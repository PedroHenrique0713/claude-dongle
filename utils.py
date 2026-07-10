import sys

# Plataforma + fonte de UI nativa (Cantarell é do GNOME; fora do Linux fica feio)
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
UI_FONT = "SF Pro Text" if IS_MAC else "Segoe UI" if IS_WIN else "Cantarell"
# Stack p/ QSS: o Qt cai na primeira família disponível na plataforma
UI_FONT_STACK = ('"SF Pro Text", "Segoe UI", "Cantarell", '
                 '"Helvetica Neue", "Inter", sans-serif')

# Paleta dark em camadas: o fundo bem escuro faz os cards "flutuarem"; rampa de
# severidade verde->vermelho vibrante; acento azul-violeta fora do espectro.
RED = "#ff6b6b"
ORANGE = "#ffa94d"
YELLOW = "#ffd43b"
GREEN = "#5bd67d"
BG = "#111114"        # fundo da janela
BG2 = "#1a1a1f"       # superfícies baixas (compat)
BG3 = "#2b2b33"       # trilhos, inputs, chips
SURFACE = "#1c1c22"   # cards
SURFACE_HI = "#26262f"  # hover / elevado
FG = "#f5f5f8"
FG2 = "#9d9daa"
FG3 = "#63636f"
SEP = "#2a2a32"
ACCENT = "#5c8bff"    # azul moderno
ACCENT2 = "#9d7bff"   # violeta (gradientes / avatar)


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
            return f"{days}d"
        if mins == 0:
            return f"{days}d {rh}h"
        return f"{days}d {rh}h{mins:02d}"
    if hours > 0:
        if mins == 0:
            return f"{hours}h"
        return f"{hours}h{mins:02d}"
    return f"{mins}m"
