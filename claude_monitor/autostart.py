"""Instala/remove o autostart do dongle no login, por sistema operacional:
Linux (systemd user), macOS (LaunchAgent), Windows (pasta Iniciar)."""
import os
import sys
import shutil
import subprocess
from pathlib import Path

_LABEL = "com.claudemonitor.dongle"


def _tray_cmd():
    """Comando que sobe o dongle. Prefere o console-script instalado; cai no
    módulo. No Windows usa pythonw (sem janela de console)."""
    exe = shutil.which("claude-monitor")
    if exe and sys.platform != "win32":
        return [exe, "tray"]
    py = sys.executable
    if sys.platform == "win32":
        pyw = Path(py).with_name("pythonw.exe")
        py = str(pyw) if pyw.exists() else py
    return [py, "-m", "claude_monitor", "tray"]


# ---------- Linux (systemd --user) ----------

def _linux_unit_dir():
    return Path.home() / ".config" / "systemd" / "user"


def _install_linux():
    d = _linux_unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    exec_start = " ".join(_tray_cmd())
    (d / "claude-monitor.service").write_text(
        "[Unit]\n"
        "Description=Claude Code usage monitor — dongle\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n\n"
        "[Service]\nType=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=graphical-session.target\n")
    notify = " ".join(_tray_cmd()[:-1] + ["notify"])
    (d / "claude-monitor-notify.service").write_text(
        "[Unit]\nDescription=Claude Code usage monitor — checagem de limites\n"
        "After=graphical-session.target\n\n"
        f"[Service]\nType=oneshot\nExecStart={notify}\n")
    (d / "claude-monitor-notify.timer").write_text(
        "[Unit]\nDescription=Checa os limites do Claude Code periodicamente\n\n"
        "[Timer]\nOnBootSec=2min\nOnUnitActiveSec=10min\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "claude-monitor.service"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "claude-monitor-notify.timer"], check=False)
    return "systemd user service habilitado (sobe no login)."


def _uninstall_linux():
    for unit in ("claude-monitor.service", "claude-monitor-notify.timer"):
        subprocess.run(["systemctl", "--user", "disable", "--now", unit],
                       check=False)
    d = _linux_unit_dir()
    for f in ("claude-monitor.service", "claude-monitor-notify.service",
              "claude-monitor-notify.timer"):
        (d / f).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return "systemd user service removido."


# ---------- macOS (LaunchAgent) ----------

def _mac_plist():
    return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def _install_mac():
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
    return "LaunchAgent instalado (sobe no login)."


def _uninstall_mac():
    p = _mac_plist()
    subprocess.run(["launchctl", "unload", str(p)], check=False,
                   capture_output=True)
    p.unlink(missing_ok=True)
    return "LaunchAgent removido."


# ---------- Windows (pasta Iniciar) ----------

def _win_startup_bat():
    base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return (Path(base) / "Microsoft" / "Windows" / "Start Menu" /
            "Programs" / "Startup" / "claude-monitor.bat")


def _install_windows():
    bat = _win_startup_bat()
    bat.parent.mkdir(parents=True, exist_ok=True)
    cmd = " ".join(f'"{a}"' if " " in a else a for a in _tray_cmd())
    bat.write_text(f'@start "" {cmd}\r\n')
    subprocess.Popen(_tray_cmd())  # sobe já, sem esperar o próximo login
    return "atalho na pasta Iniciar (sobe no login)."


def _uninstall_windows():
    _win_startup_bat().unlink(missing_ok=True)
    return "atalho da pasta Iniciar removido."


def install():
    if sys.platform.startswith("linux"):
        return _install_linux()
    if sys.platform == "darwin":
        return _install_mac()
    if sys.platform == "win32":
        return _install_windows()
    raise RuntimeError(f"plataforma não suportada: {sys.platform}")


def uninstall():
    if sys.platform.startswith("linux"):
        return _uninstall_linux()
    if sys.platform == "darwin":
        return _uninstall_mac()
    if sys.platform == "win32":
        return _uninstall_windows()
    raise RuntimeError(f"plataforma não suportada: {sys.platform}")
