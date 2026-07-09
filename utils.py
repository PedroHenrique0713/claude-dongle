RED = "#ff2244"
ORANGE = "#ff6600"
YELLOW = "#ffcc00"
GREEN = "#00ff88"
BG = "#0d0d0d"
BG2 = "#1a1a1a"
BG3 = "#252525"
FG = "#e8e8e8"
FG2 = "#888888"
FG3 = "#555555"
SEP = "#2a2a2a"
ACCENT = "#4488ff"


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