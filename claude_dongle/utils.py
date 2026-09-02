import sys

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
        return "now"
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
