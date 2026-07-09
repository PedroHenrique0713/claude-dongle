import os
# XCB forçado: PyQt6 em Wayland nativo quebra posicionamento de janelas
# frameless neste setup. Precisa estar setado antes do primeiro import de PyQt6.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtWidgets import QApplication

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication([])
        _app.setQuitOnLastWindowClosed(False)
        _app.setStyle("Fusion")
    return _app


def run(cfg):
    app = get_app()
    from dongle import DongleWidget
    w = DongleWidget(cfg)
    app.exec()


class Dashboard:
    """Compat p/ `main.py config`: abre o dashboard sem dongle."""

    def __init__(self, cfg):
        get_app()
        from dashboard_ui import DashboardWidget
        self.root = DashboardWidget(cfg)

    def run(self):
        self.root.show()
