import json, os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-monitor"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "weekly_limit": 500000,
    "auto_adjust_limit": True,
    "reset_day": "thursday",
    "reset_time": "18:00",
    "reset_timezone": "America/Sao_Paulo",
    "poll_interval": 5,
    "thresholds": [50, 70, 85, 95],
    "notify_on_threshold": True,
    "notify_on_limit": True,
    "claude_dir": str(Path.home() / ".claude"),
    "log_token_source": "jsonl",
    "dongle_opacity": 0.85,
    "dongle_always_on_top": True,
    "show_mode": "dev",
    "show_processes": ["code", "gnome-terminal", "ptyxis", "claude"],
    "proxy_enabled": False,
    "proxy_port": 8081,
    "api_poll_interval": 300,  # o endpoint de usage rate-limita polling agressivo
}


def load():
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
