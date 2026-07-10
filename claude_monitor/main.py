#!/usr/bin/env python3
import sys, json

from . import config, monitor, notifier
from .tray import run as tray_run

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")
TELEMETRY_PATH = str(config.CONFIG_DIR / "telemetry_state.json")


def cmd_status():
    state = config.load()
    u = monitor.calc_usage(state)
    print(json.dumps(u, indent=2, ensure_ascii=False))


def cmd_notify():
    state = config.load()
    u = monitor.calc_usage(state)
    notifier.check_telemetry(u, state, TELEMETRY_PATH)
    if notifier.check_thresholds(u, state, SENT_PATH):
        print("Notification sent")
    else:
        print("No threshold crossed")


def cmd_tray():
    state = config.load()
    tray_run(state)


def cmd_config():
    state = config.load()
    from .tray import get_app, Dashboard
    app = get_app()
    d = Dashboard(state)
    d.run()
    app.exec()


def cmd_setup():
    from . import autostart
    try:
        print("Autostart configurado:", autostart.install())
        print("O dongle sobe no login. Rode 'claude-monitor tray' para abrir já.")
    except Exception as e:
        print("Falha ao configurar autostart:", e)


def cmd_uninstall():
    from . import autostart
    try:
        print("Autostart:", autostart.uninstall())
    except Exception as e:
        print("Falha ao remover autostart:", e)


def main():
    cmds = {
        "tray": cmd_tray, "status": cmd_status, "notify": cmd_notify,
        "config": cmd_config, "setup": cmd_setup, "uninstall": cmd_uninstall,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("Uso: claude-monitor [tray|status|notify|config|setup|uninstall]")
        print("  tray      abre o dongle flutuante (uso normal)")
        print("  setup     configura o autostart no login (este SO)")
        print("  uninstall remove o autostart")
        print("  config    abre só o painel de configuração")
        print("  status    imprime o uso atual em JSON")
        return
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
