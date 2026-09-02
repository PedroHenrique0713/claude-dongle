import sys
import time

from .i18n import t as _t

# Platform + native UI font (Cantarell is GNOME's; it looks off outside Linux)
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
UI_FONT = "SF Pro Text" if IS_MAC else "Segoe UI" if IS_WIN else "Cantarell"
# Stack for QSS: Qt falls back to the first family available on the platform
UI_FONT_STACK = ('"SF Pro Text", "Segoe UI", "Cantarell", '
                 '"Helvetica Neue", "Inter", sans-serif')

# Layered dark palette: the very dark background makes cards "float"; vivid
# green->red severity ramp; blue-violet accent outside that spectrum.
RED = "#ff6b6b"
ORANGE = "#ffa94d"
YELLOW = "#ffd43b"
GREEN = "#5bd67d"
BG = "#111114"        # window background
BG2 = "#1a1a1f"       # low surfaces (compat)
BG3 = "#2b2b33"       # tracks, inputs, chips
SURFACE = "#1c1c22"   # cards
SURFACE_HI = "#26262f"  # hover / elevated
FG = "#f5f5f8"
FG2 = "#9d9daa"
FG3 = "#63636f"
SEP = "#2a2a32"
ACCENT = "#5c8bff"    # modern blue
ACCENT2 = "#9d7bff"   # violet (gradients / avatar)


def color(pct: float) -> str:
    if pct >= 95:
        return RED
    if pct >= 80:
        return ORANGE
    if pct >= 50:
        return YELLOW
    return GREEN


def fmt_time(seconds):
    if seconds is None:
        return "--"
    if seconds <= 0:
        return _t("time.now")
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours >= 24:
        days = hours // 24
        rh = hours % 24
        if rh == 0:
            return f"{days}d"
        if mins == 0:
            return f"{days}d {rh}h"
        return f"{days}d {rh}h{mins:02d}"
    if hours > 0:
        if mins == 0:
            return f"{hours}h"
        return f"{hours}h{mins:02d}"
    return f"{mins}m"


def limits_blocking(pct_5h, pct_week_all, threshold=100):
    """True when a limit that stops EVERY model is exhausted.

    A scoped weekly limit (Fable at 100%) is NOT one of them: the other models
    keep running against the overall week, so painting the dongle red for it
    cried wolf. Only the 5h session and the overall week stop the work.
    """
    return any(p is not None and p >= threshold for p in (pct_5h, pct_week_all))

def availability(pct_5h, weekly):
    """What can still be used right now.

    weekly: the weekly_breakdown list ({kind, model, pct, reset}).
    Returns {"blocked": [{label, reset, scope}], "everything_blocked": bool},
    where scope=None means a limit that stops every model. A scoped model at
    100% only blocks itself — the others keep running against the overall
    week, which is why it never counts as everything_blocked.
    """
    blocked = []
    everything = False
    if pct_5h is not None and pct_5h >= 100:
        blocked.append({"label": None, "scope": None, "reset": None, "kind": "session"})
        everything = True
    for w in weekly or []:
        pct = w.get("pct")
        if pct is None or pct < 100:
            continue
        if w.get("kind") == "weekly_all":
            blocked.append({"label": None, "scope": None, "reset": w.get("reset"),
                            "kind": "weekly_all"})
            everything = True
        elif w.get("kind") == "weekly_scoped":
            blocked.append({"label": w.get("model"), "scope": w.get("model"),
                            "reset": w.get("reset"), "kind": "weekly_scoped"})
    return {"blocked": blocked, "everything_blocked": everything}


def availability_text(usage):
    """One line saying what is spent and when it comes back, or None.

    Shared by the panel and the dongle tooltip so they can never disagree
    about whether work is still possible.
    """
    av = usage.get("availability") or {}
    blocked = av.get("blocked") or []
    if not blocked:
        return None
    now = time.time()

    def left(reset):
        return fmt_time(max(0, int(reset - now))) if reset else None

    if av.get("everything_blocked"):
        hard = next(b for b in blocked if b["scope"] is None)
        session = hard["kind"] == "session"
        label = _t("usage.session") if session else _t("usage.week")
        t_left = left(hard.get("reset")) or fmt_time(
            usage.get("seconds_until_reset_5h") if session
            else usage.get("seconds_until_reset"))
        return (_t("avail.spent_all", label=label, time=t_left) if t_left
                else _t("avail.spent_all_notime", label=label))
    models = [b["scope"] for b in blocked if b["scope"]]
    if not models:
        return None
    t_left = left(blocked[0].get("reset")) or fmt_time(usage.get("seconds_until_reset"))
    return _t("avail.spent_scope", model=", ".join(models), time=t_left)
