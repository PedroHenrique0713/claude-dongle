import os, sys, time, threading, math
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from . import monitor, config, history, projects, notifier, i18n
from .i18n import t as _t
from .utils import (color, fmt_time, availability_text, RED, ORANGE, GREEN, BG, BG2, BG3, FG, FG2, FG3, SEP,
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
                             QGraphicsOpacityEffect, QScrollArea)
from PyQt6.QtCore import (Qt, QTimer, QRectF, QPointF, pyqtProperty,
                          QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (QPainter, QColor, QBrush, QFont, QFontMetrics, QPen,
                         QPainterPath, QLinearGradient, QIntValidator)

REFRESH_MS = 5000
TICK_MS = 1000          # live countdown (only recomputes time texts)
WINDOW_5H = 5 * 3600    # window durations, for the pace bar
WINDOW_7D = 7 * 86400
# Built per render: the language can change while the panel is open.
def _source_label(src):
    return {"api": _t("src.api"), "none": _t("src.none")}.get(src, src or "?")
# Same file the dongle and the systemd timer write notification state to.
SENT_PATH = config.CONFIG_DIR / "sent_thresholds.json"
# animations only in real use; offscreen (screenshots/headless) paints the final state
_ANIMATE = os.environ.get("QT_QPA_PLATFORM") != "offscreen"
SHOW_MODES = [("vis.always", "always"), ("vis.claude", "claude"),
              ("vis.dev", "dev"), ("vis.custom", "custom")]


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

    QPushButton[kind="seg"] {{
        background: {BG3}; color: {FG2}; border: 1px solid transparent;
        border-radius: 9px; padding: 5px 11px; font-size: 11px; font-weight: 600;
    }}
    QPushButton[kind="seg"]:hover {{ background: {SURFACE_HI}; color: {FG}; }}
    QPushButton[kind="seg"]:checked {{
        background: {_rgba(ACCENT, 46)}; color: #cddaff; border-color: {_rgba(ACCENT, 120)};
    }}

    QScrollArea, #dashBody {{ background: {BG}; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 9px; margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BG3}; border-radius: 4px; min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #3d3d47; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

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
        if pct >= 100 and not stale:
            # a spent window has no "pace" left to comment on; what matters is
            # when it comes back
            self._sub = (_t("avail.ring_spent", time=fmt_time(seconds))
                         if seconds is not None else _t("avail.ring_spent", time="--"))
            self._animate_to(prev, pct)
            return
        sub = fmt_time(seconds) if seconds is not None else ""
        if pace is not None and not stale:  # usage vs. elapsed time
            expected = pace * 100
            if pct > expected + 8:
                sub += "  ·  " + _t("pace.high")
            elif pct < expected - 8:
                sub += "  ·  " + _t("pace.low")
            else:
                sub += "  ·  " + _t("pace.on")
        self._sub = sub
        self._animate_to(prev, pct)

    def _animate_to(self, prev, pct):
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
            self._set_sub(_t("fc.collecting"), FG3)
            return
        self.rate.setText(_t("fc.rate", rate=rate))
        eta = fc.get("eta_seconds")
        # Said as a budget ("how much work still fits") rather than as a
        # threat ("it overflows in X"): same number, and it answers the
        # question you actually have before starting one more task.
        if eta is None:
            self._set_sub(_t("fc.steady"), FG3)
        elif fc.get("alert"):  # relevant overflow (bucket already high): alarm
            self._set_sub(
                _t("fc.budget_before", eta=fmt_time(eta),
                   reset=fmt_time(seconds_until_reset)), RED)
        elif fc.get("overflow_before_reset"):
            # overflows before the reset only on paper, but usage is still low: the
            # short-term burn rate rarely holds up for that long — no alarm
            self._set_sub(_t("fc.overflow_low", eta=fmt_time(eta)), FG2)
        elif fc.get("overflow_before_reset") is False:
            self._set_sub(
                _t("fc.budget_reset_first", reset=fmt_time(seconds_until_reset)),
                GREEN)
        else:
            self._set_sub(_t("fc.budget_plain", eta=fmt_time(eta)), FG2)


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
        self.setToolTip(_t("pj.heatmap_tip"))
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


class HourProfileWidget(QWidget):
    """24 columns: how much of a window you burn in each hour of the day.

    Reads like a clock, not a chart — the point is recognising your own shape
    (the 17h peak, the quiet morning), so the current hour is marked and the
    labels are only 0/6/12/18.
    """

    H = 62
    LABEL_H = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H + self.LABEL_H)
        self.setMinimumWidth(200)
        self._hours = [0.0] * 24
        self._peak = None

    def set_data(self, hours, peak):
        self._hours = list(hours) + [0.0] * (24 - len(hours))
        self._peak = peak
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w = self.width()
        gap = 3
        bw = max(2.0, (w - gap * 23) / 24)
        top = self.H
        peak_v = max(self._hours) or 1.0
        now_h = time.localtime().tm_hour
        for i, v in enumerate(self._hours):
            x = i * (bw + gap)
            h = max(2.0, top * (v / peak_v)) if v > 0 else 2.0
            if v <= 0:
                col = QColor(BG3)
            else:
                col = QColor(ACCENT)
                col.setAlpha(int(90 + 165 * (v / peak_v)))
            if i == now_h:
                col = QColor(GREEN if v > 0 else FG3)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, top - h, bw, h), 2, 2)
        f = QFont(UI_FONT, 7)
        p.setFont(f)
        p.setPen(QPen(QColor(FG3)))
        for i in (0, 6, 12, 18):
            x = i * (bw + gap)
            p.drawText(QRectF(x, top + 2, bw * 3, self.LABEL_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{i}h")
        p.end()


class ToggleSwitch(QWidget):
    """On/off switch. The settings panel only had radio buttons and bare text
    fields, so every boolean option (alert me on X) had nowhere to live and
    simply wasn't exposed — the notification switches were config-file only."""

    W, H = 40, 22
    PAD = 3

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = bool(checked)
        self._k = 1.0 if self._checked else 0.0
        self._cb = None
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_knob(self):
        return self._k

    def _set_knob(self, v):
        self._k = float(v)
        self.update()

    knob = pyqtProperty(float, _get_knob, _set_knob)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        v = bool(v)
        if v == self._checked:
            return
        self._checked = v
        if _ANIMATE:
            self._anim.stop()
            self._anim.setStartValue(self._k)
            self._anim.setEndValue(1.0 if v else 0.0)
            self._anim.start()
        else:
            self._set_knob(1.0 if v else 0.0)

    def onToggled(self, cb):
        self._cb = cb
        return self

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            if self._cb:
                self._cb(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        off, on = QColor(BG3), QColor(ACCENT)
        k = self._k
        track = QColor(int(off.red() + (on.red() - off.red()) * k),
                       int(off.green() + (on.green() - off.green()) * k),
                       int(off.blue() + (on.blue() - off.blue()) * k))
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2, self.H / 2)
        d = self.H - 2 * self.PAD
        x = self.PAD + k * (self.W - d - 2 * self.PAD)
        p.setBrush(QColor("#ffffff" if k > 0.5 else "#9a9aa4"))
        p.drawEllipse(QRectF(x, self.PAD, d, d))
        p.end()


class DashboardWidget(QWidget):
    def __init__(self, cfg: dict, dongle=None):
        super().__init__()
        self.cfg = cfg
        self.dongle = dongle
        self._scoped_rings = {}
        self._last_u = None

        self.setObjectName("dashRoot")
        self.setWindowTitle(_t("app.title"))
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
        self._fit_to_screen()

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
        return ("▾  " if self._fc_open else "▸  ") + _t("sec.forecast")

    def _fit(self):
        # The card→window cascade must be triggered by hand: with the disclosure
        # inside a QFrame, hiding/showing the container doesn't recompute the
        # card's sizeHint on its own (without relying on the event loop).
        for c in (self.fc_container, self.pj_container, self.hr_container,
                  self.set_container):
            pl = c.parentWidget().layout()
            if pl is not None:
                pl.invalidate()
                pl.activate()
        self.layout().invalidate()
        self.layout().activate()
        self._fit_to_screen()

    def _fit_to_screen(self):
        """Height follows the content, capped at the screen it is on.

        setFixedWidth keeps the layout honest, but the height was free: on a
        1366x768 laptop the settings card ended below the bottom edge and there
        was no way to scroll to it. Past the cap the scroll area takes over.
        """
        body = self.scroll.widget()
        if body is None:
            return
        wanted = body.sizeHint().height()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            cap = int(screen.availableGeometry().height() * 0.92)
            wanted = min(wanted, cap)
            self.setMaximumHeight(cap)
        self.resize(self.width(), max(wanted, 240))

    def showEvent(self, event):
        # The screen is only known once mapped: a panel opened on the external
        # monitor may cap differently from the laptop one.
        super().showEvent(event)
        self._fit_to_screen()

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

    def _hr_header_text(self):
        return ("▾  " if self._hr_open else "▸  ") + _t("sec.hours")

    def _toggle_hours(self):
        self._hr_open = not self._hr_open
        self.hr_container.setVisible(self._hr_open)
        self.hr_header.setText(self._hr_header_text())
        self.cfg["hours_expanded"] = self._hr_open
        config.save(self.cfg)
        if self._hr_open:
            self._render_hours()
        self._fit()
        if self._hr_open and _ANIMATE:
            self._fade_widget(self.hr_container)

    def _render_hours(self):
        u = self._last_u or {}
        try:
            prof = history.hourly_profile(
                days=int(self.cfg.get("hours_days", 14)),
                account=u.get("account") or "")
        except Exception:
            return
        self.hr_profile.set_data(prof["hours"], prof["peak"])
        if not prof["days"] or prof["peak"] is None:
            self.hr_hint.setText(_t("hours.empty"))
            self.hr_peak.setText("")
            return
        self.hr_hint.setText(_t("hours.hint", days=prof["days"]))
        self.hr_peak.setText(_t("hours.peak", hour=prof["peak"]))

    def _set_header_text(self):
        return ("▾  " if self._set_open else "▸  ") + _t("sec.settings")

    def _toggle_settings(self):
        self._set_open = not self._set_open
        self.set_container.setVisible(self._set_open)
        self.set_header.setText(self._set_header_text())
        self.cfg["settings_expanded"] = self._set_open
        config.save(self.cfg)
        self._fit()
        if self._set_open and _ANIMATE:
            self._fade_widget(self.set_container)

    def _mini_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color: {FG2}; font-size: 10px; font-weight: 600;")
        return l

    def _pj_header_text(self):
        return ("▾  " if self._pj_open else "▸  ") + _t("sec.projects")

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
        # Everything lives inside a scroll area: with Forecast and By project
        # open the content is taller than a 768px screen, and the panel used to
        # simply run off the bottom with no way to reach the buttons.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidget(self._build_body())
        outer.addWidget(self.scroll)

    def _build_body(self):
        body = QWidget()
        body.setObjectName("dashBody")
        main = QVBoxLayout(body)
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
        ubox.addWidget(self._card_title(_t("card.usage")))
        ubox.addSpacing(16)
        self.rings_box = QHBoxLayout()
        self.rings_box.setContentsMargins(0, 0, 0, 0)
        self.rings_box.setSpacing(6)
        self.ring_5h = UsageRing(_t("usage.session"))
        self.ring_7d = UsageRing(_t("usage.week"))
        self.rings_box.addWidget(self.ring_5h)
        self.rings_box.addWidget(self.ring_7d)
        ubox.addLayout(self.rings_box)
        ubox.addSpacing(14)
        self.avail = QLabel("")
        self.avail.setStyleSheet(f"color: {ORANGE}; font-size: 11px; font-weight: 600;")
        self.avail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.avail.setWordWrap(True)
        self.avail.setVisible(False)
        ubox.addWidget(self.avail)
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
        self.fc_5h = ForecastRow(_t("fc.session"))
        self.fc_7d = ForecastRow(_t("fc.week"))
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
        cap = QLabel(_t("pj.hint"))
        cap.setStyleSheet(f"color: {FG3}; font-size: 10px;")
        pj_box.addWidget(cap)
        pj_box.addSpacing(4)
        pj_box.addWidget(self._mini_label(_t("pj.projects")))
        self.pj_proj_rows = [BarRow() for _ in range(8)]
        for r in self.pj_proj_rows:
            pj_box.addWidget(r)
        pj_box.addSpacing(10)
        pj_box.addWidget(self._mini_label(_t("pj.models")))
        self.pj_model_rows = [BarRow() for _ in range(5)]
        for r in self.pj_model_rows:
            pj_box.addWidget(r)
        pj_box.addSpacing(11)
        pj_box.addWidget(self._mini_label(_t("pj.last14")))
        self.pj_heatmap = HeatmapWidget()
        pj_box.addWidget(self.pj_heatmap)
        self.pj_empty = QLabel(_t("pj.collecting"))
        self.pj_empty.setStyleSheet(f"color: {FG3}; font-size: 11px;")
        pj_box.addWidget(self.pj_empty)
        pjcardbox.addWidget(self.pj_container)
        self.pj_container.setVisible(self._pj_open)
        main.addWidget(pjcard)
        if self._pj_open:
            self._kick_projects()
            self._render_projects()

        # ---- By hour (disclosure) ----
        self._hr_open = bool(self.cfg.get("hours_expanded", False))
        hrcard, hrbox = self._card(cm=(18, 14, 18, 14))
        self.hr_header = self._disclosure_btn(self._hr_header_text(),
                                              self._toggle_hours)
        hrbox.addWidget(self.hr_header)
        self.hr_container = QWidget()
        hr_box = QVBoxLayout(self.hr_container)
        hr_box.setContentsMargins(0, 14, 0, 2)
        hr_box.setSpacing(8)
        self.hr_hint = self._hint("")
        hr_box.addWidget(self.hr_hint)
        self.hr_profile = HourProfileWidget()
        hr_box.addWidget(self.hr_profile)
        self.hr_peak = QLabel("")
        self.hr_peak.setStyleSheet(f"color: {FG2}; font-size: 11px; font-weight: 600;")
        hr_box.addWidget(self.hr_peak)
        hrbox.addWidget(self.hr_container)
        self.hr_container.setVisible(self._hr_open)
        main.addWidget(hrcard)
        if self._hr_open:
            self._render_hours()

        # ---- Settings (disclosure: dongle + visibility + notifications) ----
        # Collapsed by default: settings are read rarely and, expanded, they
        # alone are taller than the usage the panel exists to show.
        self._set_open = bool(self.cfg.get("settings_expanded", False))
        scard, scardbox = self._card(cm=(18, 14, 18, 16))
        self.set_header = self._disclosure_btn(self._set_header_text(),
                                               self._toggle_settings)
        scardbox.addWidget(self.set_header)
        self.set_container = QWidget()
        sbox = QVBoxLayout(self.set_container)
        sbox.setContentsMargins(0, 15, 0, 2)
        sbox.setSpacing(0)
        scardbox.addWidget(self.set_container)
        self.set_container.setVisible(self._set_open)

        sbox.addWidget(self._card_title(_t("card.language")))
        sbox.addSpacing(9)
        lang_row = QHBoxLayout()
        lang_row.setContentsMargins(0, 0, 0, 0)
        lang_row.setSpacing(6)
        self.lang_group = QButtonGroup(self)
        self.lang_group.setExclusive(True)
        current_lang = i18n.language()
        for label, code in i18n.LANGUAGES:
            b = QPushButton(label)
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(code == current_lang)
            b.clicked.connect(lambda _c=False, code=code: self._on_language(code))
            self.lang_group.addButton(b)
            lang_row.addWidget(b)
        lang_row.addStretch()
        sbox.addLayout(lang_row)

        sbox.addSpacing(20)
        sbox.addWidget(self._card_title(_t("card.dongle")))
        sbox.addSpacing(13)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        op_lbl = QLabel(_t("set.opacity"))
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
        sbox.addWidget(self._card_title(_t("card.visibility")))
        sbox.addSpacing(6)
        self.show_group = QButtonGroup(self)
        current = self.cfg.get("show_mode", "always")
        for i, (text, val) in enumerate(SHOW_MODES):
            rb = QRadioButton(_t(text))
            rb.setChecked(current == val)
            self.show_group.addButton(rb, i)
            sbox.addWidget(rb)
        self.show_group.idToggled.connect(self._on_mode)

        sbox.addSpacing(20)
        sbox.addWidget(self._card_title(_t("card.notifications")))
        self._build_notifications(sbox)
        main.addWidget(scard)

        # ---- Actions ----
        main.addSpacing(2)
        btns = QHBoxLayout()
        btns.setContentsMargins(4, 0, 4, 0)
        quit_btn = QPushButton(_t("btn.quit"))
        quit_btn.setProperty("kind", "danger")
        quit_btn.clicked.connect(QApplication.quit)
        btns.addWidget(quit_btn)
        btns.addStretch()
        close_btn = QPushButton(_t("btn.close"))
        close_btn.setProperty("kind", "primary")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        main.addLayout(btns)
        return body

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
            self.acc_name.setText(_t("acc.switched"))
            self.avatar.set_letter("?")
            self.acc_email.setText(_t("acc.reopen"))
        else:
            acc = u.get("account") or "—"
            self.acc_name.setText(acc)
            self.avatar.set_letter(acc)
            self.acc_email.setText(u.get("email") or "")
        self.acc_plan.setText(plan)
        self._render_usage_rows(u)
        self._render_forecast(u)
        self.meta.setText(self._meta_text(u))
        self._render_availability(u)
        if self._pj_open:
            self._kick_projects()  # cheap incremental; lock prevents concurrency
            self._render_projects()
        if self._hr_open:
            self._render_hours()

    def _tick(self):
        # live countdown (1s): recomputes only the times/pace of the usage rows,
        # without redoing calc_usage/forecast/projects (those stay on the 5s cycle).
        if self._last_u is not None:
            self._render_usage_rows(self._last_u)
        self._tick_snooze()

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
                row = ForecastRow(_t("fc.week_model", model=model))
                self._fc_scoped[model] = row
                self.fc_box.addWidget(row)
            metric = f"7d:{w.get('model') or 'scoped'}"
            pts = history.series(metric, w.get("reset") or 0, account)
            row.set_data(pts, fc.get(metric), w.get("pct"),
                         until(w.get("reset")), stale)
        for model in list(self._fc_scoped):
            if model not in seen_fc:
                self._fc_scoped.pop(model).deleteLater()

    def _render_availability(self, u):
        text = availability_text(u)
        self.avail.setText(text or "")
        self.avail.setVisible(bool(text))
        self.avail.setStyleSheet(
            "color: %s; font-size: 11px; font-weight: 600;"
            % (RED if (u.get("availability") or {}).get("everything_blocked") else ORANGE))

    def _meta_text(self, u):
        parts = [_source_label(u.get("source"))]
        if u.get("stale"):
            age = u.get("stale_age_seconds")
            parts.append(_t("meta.stale_age", age=fmt_time(age)) if age is not None
                         else _t("meta.stale"))
        act = u.get("active_sessions") or 0
        if act:
            parts.append(_t("meta.session_one") if act == 1
                         else _t("meta.sessions", n=act))
        if u.get("overage_status") == "enabled":
            parts.append(_t("meta.extra_on"))
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

    # ---- notifications ----------------------------------------------------

    NOTIF_SWITCHES = [
        ("notif.threshold_crossed", "notify_on_threshold", True),
        ("notif.limit_reached", "notify_on_limit", True),
        ("notif.overflow_forecast", "forecast_notify", True),
        ("notif.limit_freed", "notify_on_reset", True),
        ("notif.telemetry_lost", "notify_on_telemetry", True),
    ]
    COOLDOWNS = [("notif.off", 0), ("5m", 5), ("15m", 15), ("30m", 30), ("1h", 60)]
    SNOOZES = [("30m", 30), ("2h", 120), ("notif.until_reset", -1)]

    def _hint(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color: {FG3}; font-size: 10px;")
        l.setWordWrap(True)
        return l

    def _build_notifications(self, sbox):
        sbox.addSpacing(12)
        sbox.addWidget(self._hint(_t("notif.thresholds_hint")))
        sbox.addSpacing(7)
        self.thr_row = QHBoxLayout()
        self.thr_row.setContentsMargins(0, 0, 0, 0)
        self.thr_row.setSpacing(8)
        sbox.addLayout(self.thr_row)
        self._render_thresholds()

        sbox.addSpacing(16)
        self.notif_switches = {}
        for i, (label, key, default) in enumerate(self.NOTIF_SWITCHES):
            if i:
                sbox.addSpacing(2)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(_t(label))
            lbl.setStyleSheet("font-size: 12px;")
            row.addWidget(lbl)
            row.addStretch()
            sw = ToggleSwitch(self.cfg.get(key, default))
            sw.onToggled(lambda v, k=key: self._on_notify_switch(k, v))
            self.notif_switches[key] = sw
            row.addWidget(sw)
            sbox.addLayout(row)

        sbox.addSpacing(16)
        sbox.addWidget(self._hint(_t("notif.gap_hint")))
        sbox.addSpacing(7)
        cool = QHBoxLayout()
        cool.setContentsMargins(0, 0, 0, 0)
        cool.setSpacing(6)
        self.cool_group = QButtonGroup(self)
        self.cool_group.setExclusive(True)
        current = int(self.cfg.get("notify_cooldown_minutes", 15))
        for label, minutes in self.COOLDOWNS:
            b = QPushButton(_t(label) if "." in label else label)
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(minutes == current)
            b.clicked.connect(lambda _c=False, m=minutes: self._on_cooldown(m))
            self.cool_group.addButton(b)
            cool.addWidget(b)
        cool.addStretch()
        sbox.addLayout(cool)

        sbox.addSpacing(16)
        self.snooze_row = QHBoxLayout()
        self.snooze_row.setContentsMargins(0, 0, 0, 0)
        self.snooze_row.setSpacing(6)
        sbox.addLayout(self.snooze_row)
        self.snooze_lbl = None
        self._render_snooze()

    def _on_language(self, code):
        if code == i18n.language() and self.cfg.get("language") == code:
            return
        self.cfg["language"] = code
        config.save(self.cfg)
        i18n.set_language(code)
        # Rebuild rather than retranslate widget by widget: every label,
        # header, tooltip and radio changes, and building the body is cheap
        # (the scroll area deletes the old one for us).
        self._scoped_rings.clear()
        self._fc_scoped.clear()
        self.scroll.setWidget(self._build_body())
        self._refresh()
        self._fit_to_screen()
        self.setWindowTitle(_t("app.title"))
        if self.dongle is not None:
            self.dongle._update_tooltip()

    def _on_notify_switch(self, key, value):
        self.cfg[key] = bool(value)
        config.save(self.cfg)

    def _on_cooldown(self, minutes):
        self.cfg["notify_cooldown_minutes"] = int(minutes)
        config.save(self.cfg)

    def _snooze_seconds_until_reset(self):
        u = self._last_u or {}
        secs = [s for s in (u.get("seconds_until_reset_5h"),
                            u.get("seconds_until_reset")) if s]
        return max(secs) if secs else 3600

    def _on_snooze(self, minutes):
        if minutes < 0:  # "until reset": silence through the longest open window
            minutes = max(1, int(self._snooze_seconds_until_reset() / 60))
        notifier.mute(str(SENT_PATH), minutes)
        self._render_snooze()

    def _on_resume(self):
        notifier.mute(str(SENT_PATH), 0)
        self._render_snooze()

    def _render_snooze(self):
        while self.snooze_row.count():
            it = self.snooze_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        until = notifier.muted_until(str(SENT_PATH))
        if until:
            self.snooze_lbl = QLabel()
            self.snooze_lbl.setStyleSheet(
                f"color: {ORANGE}; font-size: 11px; font-weight: 600;")
            self._tick_snooze(until)
            self.snooze_row.addWidget(self.snooze_lbl)
            self.snooze_row.addStretch()
            b = QPushButton(_t("notif.resume"))
            b.setProperty("kind", "ghost")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(self._on_resume)
            self.snooze_row.addWidget(b)
            return
        self.snooze_lbl = None
        lbl = QLabel(_t("notif.snooze_all"))
        lbl.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        self.snooze_row.addWidget(lbl)
        for label, minutes in self.SNOOZES:
            b = QPushButton(_t(label) if "." in label else label)
            b.setProperty("kind", "seg")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, m=minutes: self._on_snooze(m))
            self.snooze_row.addWidget(b)
        self.snooze_row.addStretch()

    def _tick_snooze(self, until=None):
        """Live countdown on the snooze label, and it drops back to the buttons
        the moment the mute expires (the notifier already ignores an expired
        one — this only keeps the panel from lying about it)."""
        lbl = getattr(self, "snooze_lbl", None)
        if lbl is None:
            return
        if until is None:
            until = notifier.muted_until(str(SENT_PATH))
        if not until:
            self._render_snooze()
            return
        lbl.setText(_t("notif.muted", time=fmt_time(int(until - time.time()))))

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
            e.setValidator(QIntValidator(1, 99, e))
            e.setFixedWidth(24)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Committed on Enter/focus-out, NEVER on every keystroke: saving
            # per keystroke turned typing "85" into a threshold of 8, and the
            # next poll dutifully alerted at 8%.
            e.editingFinished.connect(lambda w=e, idx=i: self._commit_thr(idx, w))
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
        add_btn = QPushButton("+")
        add_btn.setProperty("kind", "seg")
        add_btn.setFixedWidth(30)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_thr)
        self.thr_row.addWidget(add_btn)
        self.thr_row.addStretch()

    def _next_threshold(self):
        used = set(self.cfg.get("thresholds", []))
        for candidate in (50, 70, 85, 95, 60, 75, 90, 40, 30, 25):
            if candidate not in used:
                return candidate
        return 50

    def _add_thr(self):
        self.cfg.setdefault("thresholds", []).append(self._next_threshold())
        self._normalize_thresholds()

    def _del_thr(self, i):
        if len(self.cfg.get("thresholds", [])) > 1:
            self.cfg["thresholds"].pop(i)
            self._normalize_thresholds()

    def _commit_thr(self, i, widget):
        try:
            value = int(widget.text())
        except ValueError:
            self._normalize_thresholds()
            return
        try:
            self.cfg["thresholds"][i] = value
        except IndexError:
            return
        self._normalize_thresholds()

    def _normalize_thresholds(self):
        """Sorted, unique and in range: a duplicate alerts twice for the same
        crossing and a 0 alerts on every reading of an empty window."""
        thr = sorted({max(1, min(99, int(t)))
                      for t in self.cfg.get("thresholds", [])})
        self.cfg["thresholds"] = thr or [50]
        config.save(self.cfg)
        self._render_thresholds()
