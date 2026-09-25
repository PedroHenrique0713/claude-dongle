import json
import os
import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-dongle"
CONFIG_PATH = CONFIG_DIR / "config.json"
# Pre-rename config dir (the project used to be called claude-monitor):
# copied once, on first load, so settings/history survive the rename.
LEGACY_CONFIG_DIR = Path.home() / ".config" / "claude-monitor"

DEFAULTS = {
    # Manual fallback for the weekly reset, used only when the API never
    # answered (it normally provides the real resets_at). null = unknown:
    # the UI shows "--" instead of guessing. Example: "thursday", "18:00",
    # "America/New_York" (reset_timezone null = system local timezone).
    "reset_day": None,
    "reset_time": None,
    "reset_timezone": None,
    # "auto" follows the system language (pt-BR when it speaks Portuguese),
    # or pin it: "en" / "pt-BR".
    "language": "auto",
    "battery_saver": True,         # halve the timers while on battery
    "poll_interval": 5,
    "thresholds": [50, 70, 85, 95],
    "notify_on_threshold": True,
    "notify_on_limit": True,
    "notify_on_reset": True,       # tell me when a spent limit comes back
    "notify_on_telemetry": True,   # warn when the monitor loses its data source
    # Minimum gap between two routine notifications (critical ones ignore it).
    "notify_cooldown_minutes": 15,
    "telemetry_stale_minutes": 60,  # no fresh data for X min → warn once
    # Which Claude Code account the dongle watches: its config dir (~/.claude,
    # or the CLAUDE_CONFIG_DIR of another account, e.g. ~/.claude-work).
    "claude_dir": str(Path.home() / ".claude"),
    # What the dongle shows: "claude", "codex" or "both" (split in half).
    "sources": "claude",
    "codex_dir": os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"),
    "dongle_opacity": 0.85,
    "dongle_always_on_top": True,
    "dongle_pos": None,  # [x, y] of the last dragged position (null = default corner)
    "show_mode": "dev",
    "idle_quit_minutes": 10,  # hidden for X min → the service exits (0 = never)
    "show_processes": ["code", "claude"],  # process names for show_mode=custom
    "api_poll_interval": 300,  # the usage endpoint rate-limits aggressive polling
    "history_retention_days": 21,  # burn-rate time series (GC'd on start)
    "burn_lookback_minutes": 60,   # burn-rate regression window
    "burn_min_points": 3,          # minimum points to show a forecast
    "forecast_notify": True,       # notify on predicted overflow before the reset
    "forecast_expanded": False,    # Forecast section starts collapsed
    "projects_expanded": False,    # "By project" section starts collapsed
    "settings_expanded": False,    # Settings section starts collapsed
    "hours_expanded": False,       # "By hour" section starts collapsed
    "hours_days": 14,              # history window for the hourly profile
}


def _migrate_legacy():
    if CONFIG_DIR.exists() or not LEGACY_CONFIG_DIR.exists():
        return
    try:
        shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass


# Keys another process may change under a running dongle (the CLI's
# `use` / `source`): the dongle re-reads just these when the file changes.
LIVE_KEYS = ("claude_dir", "sources")
_seen_mtime = None


def _mtime():
    try:
        return CONFIG_PATH.stat().st_mtime_ns
    except OSError:
        return None


def load():
    global _seen_mtime
    _migrate_legacy()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        merged = DEFAULTS.copy()
        merged.update(json.loads(CONFIG_PATH.read_text()))
        _seen_mtime = _mtime()
        return merged
    save(DEFAULTS)
    return DEFAULTS.copy()


def save(cfg):
    global _seen_mtime
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    _seen_mtime = _mtime()


def sync_live(cfg) -> bool:
    """Pull LIVE_KEYS from disk into cfg when another process rewrote the
    file. True when something changed."""
    global _seen_mtime
    m = _mtime()
    if _seen_mtime is None:
        # cfg did not come from this file (tests, `config` built by hand):
        # watch from here on instead of overwriting it with the disk
        _seen_mtime = m
        return False
    if m is None or m == _seen_mtime:
        return False
    _seen_mtime = m
    try:
        disk = json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    changed = False
    for k in LIVE_KEYS:
        if k in disk and disk[k] != cfg.get(k):
            cfg[k] = disk[k]
            changed = True
    return changed
