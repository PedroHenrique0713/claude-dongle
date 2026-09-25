import json
import os
import time

import pytest

from claude_dongle import codex

NOW = 1_790_350_000


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(codex, "_scan", {"at": 0.0, "dir": None, "file": None})
    monkeypatch.setattr(codex, "_parsed", {"key": None, "data": None})


def _event(limit_id="codex", p=40.0, s=20.0, p_reset=NOW + 3600,
           s_reset=NOW + 400_000, ts="2026-09-25T14:47:13.902Z"):
    rl = {"limit_id": limit_id, "plan_type": "plus",
          "primary": None if p is None else
          {"used_percent": p, "window_minutes": 300, "resets_at": p_reset},
          "secondary": None if s is None else
          {"used_percent": s, "window_minutes": 10080, "resets_at": s_reset}}
    return json.dumps({"timestamp": ts, "type": "event_msg",
                       "payload": {"type": "token_count", "rate_limits": rl}})


def _rollout(root, day, name, lines, mtime):
    d = root / "sessions" / "2026" / "09" / day
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"rollout-{name}.jsonl"
    f.write_text("\n".join(lines) + "\n")
    os.utime(f, (mtime, mtime))
    return f


def test_reads_the_newest_plan_limit_and_skips_other_ids(tmp_path):
    _rollout(tmp_path, "25", "a", [
        '{"half a line cut by the tail read',
        _event(p=40.0, s=20.0),
        _event(limit_id="premium", p=None, s=None),  # empty windows: ignored
    ], NOW)
    d = codex.read(tmp_path, now=NOW)
    assert (d["pct_5h"], d["pct_7d"]) == (40.0, 20.0)
    assert d["reset_5h_epoch"] == NOW + 3600
    assert d["plan"] == "plus"


def test_newest_file_wins_by_mtime_not_by_directory(tmp_path):
    # a session opened on the 23rd and still running beats a closed one
    # from the 25th
    _rollout(tmp_path, "25", "closed", [_event(p=5.0)], NOW - 7200)
    _rollout(tmp_path, "23", "open", [_event(p=61.0)], NOW - 60)
    assert codex.read(tmp_path, now=NOW)["pct_5h"] == 61.0


def test_a_passed_reset_reads_as_zero(tmp_path):
    _rollout(tmp_path, "25", "a", [_event(p=88.0, p_reset=NOW - 10)], NOW - 3000)
    d = codex.read(tmp_path, now=NOW)
    assert d["pct_5h"] == 0.0 and d["reset_5h_epoch"] is None
    assert d["pct_7d"] == 20.0  # the week did not reset


def test_windows_are_ordered_by_length_not_by_name(tmp_path):
    ev = json.loads(_event())
    rl = ev["payload"]["rate_limits"]
    rl["primary"], rl["secondary"] = rl["secondary"], rl["primary"]
    _rollout(tmp_path, "25", "a", [json.dumps(ev)], NOW)
    d = codex.read(tmp_path, now=NOW)
    assert (d["window_5h_min"], d["pct_5h"]) == (300, 40.0)


def test_no_sessions_means_no_number(tmp_path):
    assert codex.read(tmp_path, now=NOW) is None
    _rollout(tmp_path, "25", "a", ['{"type":"session_meta"}'], NOW)
    codex._scan["at"] = 0.0
    assert codex.read(tmp_path, now=NOW) is None


def test_numbers_are_spent_like_claude_not_left_like_codex_status(tmp_path):
    # used_percent climbs as Codex is used within one window; showing it as
    # "left" (100 - x) would make Codex fill backwards next to Claude.
    _rollout(tmp_path, "25", "a", [_event(p=34.0), _event(p=72.0)], NOW)
    d = codex.read(tmp_path, now=NOW)
    assert d["pct_5h"] == 72.0
