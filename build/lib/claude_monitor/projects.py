"""Uso por projeto/modelo a partir dos JSONL de ~/.claude/projects.

A OAuth usage API dá o % oficial mas não diz QUAL projeto/modelo queimou a
semana. Os JSONL de sessão têm `message.usage` por resposta assistant, com
`model` e `cwd` — dado local complementar (tokens crus, não o % ponderado).

Parser incremental por offset de byte (append-only): cada refresh lê só o que
cresceu desde a última passada, então o custo marginal é ~zero. Se um arquivo
encolher (rotação/reescrita, raro), faz rebuild completo — a única forma correta
de não contar em dobro.
"""
import json, os, threading
from datetime import datetime, timedelta
from pathlib import Path

from . import history

PROJECTS_DIR = Path.home() / ".claude" / "projects"
_lock = threading.Lock()  # serializa refreshes: dois em paralelo recontariam


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
    if model.startswith("<"):  # <synthetic>: mensagens internas do Claude Code
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
    """Lê os JSONL novos e agrega. Retorna nº de linhas processadas. Barato o
    bastante para o timer de 5s do dashboard (só o que cresceu). Se outro
    refresh já roda, sai na hora (evita recontagem concorrente)."""
    if not _lock.acquire(blocking=False):
        return 0
    try:
        c = history._conn()
        _ensure_schema(c)
        offsets = dict(c.execute("SELECT path, offset FROM jsonl_state").fetchall())
        files = list(PROJECTS_DIR.glob("*/*.jsonl"))
        if not full:  # arquivo encolheu → append-only violado → rebuild
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
    """Tokens de saída por dia nos últimos `days` dias, cronológico, com 0 nos
    dias sem uso (para o heatmap ter uma célula por dia)."""
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
    """Top projetos e modelos dos últimos `days` dias, ordenados por tokens de
    saída (output = trabalho gerado, o proxy menos inflado que cache_read)."""
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
