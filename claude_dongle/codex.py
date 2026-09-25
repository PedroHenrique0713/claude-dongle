"""Codex CLI rate limits, read from its own session logs.

Codex writes its plan's rate-limit state into every session rollout
(<codex dir>/sessions/YYYY/MM/DD/rollout-*.jsonl): each `token_count` event
carries rate_limits.primary (the 5h window, window_minutes=300) and
.secondary (the week, 10080), each with used_percent and resets_at — the same
numbers `/status` prints. Reading them takes no network and no token, so the
dongle can never log Codex out.

Direction: used_percent is what was SPENT, the same direction as Claude's
utilization (it only climbs within one window). Codex's own screen prints the
complement ("72% left"); the dongle never does, so both tools fill up alike.

The catch: the file only moves while Codex runs. An idle Codex keeps its last
reading, which stays true on a single machine (nothing else spends the plan);
the tooltip says how old it is. Once a window's resets_at is past, that
window is known to be back at 0 — no guess involved.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

SCAN_EVERY_S = 15     # re-list the session files at most this often
SCAN_DAYS = 21        # a session opened days ago can still be the live one
TAIL_BYTES = 1 << 20  # rate_limits rides on frequent events: the tail has it

_scan = {"at": 0.0, "dir": None, "file": None}
_parsed = {"key": None, "data": None}


def _day_dirs(sessions: Path):
    """Newest day directories first (sessions/YYYY/MM/DD)."""
    out = []
    try:
        for y in sorted((p for p in sessions.iterdir() if p.is_dir()), reverse=True):
            for m in sorted((p for p in y.iterdir() if p.is_dir()), reverse=True):
                for d in sorted((p for p in m.iterdir() if p.is_dir()), reverse=True):
                    out.append(d)
                    if len(out) >= SCAN_DAYS:
                        return out
    except OSError:
        pass
    return out


def newest_rollout(codex_dir):
    """The session file written most recently (by mtime, not by name: a
    session started on Monday and still open on Thursday lives in Monday's
    directory)."""
    now = time.monotonic()
    if _scan["dir"] == str(codex_dir) and now - _scan["at"] < SCAN_EVERY_S:
        return _scan["file"]
    best, best_m = None, -1.0
    for d in _day_dirs(Path(codex_dir).expanduser() / "sessions"):
        try:
            for f in d.iterdir():
                if f.name.startswith("rollout-") and f.suffix == ".jsonl":
                    m = f.stat().st_mtime
                    if m > best_m:
                        best, best_m = f, m
        except OSError:
            continue
    _scan.update(at=now, dir=str(codex_dir), file=best)
    return best


def _epoch(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def last_rate_limits(path):
    """(rate_limits dict, event epoch) of the newest usable event in the
    file, or (None, None). Only the plan's own limit counts: other limit_ids
    ('premium') come with empty windows."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            chunk = fh.read()
    except OSError:
        return None, None
    for raw in reversed(chunk.splitlines()):
        if b'"rate_limits"' not in raw:
            continue
        try:
            ev = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue  # the first line of the tail is usually cut in half
        rl = (ev.get("payload") or {}).get("rate_limits")
        if not isinstance(rl, dict):
            continue
        if rl.get("limit_id") not in (None, "codex"):
            continue
        if not (rl.get("primary") or rl.get("secondary")):
            continue
        return rl, _epoch(ev.get("timestamp"))
    return None, None


def _window(w, now):
    """(pct, reset_epoch, window_minutes) of one window. A window whose reset
    already passed is at 0 — nothing spent since, or a newer event would say
    otherwise."""
    if not isinstance(w, dict) or w.get("used_percent") is None:
        return None, None, None
    pct = float(w["used_percent"])
    reset = w.get("resets_at")
    reset = int(reset) if isinstance(reset, (int, float)) else None
    if reset is not None and reset <= now:
        return 0.0, None, w.get("window_minutes")
    return pct, reset, w.get("window_minutes")


def read(codex_dir, now=None):
    """Codex usage in the shape the dongle paints, or None without data."""
    now = now or time.time()
    f = newest_rollout(codex_dir)
    if f is None:
        return None
    try:
        st = f.stat()
    except OSError:
        return None
    key = (str(f), st.st_size, st.st_mtime_ns)
    if _parsed["key"] != key:
        _parsed["key"] = key
        _parsed["data"] = last_rate_limits(f)
    rl, ts = _parsed["data"]
    if rl is None:
        return None
    short, long_ = rl.get("primary"), rl.get("secondary")
    # primary is the 5h window and secondary the week today; order by the
    # window length anyway rather than trust the naming forever.
    if all(isinstance(w, dict) and w.get("window_minutes") for w in (short, long_)) \
            and short["window_minutes"] > long_["window_minutes"]:
        short, long_ = long_, short
    p5, r5, w5 = _window(short, now)
    p7, r7, w7 = _window(long_, now)
    return {
        "source": "codex",
        "pct_5h": p5,
        "pct_7d": p7,
        "reset_5h_epoch": r5,
        "reset_7d_epoch": r7,
        "window_5h_min": w5,
        "window_7d_min": w7,
        "plan": rl.get("plan_type"),
        "limit_reached": rl.get("rate_limit_reached_type"),
        "seen_at": ts,
        "age_seconds": int(now - ts) if ts else None,
    }
