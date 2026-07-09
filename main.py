#!/usr/bin/env python3
import sys, os, threading, time, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config, monitor, notifier, proxy
from tray import run as tray_run

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")


def cmd_status():
    state = config.load()
    u = monitor.calc_usage(state)
    print(json.dumps(u, indent=2, ensure_ascii=False))


def cmd_notify():
    state = config.load()
    u = monitor.calc_usage(state)
    if notifier.check_thresholds(u, state, SENT_PATH):
        print("Notification sent")
    else:
        print("No threshold crossed")


def cmd_tray():
    state = config.load()
    if state.get("proxy_enabled"):
        proxy.start()
        def proxy_monitor_loop():
            while True:
                if not proxy.is_running():
                    proxy.start()
                time.sleep(30)
        threading.Thread(target=proxy_monitor_loop, daemon=True).start()
    tray_run(state)


def cmd_config():
    state = config.load()
    from tray import get_app, Dashboard
    app = get_app()
    d = Dashboard(state)
    d.run()
    app.exec()


def cmd_wrapper():
    state = config.load()
    print("Modo proxy: OPCIONAL e legado. O rastreamento normal já funciona")
    print("sem proxy nem wrapper (API OAuth oficial, token local do Claude Code).")
    print("Se ainda assim quiser o fallback via mitmproxy, exporte antes de rodar:")
    print("  export NODE_EXTRA_CA_CERTS=$HOME/.mitmproxy/mitmproxy-ca-cert.pem")
    print(f"  export HTTPS_PROXY=http://localhost:{state.get('proxy_port', 8081)}")
    print(f"  export HTTP_PROXY=http://localhost:{state.get('proxy_port', 8081)}")
    print("Ou use: claude-wrapper.sh (exige proxy_enabled: true no config)")


def main():
    if len(sys.argv) < 2:
        print("Usage: claude-monitor [status|notify|tray|config|wrapper]")
        return
    cmd = sys.argv[1]
    handlers = {
        "status": cmd_status,
        "notify": cmd_notify,
        "tray": cmd_tray,
        "config": cmd_config,
        "wrapper": cmd_wrapper,
    }
    fn = handlers.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command: {cmd}")
        print("Available: status, notify, tray, config, wrapper")


if __name__ == "__main__":
    main()
