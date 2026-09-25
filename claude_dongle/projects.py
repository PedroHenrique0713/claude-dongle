"""Per-model usage from the JSONL files in <account dir>/projects.

The OAuth usage API gives the official % but doesn't say WHICH model burned
the week. The session JSONLs have `message.usage` per assistant response, with
the model — complementary local data (raw tokens, not the weighted %).

Deliberately NOT per project. Attributing by the session's `cwd` is wrong
often enough to mislead (edits routinely land in repos that aren't the working
directory — worktrees, monorepos, a terminal opened elsewhere), and doing it
properly means following the edited file to the commit that closed it, which
is a different tool's job. This one stays about limits.

Incremental parser by byte offset (append-only): each refresh reads only what
grew since the last pass, so the marginal cost is ~zero. If a file shrinks
(rotation/rewrite, rare), do a full rebuild — the only correct way to avoid
double counting.

Rows are per account (the key of its config dir, see accounts.py): two
subscriptions on one machine are two different budgets.
"""
import json, os, threading
from datetime import datetime, timedelta

from . import accounts, history

_lock = threading.Lock()  # serializes refreshes: two in parallel would recount


def _ensure_schema(c):
    # Pre-accounts table (no account column): it is a cache of the JSONLs, so
    # it is dropped with its offsets and rebuilt, instead of guessing whose
    # rows those were.
    cols = [r[1] for r in c.execute("PRAGMA table_info(usage_by_model)")]
    if cols and "account" not in cols:
        c.execute("DROP TABLE usage_by_model")
        c.execute("CREATE TABLE IF NOT EXISTS jsonl_state ("
                  " path TEXT PRIMARY KEY, offset INTEGER NOT NULL) WITHOUT ROWID")
        c.execute("DELETE FROM jsonl_state")
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage_by_model ("
        " account TEXT NOT NULL DEFAULT '',"
        " model TEXT NOT NULL, day TEXT NOT NULL,"
        " input INTEGER NOT NULL DEFAULT 0, output INTEGER NOT NULL DEFAULT 0,"
        " cache_read INTEGER NOT NULL DEFAULT 0,"
        " cache_creation INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (account, model, day)) WITHOUT ROWID")
    # The per-project table and the offsets that filled it are dropped: the
    # rows were keyed by cwd, which is the attribution this module no longer
    # makes, and keeping them would leave a stale answer in the file.
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                 " AND name='usage_by_project'").fetchone():
        c.execute("DROP TABLE usage_by_project")
        c.execute("DELETE FROM jsonl_state")
    c.execute(
        "CREATE TABLE IF NOT EXISTS jsonl_state ("
        " path TEXT PRIMARY KEY, offset INTEGER NOT NULL) WITHOUT ROWID")


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
    a = agg.setdefault((model, day), [0, 0, 0, 0])
    a[0] += u.get("input_tokens") or 0
    a[1] += u.get("output_tokens") or 0
    a[2] += u.get("cache_read_input_tokens") or 0
    a[3] += u.get("cache_creation_input_tokens") or 0


def refresh(full=False, claude_dir=None):
    """Reads the new JSONL data of one account and aggregates. Returns the
    number of lines processed. Cheap enough for the dashboard's 5s timer (only
    what grew). If another refresh is already running, bail out (avoids
    concurrent recounts)."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        c = history._conn()
        _ensure_schema(c)
        acct = accounts.key(claude_dir)
        root = accounts.projects_dir(claude_dir)
        prefix = str(root) + os.sep
        offsets = {p: o for p, o in c.execute("SELECT path, offset FROM jsonl_state")
                   if p.startswith(prefix)}
        files = list(root.glob("*/*.jsonl"))
        if not full:  # a file shrank → append-only violated → rebuild
            for f in files:
                try:
                    if f.stat().st_size < offsets.get(str(f), 0):
                        full = True
                        break
                except OSError:
                    pass
        if full:
            c.execute("DELETE FROM usage_by_model WHERE account=?", (acct,))
            c.executemany("DELETE FROM jsonl_state WHERE path=?",
                          [(p,) for p in offsets])
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

        for (model, day), a in agg.items():
            c.execute(
                "INSERT INTO usage_by_model VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(account,model,day) DO UPDATE SET "
                "input=input+excluded.input, output=output+excluded.output, "
                "cache_read=cache_read+excluded.cache_read, "
                "cache_creation=cache_creation+excluded.cache_creation",
                (acct, model, day, a[0], a[1], a[2], a[3]))
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


def _top_models(c, cutoff, limit, acct=""):
    rows = c.execute(
        "SELECT model, SUM(output) AS out,"
        " SUM(input+output+cache_read+cache_creation) AS total"
        " FROM usage_by_model WHERE day >= ? AND account=?"
        " GROUP BY model ORDER BY out DESC LIMIT ?",
        (cutoff, acct, limit)).fetchall()
    return [{"name": r[0], "output": r[1] or 0, "total": r[2] or 0} for r in rows]


def daily(days=14, claude_dir=None):
    """Output tokens per day over the last `days` days, chronological, with 0
    on days without usage (so the heatmap has one cell per day)."""
    try:
        c = history._conn()
        _ensure_schema(c)
        today = datetime.now().date()
        wanted = [(today - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
                  for i in range(days)]
        rows = dict(c.execute(
            "SELECT day, SUM(output) FROM usage_by_model WHERE day >= ?"
            " AND account=? GROUP BY day",
            (wanted[0], accounts.key(claude_dir))).fetchall())
        return [(d, rows.get(d, 0) or 0) for d in wanted]
    except Exception as e:
        print(f"projects.daily: {e}", flush=True)
        return []


def summary(days=7, limit=8, claude_dir=None):
    """Top models of the last `days` days, ordered by output tokens (output =
    generated work, the least inflated proxy vs cache_read)."""
    try:
        c = history._conn()
        _ensure_schema(c)
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return {"models": _top_models(c, cutoff, limit, accounts.key(claude_dir)),
                "days": days}
    except Exception as e:
        print(f"projects.summary: {e}", flush=True)
        return {"models": [], "days": days}
