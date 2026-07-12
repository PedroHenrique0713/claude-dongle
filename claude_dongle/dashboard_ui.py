import os, sys, time, threading, math
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from . import monitor, config, history, projects
from .utils import (color, fmt_time, RED, GREEN, BG, BG2, BG3, FG, FG2, FG3, SEP,
                   ACCENT, ACCENT2, SURFACE, SURFACE_HI, UI_FONT, UI_FONT_STACK)


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(int(n))

from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QHBoxLayout, QFrame, QPushButton, QSizePolicy,
                             QSlider, QRadioButton, QButtonGroup, QLineEdit,
                             QGraphicsOpacityEffect)
from PyQt6.QtCore import (Qt, QTimer, QRectF, QPointF, pyqtProperty,
                          QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (QPainter, QColor, QBrush, QFont, QFontMetrics, QPen,
                         QPainterPath, QLinearGradient)

REFRESH_MS = 5000
TICK_MS = 1000          # live countdown (only recomputes time texts)
WINDOW_5H = 5 * 3600    # window durations, for the pace bar
WINDOW_7D = 7 * 86400
SOURCE_LABELS = {"api": "official API", "none": "no data"}
# animations only in real use; offscreen (screenshots/headless) paints the final state
_ANIMATE = os.environ.get("QT_QPA_PLATFORM") != "offscreen"
SHOW_MODES = [("Always visible", "always"),
              ("Only with Claude Code", "claude"),
              ("Only with VS Code / terminal", "dev"),
              ("Specific processes", "custom")]


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def _qss():
    return f"""
    QWidget {{ font-family: {UI_FONT_STACK}; color: {FG}; font-size: 12px; }}
    #dashRoot {{ background: {BG}; }}
    QLabel {{ background: transparent; }}

    QFrame[card="true"] {{
        background: {SURFACE};
        border: 1px solid rgba(255, 255, 255, 0.055);
        border-radius: 16px;
    }}
    QLabel[pill="true"] {{
        background: {_rgba(ACCENT, 40)}; color: #cddaff;
        border-radius: 10px; padding: 3px 11px;
        font-size: 10px; font-weight: 700;
    }}

    QPushButton {{
        background: {BG3}; color: {FG}; border: none;
        border-radius: 10px; padding: 9px 18px; font-size: 12px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {SURFACE_HI}; }}
    QPushButton[kind="primary"] {{ background: {ACCENT}; color: white; }}
    QPushButton[kind="primary"]:hover {{ background: #7099ff; }}
    QPushButton[kind="ghost"] {{
        background: transparent; color: {ACCENT}; padding: 6px 10px; font-weight: 600;
    }}
    QPushButton[kind="ghost"]:hover {{ background: {_rgba(ACCENT, 28)}; border-radius: 8px; }}
    QPushButton[kind="danger"] {{ background: transparent; color: {RED}; padding: 9px 14px; }}
    QPushButton[kind="danger"]:hover {{ background: {_rgba(RED, 28)}; border-radius: 10px; }}
    QPushButton[kind="icon"] {{
        background: transparent; color: {FG3}; padding: 2px 5px; font-size: 12px;
    }}
    QPushButton[kind="icon"]:hover {{ background: {BG3}; color: {FG}; border-radius: 7px; }}
    QPushButton[kind="disclosure"] {{
        background: transparent; color: {FG}; border: none;
        text-align: left; padding: 2px 0; font-size: 13px; font-weight: 600;
    }}
    QPushButton[kind="disclosure"]:hover {{ color: {ACCENT}; }}

    QLineEdit {{
        background: {BG3}; color: {FG}; border: 1.5px solid transparent;
        border-radius: 9px; padding: 5px 6px; font-size: 12px; font-weight: 600;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; background: {SURFACE_HI}; }}

    QFrame[chip="true"] {{ background: {BG3}; border-radius: 10px; }}
    QLineEdit[bare="true"] {{
        background: transparent; border: none; padding: 3px 0;
        font-size: 13px; font-weight: 700; color: {FG};
    }}
    QLineEdit[bare="true"]:focus {{ background: transparent; border: none; }}
    QPushButton[kind="chipx"] {{
        background: transparent; color: {FG3}; border: none;
        border-radius: 8px; font-size: 10px; padding: 0;
    }}
    QPushButton[kind="chipx"]:hover {{ color: white; background: {RED}; }}

    QSlider::groove:horizontal {{ height: 6px; background: {BG3}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        width: 16px; height: 16px; margin: -6px 0;
        border-radius: 8px; background: white; border: 3px solid {ACCENT};
    }}
    QSlider::handle:horizontal:hover {{ background: #eef3ff; }}

    QRadioButton {{ spacing: 11px; font-size: 12px; color: {FG}; background: transparent; padding: 4px 0; }}
    QRadioButton::indicator {{
        width: 16px; height: 16px; border-radius: 9px;
        border: 2px solid #45454f; background: transparent;
    }}
    QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
    QRadioButton::indicator:checked {{
        width: 16px; height: 16px; border-radius: 9px;
        border: 2px solid {ACCENT};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fp:0.5, fs:0.5,
                    stop:0 white, stop:0.42 white, stop:0.5 {ACCENT}, stop:1 {ACCENT});
    }}
    """


class UsageBar(QWidget):
    """Thin rounded bar: track + severity-colored fill, plus a PACE marker —
    where usage would sit if it were linear across the window. Fill past
    the marker = burning ahead of schedule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(9)
        self.setMinimumWidth(120)
        self._pct = None
        self._color = QColor(FG3)
        self._pace = None  # 0..1 fraction of the window elapsed

    def set_value(self, pct, color_hex, pace=None):
        self._pct = pct
        self._color = QColor(color_hex)
        self._pace = pace
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        r = h / 2
        p.setBrush(QBrush(QColor(BG3)))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        if self._pct is not None and self._pct > 0:
            fill = max(float(h), w * min(self._pct, 100) / 100)
            p.setBrush(QBrush(self._color))
            p.drawRoundedRect(QRectF(0, 0, fill, h), r, r)
        if self._pace is not None and 0.02 < self._pace < 0.99:
            x = w * self._pace
            p.setPen(QPen(QColor("#e8e8e8"), 1.4))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.end()


class UsageRing(QWidget):
    """Ring gauge: track + severity-colored arc, a PACE tick (where usage
    would sit if linear), the % in the center and label/subtext below. Flexible
    width: the radius shrinks on its own when many rings sit side by side."""

    DIAM = 84
    TH = 8

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label
        self._pace = None
        self._sub = ""
        self._stale = False
        self._display_pct = 0.0   # what gets drawn (chases the target with easing)
        self._target_pct = None   # the actual usage value
        self._anim = QPropertyAnimation(self, b"arcPct", self)
        self._anim.setDuration(600)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(76)
        self.setFixedHeight(self.DIAM + 46)

    def _get_arc(self):
        return self._display_pct

    def _set_arc(self, v):
        self._display_pct = float(v)
        self.update()

    arcPct = pyqtProperty(float, _get_arc, _set_arc)

    def set_data(self, pct, seconds, stale, window_s=None):
        self._stale = stale
        prev = self._target_pct
        self._target_pct = pct
        if pct is None:
            self._pace = None
            self._sub = ""
            self._display_pct = 0.0
            self.update()
            return
        pace = None
        if window_s and seconds is not None:
            pace = max(0.0, min(1.0, 1 - seconds / window_s))
        self._pace = pace
        sub = fmt_time(seconds) if seconds is not None else ""
        if pace is not None and not stale:  # usage vs. elapsed time
            expected = pace * 100
            if pct > expected + 8:
                sub += "  ·  high"
            elif pct < expected - 8:
                sub += "  ·  low"
            else:
                sub += "  ·  on pace"
        self._sub = sub
        # animate arc/number from the previous value (or 0 on first show) to the new one
        if _ANIMATE and (prev is None or abs(prev - pct) > 0.05):
            self._anim.stop()
            self._anim.setStartValue(0.0 if prev is None else float(self._display_pct))
            self._anim.setEndValue(float(pct))
            self._anim.start()
        elif self._anim.state() != QPropertyAnimation.State.Running:
            self._display_pct = float(pct)  # no animation in flight: sync directly
            self.update()
        else:
            self.update()  # animation running: only redraw sub/countdown

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w = self.width()
        R = min(self.DIAM, w - 10) / 2
        cx, cy = w / 2, R + 5
        rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)
        has = self._target_pct is not None
        disp = self._display_pct
        c = QColor(FG3) if (self._stale or not has) else QColor(color(disp))

        pen = QPen(QColor(BG3), self.TH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, 0, 360 * 16)
        if has and disp > 0:  # arc: from top, clockwise; grows with the animation
            pen2 = QPen(c, self.TH)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen2)
            p.drawArc(rect, 90 * 16, -int(min(disp, 100) / 100 * 360) * 16)
        if self._pace is not None and 0.02 < self._pace < 0.99:
            ang = math.radians(90 - self._pace * 360)
            r0, r1 = R - self.TH / 2 - 2, R + self.TH / 2 + 2
            cs, sn = math.cos(ang), math.sin(ang)
            p.setPen(QPen(QColor("#e8e8e8"), 1.4))
            p.drawLine(QPointF(cx + r0 * cs, cy - r0 * sn),
                       QPointF(cx + r1 * cs, cy - r1 * sn))

        # % in the center: big number + smaller '%', both scale with the radius.
        # the number counts up along with the arc (uses the animated value)
        num = f"{disp:.0f}" if has else "--"
        fn = QFont(UI_FONT, max(11, int(R * 0.42)), QFont.Weight.Bold)
        fm = QFontMetrics(fn)
        nw = fm.horizontalAdvance(num)
        fs = QFont(UI_FONT, max(8, int(R * 0.26)), QFont.Weight.DemiBold)
        sw = QFontMetrics(fs).horizontalAdvance("%") if has else 0
        bx = cx - (nw + sw + 1) / 2
        p.setFont(fn)
        p.setPen(QPen(QColor(FG if has else FG3)))
        p.drawText(QRectF(bx, cy - R, nw + 4, 2 * R),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, num)
        if has:
            p.setFont(fs)
            p.setPen(QPen(QColor(FG2)))
            p.drawText(QRectF(bx + nw + 1, cy - R + 1, sw + 4, 2 * R),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "%")

        # label + subtext
        p.setFont(QFont(UI_FONT, 10, QFont.Weight.DemiBold))
        p.setPen(QPen(QColor(FG)))
        p.drawText(QRectF(0, cy + R + 6, w, 15), Qt.AlignmentFlag.AlignHCenter, self._label)
        if self._sub:
            p.setFont(QFont(UI_FONT, 8))
            p.setPen(QPen(QColor(FG3)))
            p.drawText(QRectF(0, cy + R + 22, w, 13), Qt.AlignmentFlag.AlignHCenter, self._sub)
        p.end()


class SparklineWidget(QWidget):
    """Current-window usage series, hand painted: line + fill + last-point dot."""

    MIN_SPAN_S = 1800  # minimum X domain; 2-3 points don't become a stretched line

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setMinimumWidth(120)
        self._points = []
        self._color = QColor(FG3)

    def set_series(self, points, color_hex):
        self._points = points
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        ceil_pen = QPen(QColor(BG3))
        ceil_pen.setWidthF(1.0)
        p.setPen(ceil_pen)
        p.drawLine(QPointF(0, 0.5), QPointF(w, 0.5))  # ceiling = 100%
        pts = self._points
        if not pts:
            p.end()
            return
        t0 = pts[0][0]
        t1 = max(time.time(), t0 + self.MIN_SPAN_S)

        def xy(t, pct):
            x = (t - t0) / (t1 - t0) * (w - 4) + 2
            y = h - 2 - (min(pct, 100.0) / 100.0) * (h - 4)
            return QPointF(x, y)

        stride = max(1, len(pts) // max(1, int(w)))  # 1 point per pixel is enough
        draw = pts[::stride]
        if draw[-1] != pts[-1]:
            draw.append(pts[-1])
        path = QPainterPath(xy(*draw[0]))
        for t, pct in draw[1:]:
            path.lineTo(xy(t, pct))
        first, last = xy(*draw[0]), xy(*draw[-1])
        fill = QPainterPath(path)
        fill.lineTo(last.x(), h - 2)
        fill.lineTo(first.x(), h - 2)
        fill.closeSubpath()
        fill_c = QColor(self._color)
        fill_c.setAlpha(35)
        p.fillPath(fill, QBrush(fill_c))
        line_pen = QPen(self._color)
        line_pen.setWidthF(1.5)
        p.setPen(line_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._color))
        p.drawEllipse(last, 2.5, 2.5)
        p.end()


class ForecastRow(QWidget):
    """Label + burn rate + sparkline + overflow ETA for one rate limit."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel(label)
        self.lbl.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        top.addWidget(self.lbl, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        self.rate = QLabel("")
        self.rate.setStyleSheet(f"color: {FG2}; font-size: 10px;")
        top.addWidget(self.rate, 0, Qt.AlignmentFlag.AlignBottom)
        box.addLayout(top)

        self.spark = SparklineWidget()
        box.addWidget(self.spark)

        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color: {FG3}; font-size: 10px;")
        box.addWidget(self.sub)

    def _set_sub(self, text, c):
        self.sub.setText(text)
        self.sub.setStyleSheet(f"color: {c}; font-size: 10px;")

    def set_data(self, points, fc, pct, seconds_until_reset, stale):
        c = FG3 if (stale or pct is None) else color(pct)
        self.spark.set_series(points, c)
        rate = (fc or {}).get("rate_pph")
        if rate is None:
            self.rate.setText("")
            self._set_sub("collecting data…", FG3)
            return
        self.rate.setText(f"{rate:+.1f} pp/h")
        eta = fc.get("eta_seconds")
        if eta is None:
            self._set_sub("steady pace · no overflow risk", FG3)
        elif fc.get("alert"):  # relevant overflow (bucket already high): alarm
            self._set_sub(
                f"at current pace overflows in {fmt_time(eta)} · before reset"
                f" ({fmt_time(seconds_until_reset)})", RED)
        elif fc.get("overflow_before_reset"):
            # overflows before the reset only on paper, but usage is still low: the
            # short-term burn rate rarely holds up for that long — no alarm
            self._set_sub(
                f"at recent pace would overflow in {fmt_time(eta)} · usage still low",
                FG2)
        elif fc.get("overflow_before_reset") is False:
            self._set_sub(
                f"overflows in {fmt_time(eta)} · reset arrives first"
                f" ({fmt_time(seconds_until_reset)})", GREEN)
        else:
            self._set_sub(f"at current pace overflows in {fmt_time(eta)}", FG2)


class BarRow(QWidget):
    """Name + proportional bar + value — one row of the per-project breakdown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.name = QLabel()
        self.name.setStyleSheet(f"color: {FG}; font-size: 11px;")
        self.name.setFixedWidth(118)
        self.bar = UsageBar()
        self.val = QLabel()
        self.val.setStyleSheet(f"color: {FG2}; font-size: 10px;")
        self.val.setFixedWidth(46)
        self.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box.addWidget(self.name)
        box.addWidget(self.bar, 1)
        box.addWidget(self.val)

    def set_data(self, name, frac_pct, text, tooltip=""):
        self.name.setText(name)
        self.bar.set_value(frac_pct, ACCENT)
        self.val.setText(text)
        if tooltip:
            self.setToolTip(tooltip)


class HeatmapWidget(QWidget):
    """GitHub-style calendar: one cell per day, shade by usage intensity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(15)
        self._cells = []  # [(day, frac 0..1), ...] chronological

    def set_data(self, pairs):
        mx = max((v for _, v in pairs), default=1) or 1
        self._cells = [(d, (v / mx)) for d, v in pairs]
        self.setToolTip("rightmost = most recent · shade = usage")
        self.update()

    def paintEvent(self, event):
        if not self._cells:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        n = len(self._cells)
        gap = 3.0
        sz = min(13.0, (self.width() - (n - 1) * gap) / n)
        base, acc = QColor(BG3), QColor(ACCENT)
        for i, (_, frac) in enumerate(self._cells):
            f = frac ** 0.6 if frac > 0 else 0  # emphasizes low-usage days
            col = QColor(
                int(base.red() + (acc.red() - base.red()) * f),
                int(base.green() + (acc.green() - base.green()) * f),
                int(base.blue() + (acc.blue() - base.blue()) * f))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(i * (sz + gap), 1, sz, sz), 2.5, 2.5)
        p.end()


class AvatarWidget(QWidget):
    """Gradient circle with the account's initial — modern-app look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 42)
        self._letter = "?"

    def set_letter(self, s):
        self._letter = ((s or "?").strip()[:1] or "?").upper()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 42, 42)
        g.setColorAt(0.0, QColor(ACCENT))
        g.setColorAt(1.0, QColor(ACCENT2))
        p.setBrush(QBrush(g))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 40, 40)
        p.setPen(QPen(QColor("white")))
        p.setFont(QFont(UI_FONT, 16, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._letter)
        p.end()


class DashboardWidget(QWidget):
    def __init__(self, cfg: dict, dongle=None):
        super().__init__()
        self.cfg = cfg
        self.dongle = dongle
        self._scoped_rings = {}
        self._last_u = None

        self.setObjectName("dashRoot")
        self.setWindowTitle("Claude Monitor")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedWidth(440)
        self.setStyleSheet(_qss())

        self._build_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_MS)
        self._tick_timer = QTimer(self)  # live countdown
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(TICK_MS)
        self.adjustSize()

    # ---- construction -----------------------------------------------------

    def _section(self, text):
        l = QLabel(text.upper())
        f = QFont(UI_FONT, 8, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        l.setFont(f)
        l.setStyleSheet(f"color: {FG2};")
        return l

    def _sep(self):
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {SEP};")
        return f

    def _card(self, cm=(18, 16, 18, 16)):
        # No QGraphicsDropShadowEffect: it breaks sizeHint propagation
        # (the card doesn't regrow when a disclosure opens) and is fragile on
        # XCB. Depth comes from surface↑ contrast over the dark bg + border.
        f = QFrame()
        f.setProperty("card", "true")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(*cm)
        lay.setSpacing(0)
        return f, lay

    def _card_title(self, text):
        l = QLabel(text.upper())
        fo = QFont(UI_FONT, 8, QFont.Weight.Bold)
        fo.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        l.setFont(fo)
        l.setStyleSheet(f"color: {FG2};")
        return l

    def _disclosure_btn(self, text, cb):
        b = QPushButton(text)
        b.setProperty("kind", "disclosure")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(cb)
        return b

    def _fc_header_text(self):
        return ("▾  " if self._fc_open else "▸  ") + "FORECAST"

    def _fit(self):
        # The card→window cascade must be triggered by hand: with the disclosure
        # inside a QFrame, hiding/showing the container doesn't recompute the
        # card's sizeHint on its own (without relying on the event loop).
        for c in (self.fc_container, self.pj_container):
            pl = c.parentWidget().layout()
            if pl is not None:
                pl.invalidate()
                pl.activate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()

    def _fade_widget(self, w):
        # section fade-in. The effect is applied AFTER _fit (which already
        # resolved the sizeHint with the container visible) and removed when
        # done — a graphics effect alive during resize breaks the cascade on XCB.
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: w.setGraphicsEffect(None))
        anim.start()
        self._disc_anim = anim  # keeps the reference alive until it finishes

    def _toggle_forecast(self):
        self._fc_open = not self._fc_open
        self.fc_container.setVisible(self._fc_open)
        self.fc_header.setText(self._fc_header_text())
        self.cfg["forecast_expanded"] = self._fc_open
        config.save(self.cfg)
        self._fit()  # window shrinks/expands with the content
        if self._fc_open and _ANIMATE:
            self._fade_widget(self.fc_container)

    def _mini_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color: {FG2}; font-size: 10px; font-weight: 600;")
        return l

    def _pj_header_text(self):
        return ("▾  " if self._pj_open else "▸  ") + "BY PROJECT"

    def _toggle_projects(self):
        self._pj_open = not self._pj_open
        self.pj_container.setVisible(self._pj_open)
        self.pj_header.setText(self._pj_header_text())
        self.cfg["projects_expanded"] = self._pj_open
        config.save(self.cfg)
        if self._pj_open:
            self._kick_projects()
            self._render_projects()
        self._fit()
        if self._pj_open and _ANIMATE:
            self._fade_widget(self.pj_container)

    def _kick_projects(self):
        # the initial parse can take ~8s: always in a thread (the lock in
        # projects.refresh serializes; later incrementals are ~5ms).
        threading.Thread(target=projects.refresh, daemon=True).start()

    def _render_projects(self):
        s = projects.summary(days=7)
        projs, models = s["projects"], s["models"]
        self.pj_empty.setVisible(not projs)
        self.pj_heatmap.set_data(projects.daily(14))
        maxp = max((p["output"] for p in projs), default=1) or 1
        for i, row in enumerate(self.pj_proj_rows):
            if i < len(projs):
                p = projs[i]
                row.setVisible(True)
                row.set_data(p["name"], 100 * p["output"] / maxp,
                             _fmt_tokens(p["output"]),
                             f"{p['output']:,} output tokens · {p['total']:,} total")
            else:
                row.setVisible(False)
        maxm = max((m["output"] for m in models), default=1) or 1
        for i, row in enumerate(self.pj_model_rows):
            if i < len(models):
                m = models[i]
                row.setVisible(True)
                row.set_data(m["name"].replace("claude-", ""),
                             100 * m["output"] / maxm, _fmt_tokens(m["output"]),
                             f"{m['output']:,} output tokens")
            else:
                row.setVisible(False)

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(13)

        # ---- Account (header) ----
        hcard, hbox = self._card(cm=(16, 14, 16, 14))
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(13)
        self.avatar = AvatarWidget()
        head.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        info_w = QWidget()
        info = QVBoxLayout(info_w)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        self.acc_name = QLabel("—")
        self.acc_name.setStyleSheet("font-size: 15px; font-weight: 700;")
        info.addWidget(self.acc_name)
        self.acc_email = QLabel("")
        self.acc_email.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        info.addWidget(self.acc_email)
        head.addWidget(info_w, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch()
        self.acc_plan = QLabel("")
        self.acc_plan.setProperty("pill", "true")
        head.addWidget(self.acc_plan, 0, Qt.AlignmentFlag.AlignVCenter)
        hbox.addLayout(head)
        main.addWidget(hcard)

        # ---- Usage (highlight) — ring gauges ----
        ucard, ubox = self._card()
        ubox.addWidget(self._card_title("Usage"))
        ubox.addSpacing(16)
        self.rings_box = QHBoxLayout()
        self.rings_box.setContentsMargins(0, 0, 0, 0)
        self.rings_box.setSpacing(6)
        self.ring_5h = UsageRing("5h session")
        self.ring_7d = UsageRing("Week")
        self.rings_box.addWidget(self.ring_5h)
        self.rings_box.addWidget(self.ring_7d)
        ubox.addLayout(self.rings_box)
        ubox.addSpacing(14)
        self.meta = QLabel("")
        self.meta.setStyleSheet(f"color: {FG3}; font-size: 11px;")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ubox.addWidget(self.meta)
        main.addWidget(ucard)

        # ---- Forecast (disclosure) ----
        self._fc_open = bool(self.cfg.get("forecast_expanded", False))
        fccard, fcbox = self._card(cm=(18, 14, 18, 14))
        self.fc_header = self._disclosure_btn(self._fc_header_text(), self._toggle_forecast)
        fcbox.addWidget(self.fc_header)
        self.fc_container = QWidget()
        self.fc_box = QVBoxLayout(self.fc_container)
        self.fc_box.setContentsMargins(0, 15, 0, 2)
        self.fc_box.setSpacing(14)
        self.fc_5h = ForecastRow("Session (5h)")
        self.fc_7d = ForecastRow("Week")
        self.fc_box.addWidget(self.fc_5h)
        self.fc_box.addWidget(self.fc_7d)
        fcbox.addWidget(self.fc_container)
        self.fc_container.setVisible(self._fc_open)
        self._fc_scoped = {}
        main.addWidget(fccard)

        # ---- By project (disclosure) ----
        self._pj_open = bool(self.cfg.get("projects_expanded", False))
        pjcard, pjcardbox = self._card(cm=(18, 14, 18, 14))
        self.pj_header = self._disclosure_btn(self._pj_header_text(), self._toggle_projects)
        pjcardbox.addWidget(self.pj_header)
        self.pj_container = QWidget()
        pj_box = QVBoxLayout(self.pj_container)
        pj_box.setContentsMargins(0, 14, 0, 2)
        pj_box.setSpacing(7)
        cap = QLabel("Output tokens · last 7 days · local count")
        cap.setStyleSheet(f"color: {FG3}; font-size: 10px;")
        pj_box.addWidget(cap)
        pj_box.addSpacing(4)
        pj_box.addWidget(self._mini_label("Projects"))
        self.pj_proj_rows = [BarRow() for _ in range(8)]
        for r in self.pj_proj_rows:
            pj_box.addWidget(r)
        pj_box.addSpacing(10)
        pj_box.addWidget(self._mini_label("Models"))
        self.pj_model_rows = [BarRow() for _ in range(5)]
        for r in self.pj_model_rows:
            pj_box.addWidget(r)
        pj_box.addSpacing(11)
        pj_box.addWidget(self._mini_label("Last 14 days"))
        self.pj_heatmap = HeatmapWidget()
        pj_box.addWidget(self.pj_heatmap)
        self.pj_empty = QLabel("collecting local data…")
        self.pj_empty.setStyleSheet(f"color: {FG3}; font-size: 11px;")
        pj_box.addWidget(self.pj_empty)
        pjcardbox.addWidget(self.pj_container)
        self.pj_container.setVisible(self._pj_open)
        main.addWidget(pjcard)
        if self._pj_open:
            self._kick_projects()
            self._render_projects()

        # ---- Settings (dongle + visibility + notifications) ----
        scard, sbox = self._card(cm=(18, 16, 18, 18))

        sbox.addWidget(self._card_title("Dongle"))
        sbox.addSpacing(13)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        op_lbl = QLabel("Opacity")
        op_lbl.setStyleSheet("font-size: 12px;")
        row.addWidget(op_lbl)
        row.addSpacing(12)
        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(30, 100)
        self.op_slider.setValue(int(self.cfg.get("dongle_opacity", 0.85) * 100))
        self.op_slider.valueChanged.connect(self._on_opacity)
        row.addWidget(self.op_slider, 1)
        self.op_label = QLabel(f"{self.op_slider.value()}%")
        self.op_label.setStyleSheet(f"color: {FG2}; font-size: 11px; font-weight: 600;")
        self.op_label.setFixedWidth(40)
        self.op_label.setAlignment(Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.op_label)
        sbox.addLayout(row)

        sbox.addSpacing(20)
        sbox.addWidget(self._card_title("Visibility"))
        sbox.addSpacing(6)
        self.show_group = QButtonGroup(self)
        current = self.cfg.get("show_mode", "always")
        for i, (text, val) in enumerate(SHOW_MODES):
            rb = QRadioButton(text)
            rb.setChecked(current == val)
            self.show_group.addButton(rb, i)
            sbox.addWidget(rb)
        self.show_group.idToggled.connect(self._on_mode)

        sbox.addSpacing(20)
        sbox.addWidget(self._card_title("Notifications"))
        sbox.addSpacing(11)
        self.thr_row = QHBoxLayout()
        self.thr_row.setContentsMargins(0, 0, 0, 0)
        self.thr_row.setSpacing(8)
        sbox.addLayout(self.thr_row)
        self._render_thresholds()
        sbox.addSpacing(6)
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+ Add")
        add_btn.setProperty("kind", "ghost")
        add_btn.clicked.connect(self._add_thr)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        sbox.addLayout(add_row)
        main.addWidget(scard)

        # ---- Actions ----
        main.addSpacing(2)
        btns = QHBoxLayout()
        btns.setContentsMargins(4, 0, 4, 0)
        quit_btn = QPushButton("Quit monitor")
        quit_btn.setProperty("kind", "danger")
        quit_btn.clicked.connect(QApplication.quit)
        btns.addWidget(quit_btn)
        btns.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setProperty("kind", "primary")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        main.addLayout(btns)

    # ---- usage refresh ----------------------------------------------------

    def _refresh(self):
        try:
            u = monitor.calc_usage(self.cfg)
        except Exception:
            import traceback; traceback.print_exc()
            return
        self._last_u = u
        plan = (u.get("plan") or "").replace("claude_", "").upper()
        if u.get("identity_stale"):
            # stale oauthAccount (account switched and Claude Code hasn't
            # rewritten the name yet): don't show the old name as current
            self.acc_name.setText("Account switched")
            self.avatar.set_letter("?")
            self.acc_email.setText("reopen Claude Code to sync the name")
        else:
            acc = u.get("account") or "—"
            self.acc_name.setText(acc)
            self.avatar.set_letter(acc)
            self.acc_email.setText(u.get("email") or "")
        self.acc_plan.setText(plan)
        self._render_usage_rows(u)
        self._render_forecast(u)
        self.meta.setText(self._meta_text(u))
        if self._pj_open:
            self._kick_projects()  # cheap incremental; lock prevents concurrency
            self._render_projects()

    def _tick(self):
        # live countdown (1s): recomputes only the times/pace of the usage rows,
        # without redoing calc_usage/forecast/projects (those stay on the 5s cycle).
        if self._last_u is not None:
            self._render_usage_rows(self._last_u)

    def _render_usage_rows(self, u):
        now = time.time()
        stale = u.get("stale", False)

        def until(epoch, fallback=None):
            return max(0, int(epoch - now)) if epoch else fallback

        pct_5h = u.get("pct_5h")
        self.ring_5h.setVisible(pct_5h is not None)
        self.ring_5h.set_data(
            pct_5h, until(u.get("reset_5h_epoch"), u.get("seconds_until_reset_5h")),
            stale, WINDOW_5H)

        breakdown = u.get("weekly_breakdown") or []
        general = next((w for w in breakdown if w.get("kind") == "weekly_all"), None)
        if general:
            self.ring_7d.set_data(
                general.get("pct"),
                until(general.get("reset"), u.get("seconds_until_reset")),
                stale, WINDOW_7D)
        else:
            self.ring_7d.set_data(
                u.get("pct_7d", u.get("pct")),
                until(u.get("reset_7d_epoch"), u.get("seconds_until_reset")),
                stale, WINDOW_7D)

        seen = set()
        for w in breakdown:
            if w.get("kind") != "weekly_scoped":
                continue
            model = w.get("model") or "per model"
            seen.add(model)
            ring = self._scoped_rings.get(model)
            if ring is None:
                ring = UsageRing(model)
                self._scoped_rings[model] = ring
                self.rings_box.addWidget(ring)
            ring.set_data(w.get("pct"), until(w.get("reset")), stale, WINDOW_7D)
        for model in list(self._scoped_rings):
            if model not in seen:
                self._scoped_rings.pop(model).deleteLater()

    def _render_forecast(self, u):
        now = time.time()
        stale = u.get("stale", False)

        def until(epoch, fallback=None):
            return max(0, int(epoch - now)) if epoch else fallback

        fc = u.get("forecast") or {}
        account = u.get("account") or ""
        pct_5h = u.get("pct_5h")
        breakdown = u.get("weekly_breakdown") or []
        general = next((w for w in breakdown if w.get("kind") == "weekly_all"), None)

        self.fc_5h.setVisible(pct_5h is not None)
        if pct_5h is not None:
            pts = history.series("5h", u.get("reset_5h_epoch") or 0, account)
            self.fc_5h.set_data(pts, fc.get("5h"), pct_5h,
                                u.get("seconds_until_reset_5h"), stale)

        if general:
            pct_7d = general.get("pct")
            epoch_7d = general.get("reset") or 0
            reset_7d = until(general.get("reset"), u.get("seconds_until_reset"))
        else:
            pct_7d = u.get("pct_7d", u.get("pct"))
            epoch_7d = u.get("reset_7d_epoch") or 0
            reset_7d = u.get("seconds_until_reset")
        self.fc_7d.setVisible(pct_7d is not None)
        if pct_7d is not None:
            pts = history.series("7d", epoch_7d, account)
            self.fc_7d.set_data(pts, fc.get("7d"), pct_7d, reset_7d, stale)

        seen_fc = set()
        for w in breakdown:
            if w.get("kind") != "weekly_scoped":
                continue
            model = w.get("model") or "per model"
            seen_fc.add(model)
            row = self._fc_scoped.get(model)
            if row is None:
                row = ForecastRow(f"Week · {model}")
                self._fc_scoped[model] = row
                self.fc_box.addWidget(row)
            metric = f"7d:{w.get('model') or 'scoped'}"
            pts = history.series(metric, w.get("reset") or 0, account)
            row.set_data(pts, fc.get(metric), w.get("pct"),
                         until(w.get("reset")), stale)
        for model in list(self._fc_scoped):
            if model not in seen_fc:
                self._fc_scoped.pop(model).deleteLater()

    def _meta_text(self, u):
        parts = [SOURCE_LABELS.get(u.get("source"), u.get("source") or "?")]
        if u.get("stale"):
            age = u.get("stale_age_seconds")
            parts.append(f"stale data · {fmt_time(age)} ago" if age is not None
                         else "stale data")
        act = u.get("active_sessions") or 0
        if act:
            parts.append("1 active session" if act == 1 else f"{act} active sessions")
        if u.get("overage_status") == "enabled":
            parts.append("extra usage on")
        return "  ·  ".join(parts)

    # ---- settings ---------------------------------------------------------

    def _on_opacity(self, v):
        self.op_label.setText(f"{v}%")
        self.cfg["dongle_opacity"] = v / 100
        if self.dongle is not None:
            try:
                self.dongle.setWindowOpacity(v / 100)
            except RuntimeError:
                pass
        config.save(self.cfg)

    def _on_mode(self, idx, checked):
        if checked and 0 <= idx < len(SHOW_MODES):
            self.cfg["show_mode"] = SHOW_MODES[idx][1]
            config.save(self.cfg)

    def _render_thresholds(self):
        while self.thr_row.count():
            it = self.thr_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        for i, t in enumerate(self.cfg.get("thresholds", [])):
            chip = QFrame()
            chip.setProperty("chip", "true")
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(11, 3, 7, 3)
            lay.setSpacing(2)
            e = QLineEdit(str(t))
            e.setProperty("bare", "true")
            e.setFixedWidth(24)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.textChanged.connect(lambda txt, idx=i: self._upd_thr(idx, txt))
            lay.addWidget(e)
            pc = QLabel("%")
            pc.setStyleSheet(f"color: {FG3}; font-size: 11px; font-weight: 600;")
            lay.addWidget(pc)
            lay.addSpacing(4)
            rm = QPushButton("✕")
            rm.setProperty("kind", "chipx")
            rm.setFixedSize(16, 16)
            rm.setCursor(Qt.CursorShape.PointingHandCursor)
            rm.clicked.connect(lambda checked=False, idx=i: self._del_thr(idx))
            lay.addWidget(rm)
            self.thr_row.addWidget(chip)
        self.thr_row.addStretch()

    def _add_thr(self):
        self.cfg.setdefault("thresholds", []).append(50)
        self._render_thresholds()
        config.save(self.cfg)

    def _del_thr(self, i):
        if len(self.cfg.get("thresholds", [])) > 1:
            self.cfg["thresholds"].pop(i)
            self._render_thresholds()
            config.save(self.cfg)

    def _upd_thr(self, i, txt):
        try:
            self.cfg["thresholds"][i] = int(txt)
            config.save(self.cfg)
        except (ValueError, IndexError):
            pass
