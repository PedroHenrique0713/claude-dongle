import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from claude_dongle import accounts, config, history, projects, usage_api
from claude_dongle.utils import TONES, FG3, tone


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home with three Claude Code accounts and an isolated config."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", lambda: h)
    monkeypatch.setattr(accounts, "DEFAULT_DIR", h / ".claude")
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_dir / "config.json")
    monkeypatch.setattr(usage_api, "_caches", {})
    for name, org in ((".claude", "Main Org"), (".claude-work", "Work Inc"),
                      (".claude-side-gig", "Side")):
        d = h / name
        d.mkdir()
        (d / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {}}))
        (d / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"displayName": org}}))
    (h / ".claude-viewer").mkdir()  # no login inside: not an account
    return h


def test_discover_lists_only_dirs_with_a_login_default_first(home):
    found = accounts.discover()
    assert [p.name for p in found] == [".claude", ".claude-side-gig", ".claude-work"]


def test_keys_labels_and_find(home):
    assert accounts.key(home / ".claude") == ""
    assert accounts.key(home / ".claude-work") == "work"
    assert accounts.label(home / ".claude-work") == "Work"
    assert accounts.label(home / ".claude-side-gig") == "Side Gig"
    # the default dir has no suffix: it borrows the account's own name
    assert accounts.label(home / ".claude") == "Main Org"
    assert accounts.find("WORK") == home / ".claude-work"
    assert accounts.find("default") == home / ".claude"
    assert accounts.find("nope") is None


def test_state_files_are_per_account_and_default_keeps_the_old_name(home):
    assert accounts.state_path("sent_thresholds.json", home / ".claude") \
        == config.CONFIG_DIR / "sent_thresholds.json"
    assert accounts.state_path("sent_thresholds.json", home / ".claude-work") \
        == config.CONFIG_DIR / "sent_thresholds.work.json"


def test_default_identity_prefers_the_newest_claude_json(home):
    old = home / ".claude" / ".claude.json"
    new = home / ".claude.json"
    new.write_text(json.dumps({"oauthAccount": {"displayName": "Fresh"}}))
    os.utime(old, (time.time() - 86400, time.time() - 86400))
    assert accounts.identity_path(home / ".claude") == new
    # another account never reads the home-level file
    assert accounts.identity_path(home / ".claude-work") \
        == home / ".claude-work" / ".claude.json"


def test_usage_cache_never_leaks_between_accounts(home):
    # The default account has a cached reading; "work" has no token and no
    # cache. Before accounts existed there was ONE cache: work would have
    # shown main's numbers.
    config.CONFIG_DIR.mkdir(parents=True)
    (config.CONFIG_DIR / "usage_cache.json").write_text(json.dumps(
        {"data": {"pct_5h": 12.0, "pct_7d": 34.0}, "fetched_at": time.time() - 30,
         "account": None}))
    main = usage_api.fetch(300, claude_dir=home / ".claude")
    assert main["pct_7d"] == 34.0
    assert usage_api.fetch(300, claude_dir=home / ".claude-work") is None
    assert usage_api.has_token(home / ".claude-work") is False


def test_live_keys_follow_another_writer(home):
    config.CONFIG_DIR.mkdir(parents=True)
    cfg = dict(config.DEFAULTS)
    config.save(cfg)
    assert config.sync_live(cfg) is False
    disk = dict(cfg, sources="both", claude_dir=str(home / ".claude-work"),
                dongle_opacity=0.1)
    config.CONFIG_PATH.write_text(json.dumps(disk))
    os.utime(config.CONFIG_PATH, ns=(time.time_ns() + 10**9,) * 2)
    assert config.sync_live(cfg) is True
    assert cfg["sources"] == "both"
    assert cfg["claude_dir"].endswith(".claude-work")
    assert cfg["dongle_opacity"] == config.DEFAULTS["dongle_opacity"]  # not live


def _jsonl(path, model, out, day="2026-09-20"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "assistant", "timestamp": f"{day}T10:00:00Z",
        "message": {"model": model, "usage": {"output_tokens": out}}}) + "\n")


def test_model_usage_is_per_account_and_old_rows_are_rebuilt(home, tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB_PATH", tmp_path / "h.db")
    monkeypatch.setattr(history, "_local", type("L", (), {})())
    c = sqlite3.connect(str(tmp_path / "h.db"))
    # pre-accounts table: rows nobody can attribute to an account
    c.execute("CREATE TABLE usage_by_model (model TEXT, day TEXT, input INT,"
              " output INT, cache_read INT, cache_creation INT,"
              " PRIMARY KEY (model, day))")
    c.execute("INSERT INTO usage_by_model VALUES ('ghost', '2026-09-20', 0, 999, 0, 0)")
    c.commit()
    c.close()
    _jsonl(home / ".claude" / "projects" / "a" / "s.jsonl", "claude-opus", 10)
    _jsonl(home / ".claude-work" / "projects" / "b" / "s.jsonl", "claude-sonnet", 7)
    monkeypatch.setattr(projects, "datetime", _Frozen)
    projects.refresh(claude_dir=home / ".claude")
    projects.refresh(claude_dir=home / ".claude-work")
    main = projects.summary(days=30, claude_dir=home / ".claude")["models"]
    work = projects.summary(days=30, claude_dir=home / ".claude-work")["models"]
    assert [m["name"] for m in main] == ["claude-opus"]
    assert [(m["name"], m["output"]) for m in work] == [("claude-sonnet", 7)]


class _Frozen:
    from datetime import datetime as _dt

    @classmethod
    def now(cls):
        return cls._dt(2026, 9, 25)


def test_tones_deepen_as_the_limit_fills():
    def dist(a, b):
        return sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5))
    for key, full in TONES.items():
        steps = [dist(tone(key, p), full) for p in (0, 40, 80, 100)]
        # strictly closer to the full tone at every step (a flat colour
        # would pass a non-strict check)
        assert all(a > b for a, b in zip(steps, steps[1:])), (key, steps)
        assert steps[-1] == 0, key
    assert tone("claude.5h", None) == FG3
    # the five limits are five different colours
    assert len({tone(k, 90) for k in TONES}) == len(TONES)
