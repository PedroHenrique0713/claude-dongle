"""Per-project/model usage from the JSONL files in ~/.claude/projects.

The OAuth usage API gives the official % but doesn't say WHICH project/model
burned the week. The session JSONLs have `message.usage` per assistant
response, with `model` and `cwd` — complementary local data (raw tokens, not
the weighted %).

Incremental parser by byte offset (append-only): each refresh reads only what
grew since the last pass, so the marginal cost is ~zero. If a file shrinks
(rotation/rewrite, rare), do a full rebuild — the only correct way to avoid
double counting.
"""
import json, os, threading
from datetime import datetime, timedelta
from pathlib import Path

from . import history

PROJECTS_DIR = Path.home() / ".claude" / "projects"
_lock = threading.Lock()  # serializes refreshes: two in parallel would recount


def _ensure_schema(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage_by_project ("
        " project TEXT NOT NULL, model TEXT NOT NULL, day TEXT NOT NULL,"
        " input INTEGER NOT NULL DEFAULT 0, output INTEGER NOT NULL DEFAULT 0,"
        " cache_read INTEGER NOT NULL DEFAULT 0,"
        " cache_creation INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (project, model, day)) WITHOUT ROWID")
    c.execute(
        "CREATE TABLE IF NOT EXISTS jsonl_state ("
        " path TEXT PRIMARY KEY, offset INTEGER NOT NULL) WITHOUT ROWID")


def _project_name(cwd):
    if not cwd:
        return "?"
    return os.path.basename(cwd.rstrip("/")) or cwd


def _agg_line(raw, agg):
    try:
        o = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    if o.get("type") != "assistant":
        return
    msg = o.get("message") or {}
    u = msg.get("usage")
    if not isinstance(u, dict):
        return
    model = msg.get("model") or "?"
    if model.startswith("<"):  # <synthetic>: Claude Code internal messages
        return
    day = (o.get("timestamp") or "")[:10]  # YYYY-MM-DD
    if len(day) != 10:
        return
    key = (_project_name(o.get("cwd")), model, day)
    a = agg.setdefault(key, [0, 0, 0, 0])
    a[0] += u.get("input_tokens") or 0
    a[1] += u.get("output_tokens") or 0
    a[2] += u.get("cache_read_input_tokens") or 0
    a[3] += u.get("cache_creation_input_tokens") or 0


def refresh(full=False):
    """Reads the new JSONL data and aggregates. Returns the number of lines
    processed. Cheap enough for the dashboard's 5s timer (only what grew). If
    another refresh is already running, bail out (avoids concurrent recounts)."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        c = history._conn()
        _ensure_schema(c)
        offsets = dict(c.execute("SELECT path, offset FROM jsonl_state").fetchall())
        files = list(PROJECTS_DIR.glob("*/*.jsonl"))
        if not full:  # a file shrank → append-only violated → rebuild
            for f in files:
                try:
                    if f.stat().st_size < offsets.get(str(f), 0):
                        full = True
                        break
                except OSError:
                    pass
        if full:
            c.execute("DELETE FROM usage_by_project")
            c.execute("DELETE FROM jsonl_state")
            c.commit()
            offsets = {}

        agg, new_offsets, lines = {}, {}, 0
        for f in files:
            path = str(f)
            try:
                size = f.stat().st_size
            except OSError:
                continue
            prev = offsets.get(path, 0)
            if size <= prev:
                continue
            try:
                with open(f, "rb") as fh:
                    fh.seek(prev)
                    for raw in fh:
                        _agg_line(raw, agg)
                        lines += 1
            except OSError:
                continue
            new_offsets[path] = size

        for (proj, model, day), a in agg.items():
            c.execute(
                "INSERT INTO usage_by_project VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(project,model,day) DO UPDATE SET "
                "input=input+excluded.input, output=output+excluded.output, "
                "cache_read=cache_read+excluded.cache_read, "
                "cache_creation=cache_creation+excluded.cache_creation",
                (proj, model, day, a[0], a[1], a[2], a[3]))
        for path, off in new_offsets.items():
            c.execute("INSERT INTO jsonl_state VALUES (?,?) "
                      "ON CONFLICT(path) DO UPDATE SET offset=excluded.offset",
                      (path, off))
        if agg or new_offsets:
            c.commit()
        return lines
    except Exception as e:
        print(f"projects.refresh: {e}", flush=True)
        return 0
    finally:
        _lock.release()


def _top(c, group_col, cutoff, limit):
    rows = c.execute(
        f"SELECT {group_col},"
        " SUM(output) AS out,"
        " SUM(input+output+cache_read+cache_creation) AS total"
        " FROM usage_by_project WHERE day >= ?"
        f" GROUP BY {group_col} ORDER BY out DESC LIMIT ?",
        (cutoff, limit)).fetchall()
    return [{"name": r[0], "output": r[1] or 0, "total": r[2] or 0} for r in rows]


def daily(days=14):
    """Output tokens per day over the last `days` days, chronological, with 0
    on days without usage (so the heatmap has one cell per day)."""
    try:
        c = history._conn()
        _ensure_schema(c)
        today = datetime.now().date()
        wanted = [(today - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
                  for i in range(days)]
        rows = dict(c.execute(
            "SELECT day, SUM(output) FROM usage_by_project WHERE day >= ?"
            " GROUP BY day", (wanted[0],)).fetchall())
        return [(d, rows.get(d, 0) or 0) for d in wanted]
    except Exception as e:
        print(f"projects.daily: {e}", flush=True)
        return []


def summary(days=7, limit=8):
    """Top projects and models of the last `days` days, ordered by output
    tokens (output = generated work, the least inflated proxy vs cache_read)."""
    try:
        c = history._conn()
        _ensure_schema(c)
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return {
            "projects": _top(c, "project", cutoff, limit),
            "models": _top(c, "model", cutoff, limit),
            "days": days,
        }
    except Exception as e:
        print(f"projects.summary: {e}", flush=True)
        return {"projects": [], "models": [], "days": days}
