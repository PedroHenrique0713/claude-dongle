import json
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
    "poll_interval": 5,
    "thresholds": [50, 70, 85, 95],
    "notify_on_threshold": True,
    "notify_on_limit": True,
    "telemetry_stale_minutes": 60,  # no fresh data for X min → warn once
    "claude_dir": str(Path.home() / ".claude"),
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
}


def _migrate_legacy():
    if CONFIG_DIR.exists() or not LEGACY_CONFIG_DIR.exists():
        return
    try:
        shutil.copytree(LEGACY_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass


def load():
    _migrate_legacy()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        merged = DEFAULTS.copy()
        merged.update(json.loads(CONFIG_PATH.read_text()))
        return merged
    save(DEFAULTS)
    return DEFAULTS.copy()


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
