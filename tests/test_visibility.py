from claude_dongle.dongle import dev_open, tools_running, TERMINALS

# ptyxis keeps a background service with no window: ptyxis → ptyxis-agent
SERVICE = [(10, "ptyxis"), (11, "ptyxis-agent")]
CHILDREN = {10: [11], 11: []}
COMM = dict(SERVICE)


def _tabs(children):
    comm = {**COMM, 30: "bash"}
    return lambda pid: any(comm.get(c) not in TERMINALS for c in children.get(pid, []))


def test_terminal_service_without_a_window_is_not_open():
    assert dev_open(SERVICE, tab_open=_tabs(CHILDREN)) is False


def test_a_shell_under_the_terminal_is_an_open_tab():
    assert dev_open(SERVICE, tab_open=_tabs({10: [11], 11: [30]})) is True


def test_codex_is_not_vs_code():
    # "code" as a prefix matched codex and codex-code-mode
    procs = SERVICE + [(20, "codex"), (21, "codex-code-mode")]
    assert dev_open(procs, tab_open=_tabs(CHILDREN)) is False
    assert dev_open(procs + [(22, "code")], tab_open=_tabs(CHILDREN)) is True


def test_tools_match_exact_names_only():
    procs = [(1, "claude-dongle"), (2, "codex-code-mode")]
    assert tools_running("claude", procs) is False  # the dongle itself
    assert tools_running("claude", procs + [(3, "claude")]) is True
    assert tools_running("codex", procs + [(3, "claude")]) is False
    assert tools_running("both", [(4, "codex")]) is True
