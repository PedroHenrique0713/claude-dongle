import json, os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-monitor"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "reset_day": "thursday",
    "reset_time": "18:00",
    "reset_timezone": "America/Sao_Paulo",
    "poll_interval": 5,
    "thresholds": [50, 70, 85, 95],
    "notify_on_threshold": True,
    "notify_on_limit": True,
    "telemetry_stale_minutes": 60,  # sem dado novo por X min → avisa uma vez
    "claude_dir": str(Path.home() / ".claude"),
    "dongle_opacity": 0.85,
    "dongle_always_on_top": True,
    "dongle_pos": None,  # [x, y] global da última posição arrastada (null = canto padrão)
    "show_mode": "dev",
    "idle_quit_minutes": 10,  # escondido por X min → o serviço se encerra (0 = nunca)
    "show_processes": ["code", "gnome-terminal", "ptyxis", "claude"],
    "api_poll_interval": 300,  # o endpoint de usage rate-limita polling agressivo
    "history_retention_days": 21,  # série temporal do burn rate (GC ao iniciar)
    "burn_lookback_minutes": 60,   # janela da regressão do burn rate
    "burn_min_points": 3,          # pontos mínimos para exibir previsão
    "forecast_notify": True,       # notificar estouro previsto antes do reset
    "forecast_expanded": False,    # seção Previsão no dashboard começa recolhida
    "projects_expanded": False,    # seção "Por projeto" no dashboard começa recolhida
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
