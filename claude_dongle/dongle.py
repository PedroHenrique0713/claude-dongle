import subprocess, time, math, sys, os

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
                         QPainterPath, QRegion)

from . import monitor, config, notifier, usage_api
from .i18n import t as _t
from .utils import (color as _color, fmt_time as _fmt_time, limits_blocking,
                   availability_text, on_battery,
                   FG, FG2, FG3, ORANGE, RED, UI_FONT)

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")
TELEMETRY_PATH = str(config.CONFIG_DIR / "telemetry_state.json")

DONGLE_W, DONGLE_H = 216, 36
DONGLE_R = 18
PAD = 14
BAR_Y = 27.0
CLICK_SLOP = 8  # manhattan px: below this the release counts as a click
HOT_RESET_S = 30 * 60  # session resetting sooner than this: countdown gets highlighted
VIS_CHECK_MS = 5000  # visibility trigger (opening/closing a terminal reacts fast)
BREATH_PERIOD_S = 5.5   # one full in/out of the warning border
BATTERY_SLOWDOWN = 2    # every timer runs this much slower on battery
PS_CACHE_S = 4 if sys.platform.startswith("linux") else 20
BREATH_FRAME_MS = 80    # the timer ticks this often; a frame is only painted
                        # when the border actually changes (see _breath)
_ANIMATE = os.environ.get("QT_QPA_PLATFORM") != "offscreen"  # no animation when headless

# comm of the processes that mean "working on dev" (show_mode=dev mode)
DEV_PROCS = ["code", "cursor", "ptyxis", "gnome-terminal", "kgx", "konsole",
             "alacritty", "kitty", "wezterm", "tilix", "windowsterminal",
             "iterm", "terminal"]


def _process_names():
    """Yields running process names, lowercase. Empty if unavailable.

    On Linux this reads /proc directly instead of forking `ps`: measured at
    14ms against 114ms, and the caller stops at the first match, so the
    visibility check every 5s stopped costing ~2% of a core all day.
    macOS/Windows keep the subprocess (no /proc there).
    """
    if sys.platform.startswith("linux"):
        try:
            entries = os.scandir("/proc")
        except OSError:
            return
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                with open(entry.path + "/comm") as f:
                    yield f.read().strip().lower()
            except OSError:  # the process died between the scan and the read
                continue
        return
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"], text=True, timeout=3)
            for ln in out.splitlines():
                if ln:
                    yield ln.split('","')[0].lstrip('"').lower()
            return
        out = subprocess.check_output(["ps", "-eo", "comm="], text=True, timeout=3)
        # comm may include a path on macOS: keep just the basename
        for line in out.splitlines():
            yield line.strip().rsplit("/", 1)[-1].lower()
    except Exception:
        return


