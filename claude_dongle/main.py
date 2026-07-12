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
        print("Autostart configured:", autostart.install())
        print("The dongle starts on login. Run 'claude-dongle tray' to open it now.")
    except Exception as e:
        print("Failed to set up autostart:", e)


def cmd_uninstall():
    from . import autostart
    try:
        print("Autostart:", autostart.uninstall())
    except Exception as e:
        print("Failed to remove autostart:", e)


def main():
    cmds = {
        "tray": cmd_tray, "status": cmd_status, "notify": cmd_notify,
        "config": cmd_config, "setup": cmd_setup, "uninstall": cmd_uninstall,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("Usage: claude-dongle [tray|status|notify|config|setup|uninstall]")
        print("  tray      open the floating dongle (normal use)")
        print("  setup     set up autostart on login (this OS)")
        print("  uninstall remove autostart")
        print("  config    open just the settings panel")
        print("  status    print the current usage as JSON")
        return
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
