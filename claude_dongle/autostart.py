"""Install/remove the dongle's login autostart, per operating system:
Linux (systemd user), macOS (LaunchAgent), Windows (Startup folder)."""
import os
import sys
import shutil
import subprocess
from pathlib import Path

_LABEL = "com.claudedongle.dongle"
# Pre-rename artifacts (the project used to be called claude-monitor):
# removed on install/uninstall so both autostarts never run side by side.
_LEGACY_LABEL = "com.claudemonitor.dongle"
_LEGACY_UNITS = ("claude-monitor.service", "claude-monitor-notify.service",
                 "claude-monitor-notify.timer")


def _tray_cmd():
    """Command that starts the dongle. Prefers the installed console script;
    falls back to the module. On Windows uses pythonw (no console window)."""
    exe = shutil.which("claude-dongle")
    if exe and sys.platform != "win32":
        return [exe, "tray"]
    py = sys.executable
    if sys.platform == "win32":
        pyw = Path(py).with_name("pythonw.exe")
        py = str(pyw) if pyw.exists() else py
    return [py, "-m", "claude_dongle", "tray"]


# ---------- Linux (systemd --user) ----------

def _linux_unit_dir():
    return Path.home() / ".config" / "systemd" / "user"


def _cleanup_legacy_linux():
    d = _linux_unit_dir()
    if not any((d / u).exists() for u in _LEGACY_UNITS):
        return
    for unit in ("claude-monitor.service", "claude-monitor-notify.timer"):
        subprocess.run(["systemctl", "--user", "disable", "--now", unit],
                       check=False, capture_output=True)
    for f in _LEGACY_UNITS:
        (d / f).unlink(missing_ok=True)


def _install_linux():
    _cleanup_legacy_linux()
    d = _linux_unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    exec_start = " ".join(_tray_cmd())
    (d / "claude-dongle.service").write_text(
        "[Unit]\n"
        "Description=Claude Code usage monitor — dongle\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n\n"
        "[Service]\nType=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=graphical-session.target\n")
    notify = " ".join(_tray_cmd()[:-1] + ["notify"])
    (d / "claude-dongle-notify.service").write_text(
        "[Unit]\nDescription=Claude Code usage monitor — limit check\n"
        "After=graphical-session.target\n\n"
        f"[Service]\nType=oneshot\nExecStart={notify}\n")
    (d / "claude-dongle-notify.timer").write_text(
        "[Unit]\nDescription=Checks Claude Code limits periodically\n\n"
        "[Timer]\nOnBootSec=2min\nOnUnitActiveSec=10min\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "claude-dongle.service"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "claude-dongle-notify.timer"], check=False)
    return "systemd user service enabled (starts on login)."


def _uninstall_linux():
    _cleanup_legacy_linux()
    for unit in ("claude-dongle.service", "claude-dongle-notify.timer"):
        subprocess.run(["systemctl", "--user", "disable", "--now", unit],
                       check=False)
    d = _linux_unit_dir()
    for f in ("claude-dongle.service", "claude-dongle-notify.service",
              "claude-dongle-notify.timer"):
        (d / f).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return "systemd user service removed."


# ---------- macOS (LaunchAgent) ----------

def _mac_plist(label=_LABEL):
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _cleanup_legacy_mac():
    p = _mac_plist(_LEGACY_LABEL)
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], check=False,
                       capture_output=True)
        p.unlink(missing_ok=True)


def _install_mac():
    _cleanup_legacy_mac()
    p = _mac_plist()
    p.parent.mkdir(parents=True, exist_ok=True)
    args = "".join(f"<string>{a}</string>" for a in _tray_cmd())
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>Label</key><string>{_LABEL}</string>\n'
        f'  <key>ProgramArguments</key><array>{args}</array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><true/>\n'
        '</dict></plist>\n')
    subprocess.run(["launchctl", "unload", str(p)], check=False,
                   capture_output=True)
    subprocess.run(["launchctl", "load", str(p)], check=False)
    return "LaunchAgent installed (starts on login)."


def _uninstall_mac():
    _cleanup_legacy_mac()
    p = _mac_plist()
    subprocess.run(["launchctl", "unload", str(p)], check=False,
                   capture_output=True)
    p.unlink(missing_ok=True)
    return "LaunchAgent removed."


# ---------- Windows (Startup folder) ----------

def _win_startup_bat(name="claude-dongle.bat"):
    base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return (Path(base) / "Microsoft" / "Windows" / "Start Menu" /
            "Programs" / "Startup" / name)


def _install_windows():
    _win_startup_bat("claude-monitor.bat").unlink(missing_ok=True)  # legacy
    bat = _win_startup_bat()
    bat.parent.mkdir(parents=True, exist_ok=True)
    cmd = " ".join(f'"{a}"' if " " in a else a for a in _tray_cmd())
    bat.write_text(f'@start "" {cmd}\r\n')
    subprocess.Popen(_tray_cmd())  # start now, without waiting for next login
    return "shortcut in the Startup folder (starts on login)."


def _uninstall_windows():
    _win_startup_bat("claude-monitor.bat").unlink(missing_ok=True)  # legacy
    _win_startup_bat().unlink(missing_ok=True)
    return "Startup folder shortcut removed."


def install():
    if sys.platform.startswith("linux"):
        return _install_linux()
    if sys.platform == "darwin":
        return _install_mac()
    if sys.platform == "win32":
        return _install_windows()
    raise RuntimeError(f"unsupported platform: {sys.platform}")


def uninstall():
    if sys.platform.startswith("linux"):
        return _uninstall_linux()
    if sys.platform == "darwin":
        return _uninstall_mac()
    if sys.platform == "win32":
        return _uninstall_windows()
    raise RuntimeError(f"unsupported platform: {sys.platform}")
