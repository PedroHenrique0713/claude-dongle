import os, sys
# XCB only on Linux: PyQt6 on native Wayland breaks the positioning of frameless
# windows. On Windows/macOS the native platform is the right one — forcing xcb
# there would keep the app from opening. Set before the first PyQt6 import.
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
        _app.setFont(QFont(UI_FONT, 10))  # platform UI font
    return _app


def run(cfg):
    app = get_app()
    from .dongle import DongleWidget
    w = DongleWidget(cfg)
    app.exec()


class Dashboard:
    """Compat for `main.py config`: opens the dashboard without the dongle."""

    def __init__(self, cfg):
        get_app()
        from .dashboard_ui import DashboardWidget
        self.root = DashboardWidget(cfg)

    def run(self):
        self.root.show()
