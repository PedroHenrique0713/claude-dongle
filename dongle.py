import subprocess

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
                         QLinearGradient, QPainterPath, QRegion)

import monitor, config, notifier
from utils import (color as _color, fmt_time as _fmt_time,
                   FG2, FG3, ACCENT)

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")

DONGLE_W, DONGLE_H = 136, 44
DONGLE_R = 22
PAD = 16
COL_GAP = 10
COL_W = (DONGLE_W - 2 * PAD - COL_GAP) // 2
CLICK_SLOP = 8  # px manhattan: abaixo disso o release conta como clique


class DongleWidget(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        # Sem WA_TranslucentBackground (janela fica invisível no XCB+XWayland);
        # forma de pílula via setMask, transparência só via setWindowOpacity.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Popups top-level (QMenu incluso) não mapeiam neste setup — sem menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setFixedSize(DONGLE_W, DONGLE_H)
        self.setWindowOpacity(self.cfg.get("dongle_opacity", 0.85))
        self._apply_mask()

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - DONGLE_W - 12, 36)

        self._press_pos = None    # posição global do press; imutável durante o move
        self._move_anchor = None  # âncora do arrasto; esta sim é atualizada
        self._dragging = False
        self._dash = None
        self._last_usage = None

        self._s_pct = None
        self._w_pct = None
        self._stale = False
        self._source = "jobs"
        self._reset_5h = None
        self._reset_w = None
        self._scope_7d = None
        self._hidden = False

        self._font_label = QFont("Cantarell", 7)
        self._font_value = QFont("Cantarell", 10, QFont.Weight.Bold)
        self._font_small = QFont("Cantarell", 7)

        self._setup_timer()
        self.show()
        self.raise_()

    def _apply_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, DONGLE_W, DONGLE_H), DONGLE_R, DONGLE_R)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(self.cfg["poll_interval"] * 1000)
        self.poll()

    def _update_display(self):
        visible = True
        mode = self.cfg.get("show_mode", "always")
        if mode != "always":
            names = {"claude": ["claude"], "dev": ["code", "gnome-terminal", "ptyxis"],
                     "custom": self.cfg.get("show_processes", [])}.get(mode, [])
            visible = False
            if names:
                try:
                    out = subprocess.check_output(["ps", "-eo", "comm="], text=True, timeout=3)
                    visible = any(n in out for n in names)
                except Exception:
                    pass
        if visible:
            if self._hidden:
                self.show()
                self._hidden = False
        else:
            if not self._hidden:
                self.hide()
                self._hidden = True

    def poll(self):
        try:
            self._update_display()
            # cfg é compartilhado com o Dashboard: reaplica o que muda ao vivo
            self.setWindowOpacity(self.cfg.get("dongle_opacity", 0.85))
            u = monitor.calc_usage(self.cfg)

            if u.get("account_changed"):
                notifier.send(f"Conta trocada: {u['account']}",
                              f"Plano: {u['plan']} | Email: {u['email']}")

            self._s_pct = u.get("pct_5h")
            self._w_pct = u.get("pct_7d", u["pct"])
            self._stale = u.get("stale", False)
            self._source = u["source"]
            self._reset_5h = u.get("seconds_until_reset_5h")
            self._reset_w = u.get("seconds_until_reset")
            self._scope_7d = u.get("pct_7d_scope")

            self.update()

            last = self._last_usage or {}
            if (u["pct"], u.get("pct_5h")) != (last.get("pct"), last.get("pct_5h")):
                notifier.check_thresholds(u, self.cfg, SENT_PATH)
            self._last_usage = u
        except Exception:
            import traceback; traceback.print_exc()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        body = QPainterPath()
        body.addRoundedRect(QRectF(0.5, 0.5, DONGLE_W - 1, DONGLE_H - 1),
                            DONGLE_R - 0.5, DONGLE_R - 0.5)
        bg = QLinearGradient(0, 0, 0, DONGLE_H)
        bg.setColorAt(0.0, QColor("#26262a"))
        bg.setColorAt(1.0, QColor("#18181b"))
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor("#3a3a3f"), 1))
        p.drawPath(body)

        self._paint_metric(p, PAD, "5h", self._s_pct)
        self._paint_metric(p, PAD + COL_W + COL_GAP, "7d", self._w_pct,
                           scoped=bool(self._scope_7d))

        secs = [s for s in (self._reset_5h, self._reset_w) if s is not None]
        if secs:
            p.setFont(self._font_small)
            p.setPen(QPen(QColor(FG3 if self._stale else FG2)))
            p.drawText(QRectF(0, 30, DONGLE_W, 12),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       "⟳ " + _fmt_time(min(secs)))

        p.end()

    def _paint_metric(self, p, x, label, pct, scoped=False):
        # Cinza quando stale: dado velho nunca deve parecer vivo
        if pct is None:
            val, c = "--", QColor(FG3)
        elif self._stale:
            val, c = f"{pct:.0f}%", QColor(FG3)
        else:
            val, c = f"{pct:.0f}%", QColor(_color(pct))

        row = QRectF(x, 5, COL_W, 18)
        p.setFont(self._font_label)
        p.setPen(QPen(QColor(FG2)))
        p.drawText(row, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, label)
        if scoped:
            # Ponto discreto: o 7d exibido é o limite por modelo (pct_7d_scope)
            lw = QFontMetrics(self._font_label).horizontalAdvance(label)
            dot = QColor(ACCENT)
            dot.setAlpha(200)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QRectF(x + lw + 2, 13.5, 3, 3))
        p.setFont(self._font_value)
        p.setPen(QPen(c))
        p.drawText(row, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, val)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        track = QPainterPath()
        track.addRoundedRect(QRectF(x, 27, COL_W, 2.5), 1.25, 1.25)
        p.drawPath(track)
        if pct:
            fill = QPainterPath()
            fill_w = max(2.5, COL_W * min(pct, 100) / 100)
            fill.addRoundedRect(QRectF(x, 27, fill_w, 2.5), 1.25, 1.25)
            p.setBrush(c)
            p.drawPath(fill)

    def mousePressEvent(self, event):
        # A referência do clique-vs-arrasto NÃO muda durante o move
        self._press_pos = event.globalPosition().toPoint()
        self._move_anchor = self._press_pos
        self._dragging = False

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        gp = event.globalPosition().toPoint()
        if (gp - self._press_pos).manhattanLength() > CLICK_SLOP:
            self._dragging = True
        if self._dragging:
            self.move(self.pos() + gp - self._move_anchor)
        self._move_anchor = gp

    def mouseReleaseEvent(self, event):
        if self._press_pos is None:
            return
        moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
        was_drag = self._dragging or moved >= CLICK_SLOP
        self._press_pos = None
        self._dragging = False
        if was_drag:
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._open_dashboard()

    def _open_dashboard(self):
        if self._dash is not None:
            try:
                self._dash.raise_()
                self._dash.activateWindow()
                return
            except RuntimeError:
                self._dash = None
        try:
            from dashboard_ui import DashboardWidget
            d = DashboardWidget(self.cfg, dongle=self)
            d.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            d.destroyed.connect(self._clear_dash)
            self._dash = d
            d.show()
            d.raise_()
            d.activateWindow()
        except Exception:
            import traceback; traceback.print_exc()

    def _clear_dash(self, *args):
        self._dash = None
