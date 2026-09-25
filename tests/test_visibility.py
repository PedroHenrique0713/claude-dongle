from claude_dongle import procs
from claude_dongle.procs import dev_open, tools_running, TERMINALS

# ptyxis keeps a background service with no window: ptyxis → ptyxis-agent
SERVICE = [(10, "ptyxis"), (11, "ptyxis-agent")]
COMM = dict(SERVICE)


def _tabs(children):
    comm = {**COMM, 30: "bash"}
    return lambda pid: any(comm.get(c) not in TERMINALS for c in children.get(pid, []))


def linux_open(procs_, children):
    return dev_open(procs_, tab_open=_tabs(children), platform="linux")


def test_terminal_service_without_a_window_is_not_open():
    assert linux_open(SERVICE, {10: [11], 11: []}) is False


def test_a_shell_under_the_terminal_is_an_open_tab():
    assert linux_open(SERVICE, {10: [11], 11: [30]}) is True


def test_codex_is_not_vs_code():
    # "code" as a prefix matched codex and codex-code-mode
    ps = SERVICE + [(20, "codex"), (21, "codex-code-mode")]
    assert linux_open(ps, {10: [11]}) is False
    assert linux_open(ps + [(22, "code")], {10: [11]}) is True
    win = [(20, "codex"), (21, "explorer")]
    assert dev_open(win, platform="win32") is False
    assert dev_open(win + [(22, "code")], platform="win32") is True
    assert dev_open(win + [(23, "windowsterminal")], platform="win32") is True


def test_tools_match_exact_names_only():
    ps = [(1, "claude-dongle"), (2, "codex-code-mode")]
    for plat in ("linux", "win32"):
        assert tools_running("claude", ps, platform=plat) is False  # the dongle itself
        assert tools_running("claude", ps + [(3, "claude")], platform=plat) is True
        assert tools_running("codex", ps + [(3, "claude")], platform=plat) is False
        assert tools_running("both", [(4, "codex")], platform=plat) is True


def test_windows_listing_drops_exe_and_this_process(monkeypatch):
    me = procs.os.getpid()
    out = ('"Code.exe","4242","Console","1","120,000 K"\n'
           f'"claude-dongle.exe","{me}","Console","1","40,000 K"\n'
           '"codex.exe","77","Console","1","90,000 K"\n'
           '"System Idle Process","0","Services","0","8 K"\n')
    monkeypatch.setattr(procs.subprocess, "check_output", lambda *a, **k: out)
    assert list(procs._windows_procs()) == [(4242, "code"), (77, "codex"),
                                           (0, "system idle process")]
