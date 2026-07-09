import os, threading, time, math, json
os.environ['QT_QPA_PLATFORM'] = 'xcb'
import monitor, config, notifier, proxy
from utils import (color as _color, fmt_time as _fmt_time,
                   RED, ORANGE, YELLOW, GREEN, BG, BG2, BG3, FG, FG2, FG3, SEP, ACCENT)

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")
_last_usage = None
_dash_instance = None

try:
    from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                                 QHBoxLayout, QGridLayout, QFrame, QMenu)
    from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint, QEvent, pyqtSignal, QPropertyAnimation, QEasingCurve
    from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QFontDatabase,
                             QLinearGradient, QPainterPath, QRadialGradient, QRegion, QAction)
    _USE_QT = True
except ImportError:
    _USE_QT = False

if not _USE_QT:
    def run(cfg):
        print("PyQt6 not available")
else:
    DONGLE_W, DONGLE_H = 96, 44
    DONGLE_R = 22

    # Colors (QColor instances from utils strings)
    BG_C = QColor(BG)
    BG2_C = QColor(BG2)
    BG3_C = QColor(BG3)
    FG_C = QColor(FG)
    FG2_C = QColor(FG2)
    FG3_C = QColor(FG3)
    SEP_C = QColor(SEP)
    RED_C = QColor(RED)
    ORANGE_C = QColor(ORANGE)
    YELLOW_C = QColor(YELLOW)
    GREEN_C = QColor(GREEN)
    ACCENT_C = QColor(ACCENT)

    # App instance shared
    _app = None

    def get_app():
        global _app
        if _app is None:
            _app = QApplication([])
            _app.setQuitOnLastWindowClosed(False)
            _app.setStyle("Fusion")
        return _app

    class DongleWidget(QWidget):
        def __init__(self, cfg):
            super().__init__()
            self.cfg = cfg
            self._drag_pos = QPoint()
            self._dragging = False
            self._popup_menu = None
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint
            )
            # No WA_TranslucentBackground (causes invisible window on XWayland);
            # use setMask to clip the pill shape and windowOpacity for translucency
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setFixedSize(DONGLE_W, DONGLE_H)
            self.setWindowOpacity(self.cfg.get("dongle_opacity", 0.88))
            self._apply_mask()

            screen = QApplication.primaryScreen().geometry()
            self.move(screen.width() - DONGLE_W - 12, 36)

            self._drag_pos = QPoint()
            self._dragging = False
            self._s_pct = None
            self._w_pct = None
            self._source = "jobs"
            self._stale = False
            self._fill_color = GREEN_C
            self._hidden = False
            self._reset_5h = None
            self._reset_w = None

            self._init_font()
            self._setup_timers()
            self.show()
            self.raise_()

        def _init_font(self):
            self.font_s = QFont("Cantarell", 9, QFont.Weight.Bold)
            self.font_w = QFont("Cantarell", 8)

        def _apply_mask(self):
            path = QPainterPath()
            path.addRoundedRect(0, 0, DONGLE_W, DONGLE_H, DONGLE_R, DONGLE_R)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

        def _setup_timers(self):
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.timer.start(self.cfg["poll_interval"] * 1000)
            self._update_display()
            self.poll()

        def _update_display(self):
            visible = True
            mode = self.cfg.get("show_mode", "always")
            if mode != "always":
                import subprocess
                names = {"claude": ["claude"], "dev": ["code", "gnome-terminal", "ptyxis"],
                         "custom": self.cfg.get("show_processes", [])}.get(mode, [])
                visible = False
                if names:
                    try:
                        out = subprocess.check_output(["ps", "-eo", "comm="], text=True, timeout=3)
                        visible = any(n in out for n in names)
                    except: pass
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
                u = monitor.calc_usage(self.cfg)
                global _last_usage

                if u.get("account_changed"):
                    notifier.send(f"Conta trocada: {u['account']}",
                                  f"Plano: {u['plan']} | Email: {u['email']}")

                s_pct = u.get("pct_5h")
                w_pct = u.get("pct_7d", u["pct"])
                max_pct = max(s_pct or 0, w_pct)
                new_color = QColor(_color(max_pct))
                if new_color != self._fill_color:
                    self._fill_color = new_color
                self._s_pct = s_pct
                self._w_pct = w_pct
                self._source = u["source"]
                self._stale = u.get("stale", False)
                self._reset_5h = u.get("seconds_until_reset_5h")
                self._reset_w = u.get("seconds_until_reset")

                self.update()

                if u["pct"] != (_last_usage or {}).get("pct"):
                    notifier.check_thresholds(u, self.cfg, SENT_PATH)
                _last_usage = u
            except Exception:
                import traceback; traceback.print_exc()

        def paintEvent(self, event):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            r = DONGLE_R
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, DONGLE_W, DONGLE_H), r, r)

            # Shadow
            shadow = QPainterPath()
            shadow.addRoundedRect(QRectF(2, 3, DONGLE_W, DONGLE_H), r, r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 0, 0, 80)))
            p.drawPath(shadow)

            # Background
            bg = QLinearGradient(0, 0, 0, DONGLE_H)
            bg.setColorAt(0, QColor("#1e1e1e"))
            bg.setColorAt(1, QColor("#151515"))
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor("#333333"), 1))
            p.drawPath(path)

            # Accent fill overlay (80% width, bottom-aligned bar)
            if self._s_pct is not None or self._w_pct is not None:
                max_p = max(self._s_pct or 0, self._w_pct or 0)
                fill_h = int((DONGLE_H - 4) * (max_p / 100))
                fill_h = max(0, min(DONGLE_H - 4, fill_h))
                if fill_h > 0:
                    accent = QColor(self._fill_color)
                    accent.setAlpha(35)
                    fill_rect = QRectF(2, DONGLE_H - 2 - fill_h, DONGLE_W - 4, fill_h)
                    fill_path = QPainterPath()
                    fill_path.addRoundedRect(fill_rect, r - 2, r - 2)
                    p.setBrush(QBrush(accent))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawPath(fill_path)

            # Text
            s_val = self._s_pct
            w_val = self._w_pct
            s_str = f"{s_val:.0f}%" if s_val is not None else "--"
            w_str = f"{w_val:.0f}%" if w_val is not None else "--"
            p.setFont(self.font_s)
            # Grey text = data is stale (API/proxy unreachable), not a live pct
            c = FG3_C if self._stale else QColor(self._fill_color)
            p.setPen(QPen(c))
            p.drawText(QRectF(12, 5, DONGLE_W - 16, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       s_str)

            p.setFont(self.font_w)
            p.setPen(QPen(FG2_C))
            reset_str = ""

            # Use already-polled data for reset time
            try:
                if self._reset_5h is not None:
                    reset_str = f"  ⟳{_fmt_time(self._reset_5h)}"
                elif self._reset_w is not None:
                    reset_str = f"  ⟳{_fmt_time(self._reset_w)}"
            except: pass

            p.drawText(QRectF(12, 23, DONGLE_W - 16, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{w_str}{reset_str}")

            p.end()

        def mousePressEvent(self, event):
            self._press_time = time.time()
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_pos = event.globalPosition().toPoint()
                self._drag_start_pos = QPoint()
            self._dragging = False
            self._popup_menu = None

        def mouseMoveEvent(self, event):
            if event.buttons() & Qt.MouseButton.LeftButton:
                delta = event.globalPosition().toPoint() - self._drag_pos
                if delta.manhattanLength() > 8:
                    self._dragging = True
                self.move(self.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()

        def mouseReleaseEvent(self, event):
            press_duration = time.time() - getattr(self, '_press_time', time.time())
            moved = (event.globalPosition().toPoint() - getattr(self, '_drag_pos', event.globalPosition().toPoint())).manhattanLength()
            if self._dragging or press_duration >= 0.5 or moved >= 10:
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self._show_menu()
            elif event.button() == Qt.MouseButton.RightButton:
                self._open_dashboard()

        def contextMenuEvent(self, event):
            self._show_menu()

        def _open_dashboard(self):
            global _dash_instance
            if _dash_instance is not None:
                try:
                    _dash_instance.raise_()
                    _dash_instance.activateWindow()
                    return
                except Exception as e:
                    print(f"[dash] raise failed: {e}", flush=True)
            try:
                d = Dashboard(self.cfg)
                _dash_instance = d.root
                def _clear():
                    global _dash_instance
                    _dash_instance = None
                d.root.destroyed.connect(_clear)
                d.root.show()
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[dash] failed: {e}", flush=True)

        def _show_menu(self):
            m = QMenu()
            m.setStyleSheet("QMenu { background: #1c1c1e; color: #e8e8e8; border: 1px solid #333; } QMenu::item:disabled { color: #888; } QMenu::item:selected:!disabled { background: #2a5c2a; }")
            m.addAction("Dashboard").triggered.connect(self._open_dashboard)
            m.addSeparator()
            m.addAction("Sair").triggered.connect(QApplication.quit)
            px = self.x()
            sw = QApplication.primaryScreen().geometry().width()
            if px + 200 > sw:
                px = sw - 208
            m.setMinimumWidth(200)
            self._popup_menu = m
            m.exec(QPoint(px, self.y() + self.height() + 4))
            self._popup_menu = None

    class DashboardWidget(QWidget):
        def __init__(self, cfg):
            super().__init__()
            self.cfg = cfg
            self.setWindowTitle("Claude Monitor")
            self.setFixedSize(420, 520)
            self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setStyleSheet(self._style())

            self._setup_ui()

        def _style(self):
            return """
            QWidget { background: #0d0d0d; color: #e8e8e8; font-family: Cantarell; }
            QLabel { background: transparent; }
            QLabel[heading="true"] { font-size: 15px; font-weight: bold; }
            QLabel[section="true"] { font-size: 9px; color: #888; font-weight: bold; padding-top: 6px; }
            QSlider::groove:horizontal {
                height: 4px; background: #333; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; margin: -5px 0;
                background: #555; border-radius: 7px;
            }
            QSlider::sub-page:horizontal { background: #4488ff; border-radius: 2px; }
            QPushButton {
                background: #252525; color: #e8e8e8; border: 1px solid #333;
                border-radius: 6px; padding: 4px 16px; font-size: 10px;
            }
            QPushButton:hover { background: #333; }
            QPushButton[pink="true"] { background: #2a1515; border-color: #5c2a2a; color: #ff2244; }
            QPushButton[pink="true"]:hover { background: #3a2020; }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator {
                width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid #555; background: #1a1a1a;
            }
            QCheckBox::indicator:checked { background: #4488ff; border-color: #4488ff; }
            QRadioButton { spacing: 8px; }
            QRadioButton::indicator {
                width: 14px; height: 14px; border-radius: 7px;
                border: 1px solid #555; background: #1a1a1a;
            }
            QRadioButton::indicator:checked { background: #4488ff; border-color: #4488ff; }
            QLineEdit {
                background: #1a1a1a; color: #e8e8e8; border: 1px solid #333;
                border-radius: 4px; padding: 2px 6px;
            }
            """

        def _setup_ui(self):
            from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                                         QPushButton, QSlider, QCheckBox,
                                         QRadioButton, QButtonGroup, QLineEdit,
                                         QGridLayout, QFrame)
            main = QVBoxLayout(self)
            main.setContentsMargins(16, 16, 16, 16)
            main.setSpacing(0)

            def h(): return QHBoxLayout()
            def heading(text):
                l = QLabel(text)
                l.setProperty("heading", True)
                return l
            def section(text):
                l = QLabel(text)
                l.setProperty("section", True)
                return l
            def sep():
                f = QFrame()
                f.setFixedHeight(1)
                f.setStyleSheet("background: #2a2a2a;")
                return f
            def btn(text, pink=False):
                b = QPushButton(text)
                if pink: b.setProperty("pink", True)
                return b

            main.addWidget(heading("Claude Monitor"))
            main.addSpacing(4)
            main.addWidget(sep())
            main.addSpacing(4)

            # Account
            main.addWidget(section("CONTA"))
            self.acc_name = QLabel("carregando…")
            self.acc_name.setStyleSheet("font-size: 13px; font-weight: bold;")
            main.addWidget(self.acc_name)
            self.acc_email = QLabel("")
            self.acc_email.setStyleSheet("font-size: 9px; color: #888;")
            main.addWidget(self.acc_email)
            self.acc_plan = QLabel("")
            self.acc_plan.setStyleSheet("font-size: 9px; color: #888;")
            main.addWidget(self.acc_plan)
            main.addSpacing(8)
            main.addWidget(sep())
            main.addSpacing(4)

            # Dongle section
            main.addWidget(section("DONGLE"))
            row = h()
            row.addWidget(QLabel("Opacidade"))
            self.op_slider = QSlider(Qt.Orientation.Horizontal)
            self.op_slider.setRange(30, 100)
            self.op_slider.setValue(int(self.cfg.get("dongle_opacity", 0.85) * 100))
            self.op_slider.valueChanged.connect(self._on_opacity)
            row.addWidget(self.op_slider)
            self.op_label = QLabel(f"{self.op_slider.value()}%")
            self.op_label.setFixedWidth(36)
            row.addWidget(self.op_label)
            main.addLayout(row)

            row2 = h()
            self.ontop_cb = QCheckBox("Sempre no topo")
            self.ontop_cb.setChecked(self.cfg.get("dongle_always_on_top", True))
            self.ontop_cb.toggled.connect(self._save)
            row2.addWidget(self.ontop_cb)
            row2.addStretch()
            main.addLayout(row2)
            main.addSpacing(8)
            main.addWidget(sep())
            main.addSpacing(4)

            # Visibility
            main.addWidget(section("VISIBILIDADE"))
            self.show_group = QButtonGroup(self)
            for text, val in [("Sempre visível", "always"),
                              ("Só com Claude Code", "claude"),
                              ("Só com VS Code / terminal", "dev"),
                              ("Processos específicos", "custom")]:
                rb = QRadioButton(text)
                rb.setChecked(self.cfg.get("show_mode", "always") == val)
                self.show_group.addButton(rb, 100 + ["always", "claude", "dev", "custom"].index(val))
                main.addWidget(rb)
            self.show_group.idToggled.connect(self._save)
            main.addSpacing(8)
            main.addWidget(sep())
            main.addSpacing(4)

            # Notifications
            main.addWidget(section("NOTIFICAÇÕES (%)"))
            self.thr_layout = QHBoxLayout()
            main.addLayout(self.thr_layout)
            self._render_thresholds()
            add_btn = QPushButton("+ Adicionar")
            add_btn.clicked.connect(self._add_thr)
            main.addWidget(add_btn)
            main.addSpacing(8)
            main.addWidget(sep())
            main.addSpacing(4)

            # Proxy status
            self.proxy_label = QLabel("")
            self.proxy_label.setStyleSheet("font-size: 9px;")
            main.addWidget(self.proxy_label)
            main.addSpacing(8)

            # Buttons
            row_btns = h()
            row_btns.addStretch()
            close_btn = QPushButton("Fechar")
            close_btn.setProperty("pink", True)
            close_btn.clicked.connect(self.close)
            row_btns.addWidget(close_btn)
            main.addLayout(row_btns)
            main.addStretch()

            self._refresh_loop()

        def _render_thresholds(self):
            for i in reversed(range(self.thr_layout.count())):
                w = self.thr_layout.itemAt(i).widget()
                if w: w.deleteLater()

            for i, t in enumerate(self.cfg.get("thresholds", [])):
                from PyQt6.QtWidgets import QLineEdit, QPushButton, QHBoxLayout
                w = QWidget()
                w.setStyleSheet("background: transparent;")
                l = QHBoxLayout(w)
                l.setContentsMargins(0, 0, 0, 0)
                e = QLineEdit(str(t))
                e.setFixedWidth(50)
                e.textChanged.connect(lambda txt, idx=i: self._upd_thr(idx, txt))
                l.addWidget(e)
                l.addWidget(QLabel("%"))
                d = QPushButton("✕")
                d.setFixedWidth(24)
                d.clicked.connect(lambda checked=False, idx=i: self._del_thr(idx))
                l.addWidget(d)
                l.addStretch()
                self.thr_layout.addWidget(w)

        def _add_thr(self):
            self.cfg["thresholds"].append(50)
            self._render_thresholds()
            self._save()

        def _del_thr(self, i):
            if len(self.cfg["thresholds"]) > 1:
                self.cfg["thresholds"].pop(i)
                self._render_thresholds()
                self._save()

        def _upd_thr(self, i, txt):
            try:
                self.cfg["thresholds"][i] = int(txt)
                self._save()
            except ValueError:
                pass

        def _on_opacity(self, v):
            self.op_label.setText(f"{v}%")
            self.cfg["dongle_opacity"] = v / 100
            self._save()

        def _save(self, *a):
            self.cfg["dongle_always_on_top"] = self.ontop_cb.isChecked()
            mode_idx = self.show_group.checkedId() - 100
            modes = ["always", "claude", "dev", "custom"]
            if 0 <= mode_idx < len(modes):
                self.cfg["show_mode"] = modes[mode_idx]
            config.save(self.cfg)

        def _refresh_loop(self):
            acc = monitor.get_account_identity()
            self.acc_name.setText(acc.get("account_name", "?"))
            self.acc_email.setText(acc.get("email", ""))
            self.acc_plan.setText(f"{acc.get('plan', '?')}")
            self._update_proxy_status()
            QTimer.singleShot(10000, self._refresh_loop)

        def _update_proxy_status(self):
            running = proxy.is_running()
            color = "#00ff88" if running else "#ff2244"
            age = ""
            try:
                d = json.loads(proxy.STATE_FILE)
                a = time.time() - d.get("_updated_at", 0)
                age = f"  ·  {_fmt_time(int(a))} atrás"
            except: pass
            text = f"Proxy: {'ativo' if running else 'inativo'}{age}"
            self.proxy_label.setText(text)
            self.proxy_label.setStyleSheet(f"font-size: 9px; color: {color};")

    def run(cfg):
        app = get_app()
        w = DongleWidget(cfg)
        w.show()
        app.exec()

    class Dashboard:
        def __init__(self, cfg):
            self.cfg = cfg
            get_app()
            self.root = DashboardWidget(cfg)

        def run(self):
            self.root.show()
