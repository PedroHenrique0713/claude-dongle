import subprocess

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
                         QLinearGradient, QPainterPath, QRegion)

import monitor, config, notifier
from utils import (color as _color, fmt_time as _fmt_time,
                   FG, FG2, FG3)

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")

DONGLE_W, DONGLE_H = 216, 36
DONGLE_R = 18
PAD = 14
BAR_Y = 27.0
CLICK_SLOP = 8  # px manhattan: abaixo disso o release conta como clique
HOT_RESET_S = 30 * 60  # sessão resetando em menos que isso: countdown ganha destaque


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
        self._w_all = None
        self._scoped_pct = None
        self._scoped_name = None
        self._stale = False
        self._source = "none"
        self._reset_5h = None
        self._reset_w = None
        self._hidden = False

        self._font_label = QFont("Cantarell", 7)
        self._font_value_5h = QFont("Cantarell", 13, QFont.Weight.Bold)
        self._font_value_7d = QFont("Cantarell", 9, QFont.Weight.DemiBold)
        self._font_reset = QFont("Cantarell", 8)
        self._font_reset_hot = QFont("Cantarell", 8, QFont.Weight.Bold)

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
            # Semanal geral e semanal por modelo (ex. Fable) são limites
            # distintos: o dongle mostra os dois
            breakdown = u.get("weekly_breakdown") or []
            w_all = next((w.get("pct") for w in breakdown
                          if w.get("kind") == "weekly_all"), None)
            scoped = [w for w in breakdown
                      if w.get("kind") == "weekly_scoped" and w.get("pct") is not None]
            top = max(scoped, key=lambda w: w["pct"]) if scoped else None
            self._w_all = w_all if w_all is not None else u.get("pct_7d", u["pct"])
            self._scoped_pct = top["pct"] if top else None
            self._scoped_name = (top.get("model") or "modelo") if top else None
            self._stale = u.get("stale", False)
            self._source = u["source"]
            self._reset_5h = u.get("seconds_until_reset_5h")
            self._reset_w = u.get("seconds_until_reset")

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

        row = lambda x, w: QRectF(x, 4, w, 20)

        # Mede os grupos da direita antes: a esquerda nunca pode invadi-los
        def group_w(label, pct):
            val = f"{pct:.0f}%" if pct is not None else "--"
            return (QFontMetrics(self._font_label).horizontalAdvance(label) + 4 +
                    QFontMetrics(self._font_value_7d).horizontalAdvance(val))

        right_w = group_w("7d", self._w_all)
        if self._scoped_pct is not None:
            right_w += 9 + group_w(self._scoped_name, self._scoped_pct)
        left_max = DONGLE_W - PAD - right_w - 8

        # Sessão (5h): a métrica dominante, à esquerda
        c5 = self._metric_color(self._s_pct)
        v5 = f"{self._s_pct:.0f}%" if self._s_pct is not None else "--"
        x = PAD
        p.setFont(self._font_label)
        p.setPen(QPen(QColor(FG2)))
        p.drawText(row(x, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "5h")
        x += QFontMetrics(self._font_label).horizontalAdvance("5h") + 4
        p.setFont(self._font_value_5h)
        p.setPen(QPen(c5))
        p.drawText(row(x, 60), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, v5)
        x += QFontMetrics(self._font_value_5h).horizontalAdvance(v5)

        # Countdown do reset da sessão; faltando pouco, destaca
        if self._reset_5h is not None and x + 5 < left_max:
            hot = self._reset_5h <= HOT_RESET_S and not self._stale
            reset_txt = _fmt_time(self._reset_5h)
            f = self._font_reset_hot if hot else self._font_reset
            p.setFont(f)
            p.setPen(QPen(QColor(FG3 if self._stale else (FG if hot else FG2))))
            p.drawText(row(x + 5, left_max - x - 5),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, reset_txt)
            x += 5 + min(QFontMetrics(f).horizontalAdvance(reset_txt), left_max - x - 5)
        self._paint_bar(p, PAD, BAR_Y, min(x, left_max) - PAD, self._s_pct, c5)

        # Semanais à direita: por modelo (ex. Fable) e geral
        right = DONGLE_W - PAD
        if self._scoped_pct is not None:
            right = self._draw_compact(p, right, self._scoped_name, self._scoped_pct)
            right -= 9
        self._draw_compact(p, right, "7d", self._w_all)
        p.end()

    def _draw_compact(self, p, right, label, pct):
        # Métrica secundária alinhada pela borda direita; devolve o x inicial
        c = self._metric_color(pct)
        val = f"{pct:.0f}%" if pct is not None else "--"
        lw = QFontMetrics(self._font_label).horizontalAdvance(label)
        vw = QFontMetrics(self._font_value_7d).horizontalAdvance(val)
        x0 = right - (lw + 4 + vw)
        r = QRectF(x0, 4, lw + 4 + vw + 2, 20)
        p.setFont(self._font_label)
        p.setPen(QPen(QColor(FG2)))
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        p.setFont(self._font_value_7d)
        p.setPen(QPen(c))
        p.drawText(QRectF(x0 + lw + 4, 4, vw + 2, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, val)
        self._paint_bar(p, x0, BAR_Y, lw + 4 + vw, pct, c)
        return x0

    def _metric_color(self, pct):
        # Cinza quando stale: dado velho nunca deve parecer vivo
        if pct is None or self._stale:
            return QColor(FG3)
        return QColor(_color(pct))

    def _paint_bar(self, p, x, y, w, pct, c):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        track = QPainterPath()
        track.addRoundedRect(QRectF(x, y, w, 2.5), 1.25, 1.25)
        p.drawPath(track)
        if pct:
            fill = QPainterPath()
            fill_w = max(2.5, w * min(pct, 100) / 100)
            fill.addRoundedRect(QRectF(x, y, fill_w, 2.5), 1.25, 1.25)
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
