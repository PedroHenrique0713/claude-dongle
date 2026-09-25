"""Which dev tools are open: decides when the dongle shows (show_mode).

Stdlib only, so it is tested without PyQt6 like the rest of the core.

Names match exactly where the platform gives clean names (Linux comm,
Windows image name without .exe): a prefix "code" matched "codex" and
"codex-code-mode", and "claude" matched this very process (claude-dongle).
macOS keeps the prefix match — `ps` comm there is looser and untested.
"""
import os
import subprocess
import sys

IS_LINUX = sys.platform.startswith("linux")
IS_WIN = sys.platform == "win32"

# macOS: prefix match on names, the only thing the cheap listing gives.
DEV_PROCS = ["code", "cursor", "ptyxis", "gnome-terminal", "kgx", "konsole",
             "alacritty", "kitty", "wezterm", "tilix", "windowsterminal",
             "iterm", "terminal"]
# An editor's main process lives only while a window is open.
EDITORS = {"code", "code-oss", "codium", "cursor", "zed", "zed-editor"}
# Linux terminal emulators (comm, truncated at 15 chars by the kernel).
# Ptyxis and GNOME Terminal keep a background service alive with no window at
# all (`ptyxis --gapplication-service` → ptyxis-agent), so a terminal counts
# only while it has a child that is not one of its own helpers: a shell, i.e.
# an open tab. Matching the name alone kept the dongle on screen forever after
# the last terminal closed.
TERMINALS = {"ptyxis", "ptyxis-agent", "gnome-terminal-", "kgx", "konsole",
             "alacritty", "kitty", "wezterm-gui", "tilix", "xterm", "foot",
             "xfce4-terminal", "terminator", "blackbox"}
# Windows terminals exit with their last window: the name is enough there.
WIN_TERMINALS = {"windowsterminal", "wezterm-gui", "alacritty"}
# show_mode=claude: the AI tools themselves.
TOOLS = {"claude": {"claude", "claude.exe"}, "codex": {"codex"}}


def _children(pid):
    """Linux: child pids of a process (every thread's list: a terminal may
    spawn its shells from a worker thread)."""
    out = []
    try:
        tasks = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return out
    for t in tasks:
        try:
            with open(f"/proc/{pid}/task/{t}/children") as f:
                out += [int(c) for c in f.read().split()]
        except (OSError, ValueError):
            continue
    return out


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip().lower()
    except OSError:
        return None


def _tab_open(pid):
    """A terminal process has a child that is not one of its own helpers
    (ptyxis → ptyxis-agent is a helper; ptyxis-agent → bash is a tab)."""
    return any(_comm(c) not in TERMINALS | {None} for c in _children(pid))


def _linux_procs():
    """(pid, comm) of every process but this one — it must never be the
    reason it stays on screen. Reads /proc directly instead of forking `ps`:
    14ms against 114ms, every 5s all day."""
    me = os.getpid()
    try:
        entries = os.scandir("/proc")
    except OSError:
        return
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        c = _comm(entry.name)
        if c is not None:  # None: it died between the scan and the read
            yield int(entry.name), c


def _windows_procs():
    """(pid, image name without .exe), from `tasklist` (no /proc there)."""
    me = os.getpid()
    try:
        out = subprocess.check_output(["tasklist", "/fo", "csv", "/nh"],
                                      text=True, timeout=3)
    except Exception:
        return
    for ln in out.splitlines():
        cols = ln.strip().strip('"').split('","')
        if len(cols) < 2 or not cols[1].isdigit() or int(cols[1]) == me:
            continue
        name = cols[0].lower()
        yield int(cols[1]), name[:-4] if name.endswith(".exe") else name


def _mac_names():
    try:
        out = subprocess.check_output(["ps", "-eo", "comm="], text=True, timeout=3)
    except Exception:
        return
    # comm may include a path on macOS: keep just the basename
    for line in out.splitlines():
        yield line.strip().rsplit("/", 1)[-1].lower()


def process_names():
    """Running process names, lowercase (show_mode=custom). Empty if the
    listing is unavailable."""
    if IS_LINUX:
        return (c for _, c in _linux_procs())
    if IS_WIN:
        return (c for _, c in _windows_procs())
    return _mac_names()


def dev_open(procs=None, tab_open=_tab_open, platform=None):
    """An editor window or a terminal tab is open (show_mode=dev).

    procs: (pid, name) pairs, the live listing when None. On Linux it stops
    at the first hit and reads children only for terminal processes, so it
    costs what the old name-only scan did."""
    platform = platform or sys.platform
    if platform.startswith("linux"):
        for pid, comm in (_linux_procs() if procs is None else procs):
            if comm in EDITORS or (comm in TERMINALS and tab_open(pid)):
                return True
        return False
    if platform == "win32":
        return any(c in EDITORS or c in WIN_TERMINALS
                   for _, c in (_windows_procs() if procs is None else procs))
    names = _mac_names() if procs is None else (c for _, c in procs)
    return any(p.startswith(n) for p in names for n in DEV_PROCS)


def tools_running(sources, procs=None, platform=None):
    """The AI tool(s) the dongle shows are running (show_mode=claude)."""
    want = set().union(*(TOOLS[s] for s in
                         (("claude", "codex") if sources == "both" else (sources,))))
    platform = platform or sys.platform
    if platform.startswith("linux") or platform == "win32":
        if procs is None:
            procs = _linux_procs() if platform.startswith("linux") else _windows_procs()
        return any(c in want for _, c in procs)
    names = _mac_names() if procs is None else (c for _, c in procs)
    return any(p.startswith(n) for p in names for n in want)
