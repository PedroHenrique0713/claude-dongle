#!/usr/bin/env python3
"""Generates the README screenshots with FAKE data, offscreen.

Regenerates docs/{dongle,dashboard,dashboard-full,notifications}.png through the
app's own renderer (pixel-faithful), swapping real account/email/projects for
anonymous data — so no PII ever leaks into captures of a repo that may go public.

Usage:
    python scripts/gen_screenshots.py            # writes into docs/
    python scripts/gen_screenshots.py /tmp/out   # writes into another directory

Edit the FAKE_* constants below to change the displayed data.

Note (costly gotcha): instantiating the dongle/dashboard calls poll()/_refresh(),
which fires a REAL notify-send. This script neutralizes notifier/monitor/projects/
history BEFORE instantiating any widget — no network, no reading the real
~/.claude, no writing to the user's config, no on-screen notification.
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # before any Qt import

from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs"

# --- fake data (edit freely) --------------------------------------------------
FAKE_ACCOUNT = "Alex Doe"
FAKE_EMAIL = "alex@example.com"
FAKE_PLAN = "max"
FAKE_MODELS = [
    {"name": "claude-opus-4-8",  "output": 16_100_000, "total": 128_000_000},
    {"name": "claude-fable-5",   "output":  7_000_000, "total":  56_000_000},
    {"name": "claude-sonnet-5",  "output":  1_100_000, "total":   8_800_000},
]
HEAT = [2, 3, 4, 3, 1, 5, 4, 2, 0, 3, 4, 5, 3, 7]   # per-day intensity (heatmap)

NOW = time.time()
RESET_5H = NOW + 8700       # 2h25
RESET_7D = NOW + 319980     # 3d 16h53

FAKE_U = {
    "pct": 34.0, "pct_7d": 34.0, "pct_5h": 46.0,
    "source": "api", "stale": False,
    "account_changed": False, "identity_stale": False,
    "account": FAKE_ACCOUNT, "plan": FAKE_PLAN, "email": FAKE_EMAIL,
    "active_sessions": 2, "idle_sessions": 0,
    "seconds_until_reset": int(RESET_7D - NOW),
    "seconds_until_reset_5h": int(RESET_5H - NOW),
    "reset_7d_epoch": RESET_7D, "reset_5h_epoch": RESET_5H,
    "weekly_breakdown": [
        {"kind": "weekly_all", "pct": 34.0, "reset": RESET_7D},
        {"kind": "weekly_scoped", "model": "Fable", "pct": 58.0, "reset": RESET_7D},
    ],
    "forecast": {
        "5h": {"rate_pph": 5.0, "eta_seconds": 37980,
               "overflow_before_reset": False, "alert": False},
        "7d": {"rate_pph": 0.8, "eta_seconds": 289980,
               "overflow_before_reset": False, "alert": False},
        "7d:Fable": {"rate_pph": 3.0, "eta_seconds": 49980,
                     "overflow_before_reset": True, "alert": True},
    },
}

# texts identical to those emitted in notifier.py (check_thresholds / forecast)
FAKE_NOTIFS = [
    ("5h session · 85%", "Resets in 2h25"),
    ("Fable week · overflow forecast",
     "58% now · +3.0 p.p./h · overflows in 13h53, before the reset in 3d 16h53"),
    ("Overall week · 70%", "Resets in 3d 16h52"),
]

# --- neutralize everything that leaves the machine / writes / notifies -------
from claude_dongle import monitor, projects, history, notifier, config, i18n

# The README is in English; without this the shots would follow the
# machine's locale (pt_BR here).
i18n.set_language("en")

notifier.send = lambda *a, **k: None
notifier.check_thresholds = lambda *a, **k: False
notifier.check_telemetry = lambda *a, **k: False
monitor.calc_usage = lambda cfg: dict(FAKE_U)
projects.refresh = lambda *a, **k: 0
projects.summary = lambda days=7, limit=8: {"models": FAKE_MODELS, "days": days}
projects.daily = lambda days=14: [
    (f"2026-06-{20 + i:02d}", HEAT[i] * 120_000) for i in range(14)]
history.record = lambda *a, **k: None
# A plausible working day — never the real profile: it would put the author's
# actual working hours in a public README.
FAKE_HOURS = [0.2, 0.1, 0, 0, 0, 0, 0, 0.3, 1.1, 2.4, 3.6, 4.1, 2.2, 3.9,
              5.4, 4.8, 5.9, 6.8, 4.2, 2.6, 3.1, 2.0, 0.9, 0.4]
history.hourly_profile = lambda *a, **k: {
    "hours": FAKE_HOURS, "days": 14, "peak": 17}
history.attach_forecasts = lambda *a, **k: None
config.save = lambda *a, **k: None


def _fake_series(metric, *a, **k):
    final = {"5h": 46, "7d": 34, "7d:Fable": 58}.get(metric, 30)
    n = 14
    return [(NOW - (n - 1 - i) * 260, final * (0.55 + 0.45 * i / (n - 1)))
            for i in range(n)]
history.series = _fake_series

# --- Qt ----------------------------------------------------------------------
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import (QPixmap, QColor, QPainter, QFont, QFontMetrics, QBrush,
                         QPen, QPainterPath, QLinearGradient)
from PyQt6.QtCore import Qt, QRectF, QRect

app = QApplication(sys.argv[:1])

from claude_dongle.dongle import DongleWidget, DONGLE_W, DONGLE_H
from claude_dongle.dashboard_ui import DashboardWidget
from claude_dongle.utils import UI_FONT, ACCENT, ACCENT2


def _cfg(**over):
    c = dict(config.DEFAULTS)          # show_mode="dev" → "Only with VS Code / terminal" radio
    c.update(dongle_opacity=1.0, dongle_pos=None, language="en")
    c.update(over)
    return c


def gen_app_shots():
    # dongle (opaque RGB 216x36; the corners get the same pure black as the body)
    d = DongleWidget(_cfg(show_mode="always"))   # always: doesn't hide during the grab
    d._overflow = False                          # clean border, no amber pulse
    d._critical = False
    d.update(); app.processEvents()
    pm = QPixmap(DONGLE_W, DONGLE_H)
    pm.fill(QColor("#000000"))
    d.render(pm)
    pm.save(str(OUT / "dongle.png"))

    for name, over in (("dashboard", dict(forecast_expanded=False, projects_expanded=False,
                                          settings_expanded=False)),
                       ("dashboard-full", dict(forecast_expanded=True, projects_expanded=True,
                                               hours_expanded=True,
                                               settings_expanded=True))):
        w = DashboardWidget(_cfg(**over))
        w.show(); app.processEvents()
        # On a real screen the panel is capped and scrolls; a screenshot must
        # still show the whole thing, so lift the cap just for the grab.
        w.setMaximumHeight(16777215)
        w.resize(w.width(), w.scroll.widget().sizeHint().height())
        app.processEvents()
        w.grab().save(str(OUT / f"{name}.png"))
        w.close(); app.processEvents()
    print("app shots:", "dongle dashboard dashboard-full")


def gen_notifs():
    """Mockup of the GNOME toasts (Cantarell, rounded cards, brand icon)."""
    SCALE = 2
    W = 392
    CARD_X, CARD_W = 8, 392 - 16
    PAD_L, PAD_T, PAD_B = 16, 14, 14
    ICON = 30
    TXT_X = PAD_L + ICON + 12
    TXT_W = CARD_W - TXT_X - 16
    GAP = 12
    BG_CARD, BORDER = QColor("#2c2c31"), QColor(255, 255, 255, 24)
    C_APP, C_TITLE, C_BODY = QColor("#a8a8b4"), QColor("#f5f5f8"), QColor("#c2c2cc")

    f_app = QFont(UI_FONT, 8)
    f_title = QFont(UI_FONT, 10, QFont.Weight.Bold)
    f_body = QFont(UI_FONT, 9)
    fm_body, fm_title = QFontMetrics(f_body), QFontMetrics(f_title)

    def body_h(text):
        return fm_body.boundingRect(QRect(0, 0, TXT_W, 1000),
                                    int(Qt.TextFlag.TextWordWrap), text).height()

    heights = [int(PAD_T + 16 + 6 + fm_title.height() + 4 + body_h(b) + PAD_B)
               for _t, b in FAKE_NOTIFS]
    total_h = sum(heights) + GAP * (len(FAKE_NOTIFS) - 1) + 8

    pm = QPixmap(W * SCALE, total_h * SCALE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(SCALE, SCALE)

    y = 4
    for (title, body), ch in zip(FAKE_NOTIFS, heights):
        card = QRectF(CARD_X, y, CARD_W, ch)
        path = QPainterPath(); path.addRoundedRect(card, 13, 13)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(BG_CARD)); p.drawPath(path)
        p.setPen(QPen(BORDER, 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)

        ix, iy = CARD_X + PAD_L, y + PAD_T
        g = QLinearGradient(ix, iy, ix + ICON, iy + ICON)
        g.setColorAt(0.0, QColor(ACCENT)); g.setColorAt(1.0, QColor(ACCENT2))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(ix, iy, ICON, ICON))
        p.setPen(QPen(QColor("white"))); p.setFont(QFont(UI_FONT, 11, QFont.Weight.Bold))
        p.drawText(QRectF(ix, iy, ICON, ICON), Qt.AlignmentFlag.AlignCenter, "C")

        tx = CARD_X + TXT_X
        p.setFont(f_app); p.setPen(QPen(C_APP))
        p.drawText(QRectF(tx, y + PAD_T + 1, TXT_W, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Claude Monitor")
        p.drawText(QRectF(tx, y + PAD_T + 1, TXT_W, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "now")
        ty = y + PAD_T + 16 + 6
        p.setFont(f_title); p.setPen(QPen(C_TITLE))
        p.drawText(QRectF(tx, ty, TXT_W, fm_title.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, title)
        by = ty + fm_title.height() + 4
        p.setFont(f_body); p.setPen(QPen(C_BODY))
        p.drawText(QRectF(tx, by, TXT_W, body_h(body) + 4),
                   int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft)
                   | int(Qt.AlignmentFlag.AlignTop), body)
        y += ch + GAP
    p.end()
    pm.setDevicePixelRatio(SCALE)
    pm.save(str(OUT / "notifications.png"))
    print("notifs:", "notifications")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    gen_app_shots()
    gen_notifs()
    print("OK ->", OUT)
