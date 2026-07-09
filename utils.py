# Palette aligned to GNOME Adwaita dark: neutral surfaces, a green->red
# severity ramp for usage, and a single interactive accent (Adwaita blue,
# deliberately outside the severity spectrum).
RED = "#f66151"
ORANGE = "#ff7800"
YELLOW = "#f6d32d"
GREEN = "#33d17a"
BG = "#242424"
BG2 = "#303030"
BG3 = "#3a3a3a"
FG = "#f2f2f2"
FG2 = "#9a9a9a"
FG3 = "#6b6b6b"
SEP = "#3c3c3c"
ACCENT = "#3584e4"


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
        return "agora"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours >= 24:
        days = hours // 24
        rh = hours % 24
        if rh == 0:
            return f"~{days}d"
        if mins == 0:
            return f"~{days}d {rh}h"
        return f"~{days}d {rh}h{mins:02d}"
    if hours > 0:
        if mins == 0:
            return f"~{hours}h"
        return f"~{hours}h{mins:02d}"
    return f"~{mins}m"
