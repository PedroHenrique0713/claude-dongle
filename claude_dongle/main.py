#!/usr/bin/env python3
import sys, json

from . import accounts, config, i18n, monitor, notifier
from .tray import run as tray_run

SOURCES = ("claude", "codex", "both")


def _state():
    """Config with the language already applied — every command renders or
    notifies, and both must speak the configured language."""
    state = config.load()
    i18n.set_language(state.get("language"))
    return state


def cmd_status():
    state = _state()
    u = monitor.calc_usage(state)
    print(json.dumps(u, indent=2, ensure_ascii=False))


def cmd_notify():
    state = _state()
    if state.get("sources") == "codex":
        print("Claude is not shown (source: codex) — nothing to check")
        return
    u = monitor.calc_usage(state)
    acct = state.get("claude_dir")
    notifier.check_telemetry(
        u, state, str(accounts.state_path("telemetry_state.json", acct)))
    if notifier.check_thresholds(
            u, state, str(accounts.state_path("sent_thresholds.json", acct))):
        print("Notification sent")
    else:
        print("No threshold crossed")


def cmd_accounts():
    state = _state()
    cur = accounts.key(state.get("claude_dir"))
    for d in accounts.discover(state.get("claude_dir")):
        mark = "*" if accounts.key(d) == cur else " "
        print(f"{mark} {accounts.label(d):<16} {d}")


def cmd_use():
    if len(sys.argv) < 3:
        return cmd_accounts()
    state = _state()
    d = accounts.find(sys.argv[2], state.get("claude_dir"))
    if d is None:
        print(f"No Claude Code account matches '{sys.argv[2]}'. Known:")
        return cmd_accounts()
    state["claude_dir"] = str(d)
    config.save(state)
    print(f"Watching {accounts.label(d)} ({d})")


def cmd_source():
    state = _state()
    if len(sys.argv) < 3 or sys.argv[2] not in SOURCES:
        print(f"Showing: {state.get('sources', 'claude')}")
        print("Usage: claude-dongle source claude|codex|both")
        return
    state["sources"] = sys.argv[2]
    config.save(state)
    print(f"Showing: {sys.argv[2]}")


def cmd_tray():
    state = _state()
    tray_run(state)


def cmd_config():
    state = _state()
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
        "use": cmd_use, "accounts": cmd_accounts, "source": cmd_source,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("Usage: claude-dongle [tray|status|notify|config|setup|uninstall|"
              "use|accounts|source]")
        print("  tray      open the floating dongle (normal use)")
        print("  setup     set up autostart on login (this OS)")
        print("  uninstall remove autostart")
        print("  config    open just the settings panel")
        print("  status    print the current usage as JSON")
        print("  accounts  list the Claude Code accounts on this machine")
        print("  use NAME  watch another account (e.g. use work, use default)")
        print("  source S  what the dongle shows: claude, codex or both")
        return
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
