import os, sys
# XCB só no Linux: PyQt6 em Wayland nativo quebra o posicionamento de janelas
# frameless. Em Windows/macOS a plataforma nativa é a correta — forçar xcb lá
# impediria o app de abrir. Setar antes do primeiro import de PyQt6.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from .utils import UI_FONT

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication([])
        _app.setQuitOnLastWindowClosed(False)
        _app.setStyle("Fusion")
        _app.setFont(QFont(UI_FONT, 10))  # fonte de UI da plataforma
    return _app


def run(cfg):
    app = get_app()
    from .dongle import DongleWidget
    w = DongleWidget(cfg)
    app.exec()


class Dashboard:
    """Compat p/ `main.py config`: abre o dashboard sem dongle."""

    def __init__(self, cfg):
        get_app()
        from .dashboard_ui import DashboardWidget
        self.root = DashboardWidget(cfg)

    def run(self):
        self.root.show()
