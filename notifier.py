import subprocess, json, os
from pathlib import Path
from utils import fmt_time as _fmt_time


def send(title: str, message: str, urgency: str = "normal"):
    subprocess.run(
        ["notify-send", "-a", "Claude Monitor", "-u", urgency,
         title, message],
        capture_output=True, timeout=5)


def check_thresholds(usage: dict, state: dict, sent_path: str) -> bool:
    pct = usage["pct"]
    if pct is None:
        return False
    pct_5h = usage.get("pct_5h")
    sent_file = Path(sent_path)
    sent = set()
    if sent_file.exists():
        sent = set(json.loads(sent_file.read_text()))

    # Keys carry the window's reset epoch so each new window starts clean;
    # entries from past windows are dropped on save.
    w_epoch = usage.get("reset_7d_epoch") or 0
    s_epoch = usage.get("reset_5h_epoch") or 0

    triggered = False
    for t in sorted(state["thresholds"]):
        if pct >= t and f"w{w_epoch}:{t}" not in sent:
            detail = ""
            if usage.get("total_tokens") is not None:
                detail = f" · {usage['total_tokens']:,}/{usage['limit']:,}t"
            sess = f"Sessão: {pct_5h:.0f}% " if pct_5h is not None else ""
            send(
                f"Claude Code: {pct:.0f}% semanal",
                f"{sess}· Reset {_fmt_time(usage['seconds_until_reset'])}{detail}",
                "critical" if t >= 95 else "normal"
            )
            sent.add(f"w{w_epoch}:{t}")
            triggered = True

    if pct_5h is not None:
        for t in sorted(state["thresholds"]):
            if pct_5h >= t and f"s{s_epoch}:{t}" not in sent:
                send(
                    f"Claude Code: {pct_5h:.0f}% sessão (5h)",
                    f"Semanal: {pct:.0f}% · Reset {_fmt_time(usage['seconds_until_reset'])}",
                    "critical" if t >= 95 else "normal"
                )
                sent.add(f"s{s_epoch}:{t}")
                triggered = True

    if pct >= 100 and f"w{w_epoch}:limit" not in sent:
        send(
            "Limite semanal atingido!",
            f"Reset em {_fmt_time(usage['seconds_until_reset'])}.",
            "critical"
        )
        sent.add(f"w{w_epoch}:limit")
        triggered = True

    sent = {k for k in sent
            if k.startswith(f"w{w_epoch}:") or k.startswith(f"s{s_epoch}:")}
    sent_file.parent.mkdir(parents=True, exist_ok=True)
    sent_file.write_text(json.dumps(sorted(sent)))
    return triggered