class DongleWidget(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        # No WA_TranslucentBackground (window turns invisible on XCB+XWayland);
        # pill shape via setMask, transparency only via setWindowOpacity.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Top-level popups (QMenu included) don't map in this setup — no menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setFixedSize(DONGLE_W, DONGLE_H)
        self.setWindowOpacity(self.cfg.get("dongle_opacity", 0.85))
        self._apply_mask()

        self._restore_position()

        self._press_pos = None    # global press position; immutable during the move
        self._move_anchor = None  # drag anchor; this one does get updated
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
        self._reset_5h_epoch = None  # epoch for live countdown (recomputed on paint)
        self._reset_w_epoch = None
        self._overflow = False    # some bucket forecast to overflow before the reset
        self._critical = False    # a limit that blocks everything is exhausted
        self._availability = None # what is spent right now (tooltip)
        self._budget_s = None     # seconds of work left at the current pace
        self._on_battery = False  # timers run slower while unplugged
        self._paint_stamp = None  # last countdown text painted (skips no-op repaints)
        self._breath_frame = None # last border frame painted (same idea)
        self._hidden = False
        self._idle_secs = 0
        self._ps_cache = None     # (t_monotonic, visible) so ps doesn't run 2x/5s

        self._font_label = QFont(UI_FONT, 7)
        self._font_value_5h = QFont(UI_FONT, 13, QFont.Weight.Bold)
        self._font_value_7d = QFont(UI_FONT, 9, QFont.Weight.DemiBold)
        self._font_reset = QFont(UI_FONT, 8)
        self._font_reset_hot = QFont(UI_FONT, 8, QFont.Weight.Bold)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(260)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._setup_timer()
        self.show()
        if _ANIMATE:
            self._start_fade_in()
        self.raise_()

    def _start_fade_in(self):
        # smooth fade-in: opacity from 0 to the configured value (startup and reappearance)
        target = self.cfg.get("dongle_opacity", 0.85)
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(target)
        self._fade.start()

    def _apply_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, DONGLE_W, DONGLE_H), DONGLE_R, DONGLE_R)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _pos_on_screen(self, x, y):
        # the dragged position must land (with visible margin) on some connected
        # screen — otherwise the dongle would vanish off-area after switching monitors
        for s in QApplication.screens():
            g = s.geometry()
            if g.left() <= x <= g.right() - 40 and g.top() <= y <= g.bottom() - 20:
                return True
        return False

    def _restore_position(self):
        pos = self.cfg.get("dongle_pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and \
                self._pos_on_screen(pos[0], pos[1]):
            self.move(int(pos[0]), int(pos[1]))
            return
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.left() + screen.width() - DONGLE_W - 12, screen.top() + 36)

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(self.cfg["poll_interval"] * 1000)
        # Visibility on its own timer, snappier than the data poll
        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._tick_visibility)
        self._vis_timer.start(VIS_CHECK_MS)
        # Animation: live countdown (1s) and border pulse when critical (~90ms,
        # adjusted in poll based on state)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim)
        self._anim_timer.start(1000)
        self.poll()

    def _pace_multiplier(self):
        return BATTERY_SLOWDOWN if self._on_battery else 1

    def _apply_power_mode(self):
        """On battery every timer runs at half rate.

        The dongle is a passenger on a laptop: polling, scanning processes and
        breathing at the same rate plugged or not spends the battery on a
        number that changes every five minutes anyway. Unplugging is noticed
        on the next poll — no extra timer to watch the cable.
        """
        wanted = on_battery() if self.cfg.get("battery_saver", True) else False
        if wanted == self._on_battery:
            return
        self._on_battery = wanted
        mult = self._pace_multiplier()
        self._timer.setInterval(int(self.cfg["poll_interval"] * 1000 * mult))
        self._vis_timer.setInterval(VIS_CHECK_MS * mult)
        print("[dongle] %s power mode" % ("battery" if wanted else "mains"),
              flush=True)

    def _breath(self):
        """(alpha, width) of the warning border right now.

        Slow sine (≈5.5s) smoothed by a smoothstep: it lingers at the ends the
        way breath does instead of strobing at the corner of the eye.
        """
        phase = (math.sin(time.monotonic() * math.tau / BREATH_PERIOD_S) + 1) / 2
        b = phase * phase * (3 - 2 * phase)
        return int(70 + 120 * b), round(1.2 + 1.0 * b, 1)

    def _on_anim(self):
        if self._hidden:
            return
        # Breathing border: repaint only when the border really changes. The
        # curve is flat at both ends, so a fixed frame rate spent most of its
        # repaints drawing the identical pixels — and a repaint here costs
        # ~2.7ms on XCB, which is what made an idle dongle burn ~5% of a core.
        if self._critical or self._overflow:
            frame = self._breath()
            if frame != self._breath_frame:
                self._breath_frame = frame
                self.update()
            return
        # Otherwise the only moving part is the session countdown, and
        # fmt_time's finest unit is the minute — repainting once a second was
        # 59 wasted repaints a minute, all day, on a laptop.
        secs = self._live_secs(self._reset_5h_epoch, self._reset_5h)
        stamp = (_fmt_time(secs), secs is not None and secs <= HOT_RESET_S)
        if stamp != self._paint_stamp:
            self._paint_stamp = stamp
            self.update()

    def _tick_visibility(self):
        was_hidden = self._hidden
        self._update_display()
        if was_hidden and not self._hidden:
            self._idle_secs = 0
            self.poll()  # reappeared: fresh data right away
            return
        if not self._hidden:
            self._idle_secs = 0
            return
        # Hidden: with no dev tools open the service has no reason to live.
        # The bashrc hook resurrects it on the next terminal (0 = never quit).
        quit_min = self.cfg.get("idle_quit_minutes", 10)
        if quit_min:
            self._idle_secs += VIS_CHECK_MS / 1000
            if self._idle_secs >= quit_min * 60:
                print(f"[dongle] idle for {quit_min}min with no dev tools — quitting", flush=True)
                QApplication.quit()

    def _compute_visible(self):
        mode = self.cfg.get("show_mode", "always")
        if mode == "always":
            return True
        # poll (data) and _vis_timer each fire every 5s; the cache keeps the
        # scan from running twice per cycle. Off Linux the scan is a
        # subprocess (`ps`/`tasklist`, ~100x the cost of reading /proc), so it
        # is held much longer — the price of noticing an editor a few seconds
        # later is smaller than a fork every five seconds all day.
        now = time.monotonic()
        if self._ps_cache and now - self._ps_cache[0] < PS_CACHE_S:
            return self._ps_cache[1]
        names = {"claude": ["claude"], "dev": DEV_PROCS,
                 "custom": self.cfg.get("show_processes", [])}.get(mode, [])
        visible = False
        if names:
            # prefix match (Linux comm truncates at 15 chars); never a
            # substring over the whole blob ("code" would match "opencode")
            names = [n.lower() for n in names]
            # generator + any(): stops at the first matching process instead
            # of listing every process on the machine
            visible = any(p.startswith(n) for p in _process_names() for n in names)
        self._ps_cache = (now, visible)
        return visible

    def _update_display(self):
        visible = self._compute_visible()
        if visible:
            if self._hidden:
                self.show()
                self._hidden = False
                if _ANIMATE:
                    self._start_fade_in()  # reappeared (terminal open): smooth fade-in
        else:
            if not self._hidden:
                self.hide()
                self._hidden = True

    def poll(self):
        try:
            self._update_display()
            if self._hidden:
                return  # no dev tools open: don't waste an API call
            # cfg is shared with the Dashboard: reapply live changes
            # (but not during the fade-in, or it would jump to the final opacity)
            if self._fade.state() != QPropertyAnimation.State.Running:
                self.setWindowOpacity(self.cfg.get("dongle_opacity", 0.85))
            u = monitor.calc_usage(self.cfg)

            if u.get("account_changed"):
                if u.get("identity_stale"):
                    notifier.send("Account switched",
                                  f"Now on the {u['plan']} plan · reopen Claude "
                                  "Code to sync the name")
                else:
                    notifier.send(_t("n.account_title", account=u["account"]),
                                  _t("n.account_body", plan=u["plan"]))

            self._s_pct = u.get("pct_5h")
            # Overall weekly and per-model weekly (e.g. Fable) are separate
            # limits: the dongle shows both
            breakdown = u.get("weekly_breakdown") or []
            w_all = next((w.get("pct") for w in breakdown
                          if w.get("kind") == "weekly_all"), None)
            scoped = [w for w in breakdown
                      if w.get("kind") == "weekly_scoped" and w.get("pct") is not None]
            top = max(scoped, key=lambda w: w["pct"]) if scoped else None
            self._w_all = w_all if w_all is not None else u.get("pct_7d", u["pct"])
            self._scoped_pct = top["pct"] if top else None
            self._scoped_name = (top.get("model") or "model") if top else None
            self._stale = u.get("stale", False)
            self._source = u["source"]
            self._reset_5h = u.get("seconds_until_reset_5h")
            self._reset_w = u.get("seconds_until_reset")
            self._reset_5h_epoch = u.get("reset_5h_epoch")
            self._reset_w_epoch = u.get("reset_7d_epoch")
            fcs = u.get("forecast") or {}
            # 'alert' (not raw 'overflow'): only blinks when the overflow is
            # actionable — the bucket already crossed the floor. Avoids blinking on
            # short-term burn rate extrapolated over days while usage is still low.
            self._overflow = (not self._stale) and any(
                v.get("alert") for v in fcs.values())
            # The budget is the TIGHTEST of the windows: the first ceiling you
            # hit is the one that stops the work.
            etas = [v["eta_seconds"] for v in fcs.values()
                    if v.get("eta_seconds") is not None]
            self._budget_s = min(etas) if etas and not self._stale else None
            # A scoped model running out (Fable at 100%) does NOT stop the
            # work — the other models keep going against the overall week. Red
            # is for the limits that stop EVERYTHING: the 5h session and the
            # overall week. The scoped number already turns red on its own.
            self._availability = u.get("availability")
            self._critical = (not self._stale) and limits_blocking(
                self._s_pct, self._w_all)
            self._apply_power_mode()
            # smooth frames while breathing; else 1s just for the countdown
            self._anim_timer.setInterval(
                (BREATH_FRAME_MS if (self._critical or self._overflow) else 1000)
                * self._pace_multiplier())
            self._update_tooltip()

            self.update()

            notifier.check_telemetry(u, self.cfg, TELEMETRY_PATH)
            last = self._last_usage or {}
            if (u["pct"], u.get("pct_5h")) != (last.get("pct"), last.get("pct_5h")):
                notifier.check_thresholds(u, self.cfg, SENT_PATH)
            self._last_usage = u
        except Exception:
            import traceback; traceback.print_exc()

    def _live_secs(self, epoch, fallback):
        # live countdown: recompute from epoch when present, else use the fixed value
        if epoch:
            return max(0, int(epoch - time.time()))
        return fallback

    def _update_tooltip(self):
        src = {"api": _t("src.api"), "none": _t("src.none")}.get(self._source,
                                                                 self._source)
        lines = [_t("tip.source", src=src) + (_t("tip.stale") if self._stale else "")]
        if self._s_pct is not None:
            lines.append(_t("tip.session", pct=f"{self._s_pct:.0f}",
                            time=_fmt_time(self._reset_5h)))
        if self._w_all is not None:
            lines.append(_t("tip.week", pct=f"{self._w_all:.0f}",
                            time=_fmt_time(self._reset_w)))
        if self._scoped_pct is not None:
            lines.append(_t("tip.week_model", model=self._scoped_name,
                            pct=f"{self._scoped_pct:.0f}"))
        spent = availability_text({"availability": self._availability,
                                   "seconds_until_reset": self._reset_w,
                                   "seconds_until_reset_5h": self._reset_5h})
        if spent:
            lines.append(spent)
        if self._budget_s is not None:
            lines.append(_t("tip.budget", eta=_fmt_time(self._budget_s)))
        if self._overflow:
            lines.append(_t("tip.overflow"))
        lines.append(_t("tip.actions"))
        self.setToolTip("\n".join(lines))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0.5, 0.5, DONGLE_W - 1, DONGLE_H - 1),
                            DONGLE_R - 0.5, DONGLE_R - 0.5)
        p.setBrush(QBrush(QColor("#000000")))
        # Pulsing border: red when some limit crossed 95%, amber when an
        # overflow is forecast — at-a-glance warning without cluttering the 216×36.
        if self._critical or self._overflow:
            alpha, width = self._breath()
            edge = QColor(RED if self._critical else ORANGE)
            edge.setAlpha(alpha)
            p.setPen(QPen(edge, width))
        else:
            p.setPen(QPen(QColor("#2c2c31"), 1))
        p.drawPath(body)

        row = lambda x, w: QRectF(x, 4, w, 20)

        # Measure the right-side groups first: the left may never invade them
        def group_w(label, pct):
            val = f"{pct:.0f}%" if pct is not None else "--"
            return (QFontMetrics(self._font_label).horizontalAdvance(label) + 4 +
                    QFontMetrics(self._font_value_7d).horizontalAdvance(val))

        right_w = group_w("7d", self._w_all)
        if self._scoped_pct is not None:
            right_w += 9 + group_w(self._scoped_name, self._scoped_pct)
        left_max = DONGLE_W - PAD - right_w - 8

        # Session (5h): the dominant metric, on the left
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

        # Session reset countdown (live: recomputed from epoch on every paint)
        reset_5h = self._live_secs(self._reset_5h_epoch, self._reset_5h)
        if reset_5h is not None and x + 5 < left_max:
            hot = reset_5h <= HOT_RESET_S and not self._stale
            reset_txt = _fmt_time(reset_5h)
            f = self._font_reset_hot if hot else self._font_reset
            p.setFont(f)
            p.setPen(QPen(QColor(FG3 if self._stale else (FG if hot else FG2))))
            p.drawText(row(x + 5, left_max - x - 5),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, reset_txt)
            x += 5 + min(QFontMetrics(f).horizontalAdvance(reset_txt), left_max - x - 5)
        self._paint_bar(p, PAD, BAR_Y, min(x, left_max) - PAD, self._s_pct, c5)

        # Weeklies on the right: per model (e.g. Fable) and overall
        right = DONGLE_W - PAD
        if self._scoped_pct is not None:
            right = self._draw_compact(p, right, self._scoped_name, self._scoped_pct)
            right -= 9
        self._draw_compact(p, right, "7d", self._w_all)
        p.end()

    def _draw_compact(self, p, right, label, pct):
        # Secondary metric aligned to the right edge; returns the starting x
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
        # Gray when stale: old data must never look live
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
        # The click-vs-drag reference does NOT change during the move
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
        dragged = self._dragging  # only the left button sets _dragging in move
        self._press_pos = None
        self._dragging = False
        if dragged:  # real drag: snaps to the edge and persists (survives the idle-kill)
            self._snap_to_edge()
            pos = self.pos()
            self.cfg["dongle_pos"] = [pos.x(), pos.y()]
            config.save(self.cfg)
            return
        if was_drag:
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._force_refresh()
        elif event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._open_dashboard()

    def _snap_to_edge(self):
        # Dragged near an edge of the current screen → snap to the corner.
        SNAP, M = 26, 10
        scr = (self.screen() or QApplication.primaryScreen()).geometry()
        x, y = self.x(), self.y()
        if abs(x - scr.left()) < SNAP:
            x = scr.left() + M
        elif abs((x + DONGLE_W) - scr.right()) < SNAP:
            x = scr.right() - DONGLE_W - M
        if abs(y - scr.top()) < SNAP:
            y = scr.top() + M
        elif abs((y + DONGLE_H) - scr.bottom()) < SNAP:
            y = scr.bottom() - DONGLE_H - M
        self.move(x, y)

    def _force_refresh(self):
        # Middle click: bypass the cache and fetch fresh data right away.
        usage_api.invalidate()
        self.poll()

    def _open_dashboard(self):
        if self._dash is not None:
            try:
                self._dash.raise_()
                self._dash.activateWindow()
                return
            except RuntimeError:
                self._dash = None
        try:
            from .dashboard_ui import DashboardWidget
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
