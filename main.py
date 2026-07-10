#!/usr/bin/env python3
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config, monitor, notifier
from tray import run as tray_run

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
    from tray import get_app, Dashboard
    app = get_app()
    d = Dashboard(state)
    d.run()
    app.exec()


def main():
    if len(sys.argv) < 2:
        print("Usage: claude-monitor [status|notify|tray|config]")
        return
    cmd = sys.argv[1]
    handlers = {
        "status": cmd_status,
        "notify": cmd_notify,
        "tray": cmd_tray,
        "config": cmd_config,
    }
    fn = handlers.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command: {cmd}")
        print("Available: status, notify, tray, config")


if __name__ == "__main__":
    main()
