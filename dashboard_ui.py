import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import monitor, config
from utils import color, fmt_time, RED, BG, BG2, BG3, FG, FG2, FG3, SEP, ACCENT

from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QFrame, QPushButton,
                             QSlider, QRadioButton, QButtonGroup, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QFont

REFRESH_MS = 5000
SOURCE_LABELS = {"api": "API oficial", "proxy": "proxy", "jobs": "estimativa local"}
SHOW_MODES = [("Sempre visível", "always"),
              ("Só com Claude Code", "claude"),
              ("Só com VS Code / terminal", "dev"),
              ("Processos específicos", "custom")]


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def _qss():
    return f"""
    QWidget {{ font-family: Cantarell; color: {FG}; }}
    #dashRoot {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QPushButton {{
        background: {BG3}; color: {FG}; border: none;
        border-radius: 6px; padding: 6px 18px; font-size: 12px;
    }}
    QPushButton:hover {{ background: #464646; }}
    QPushButton:pressed {{ background: {BG2}; }}
    QPushButton[kind="ghost"] {{ background: transparent; color: {ACCENT}; padding: 6px 10px; }}
    QPushButton[kind="ghost"]:hover {{ background: {_rgba(ACCENT, 26)}; }}
    QPushButton[kind="danger"] {{ background: transparent; color: {RED}; padding: 6px 12px; }}
    QPushButton[kind="danger"]:hover {{ background: {_rgba(RED, 30)}; }}
    QPushButton[kind="icon"] {{
        background: transparent; color: {FG2}; padding: 2px 4px; font-size: 11px;
    }}
    QPushButton[kind="icon"]:hover {{ background: {BG3}; color: {FG}; }}
    QLineEdit {{
        background: {BG3}; color: {FG}; border: 1px solid transparent;
        border-radius: 6px; padding: 3px 4px; font-size: 12px;
        selection-background-color: {ACCENT};
    }}
    QLineEdit:focus {{ border-color: {ACCENT}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {BG3}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 16px; height: 16px; margin: -6px 0;
        border-radius: 8px; background: #e8e8e8;
    }}
    QSlider::handle:horizontal:hover {{ background: #ffffff; }}
    QRadioButton {{ spacing: 10px; font-size: 12px; color: {FG}; background: transparent; }}
    QRadioButton::indicator {{
        width: 14px; height: 14px; border-radius: 8px;
        border: 1px solid #5a5a5a; background: transparent;
    }}
    QRadioButton::indicator:hover {{ border-color: #7a7a7a; }}
    QRadioButton::indicator:checked {{
        width: 6px; height: 6px; border: 5px solid {ACCENT};
        border-radius: 8px; background: {FG};
    }}
    """


class UsageBar(QWidget):
    """Thin fully-rounded bar; trough + severity-colored fill, hand painted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setMinimumWidth(120)
        self._pct = None
        self._color = QColor(FG3)

    def set_value(self, pct, color_hex):
        self._pct = pct
        self._color = QColor(color_hex)
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
        p.end()


class UsageRow(QWidget):
    """Label + big percent + bar + reset countdown for one rate limit."""

    def __init__(self, label, compact=False, parent=None):
        super().__init__(parent)
        self._pct_size = 15 if compact else 22
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.lbl = QLabel(label)
        self.lbl.setStyleSheet(
            f"color: {FG2}; font-size: {'11px' if compact else '12px'};")
        top.addWidget(self.lbl, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        self.pct = QLabel("--")
        self._set_pct_color(FG3)
        top.addWidget(self.pct, 0, Qt.AlignmentFlag.AlignBottom)
        box.addLayout(top)

        self.bar = UsageBar()
        box.addWidget(self.bar)

        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color: {FG3}; font-size: 10px;")
        self.sub.hide()
        box.addWidget(self.sub)

    def _set_pct_color(self, c):
        self.pct.setStyleSheet(
            f"color: {c}; font-size: {self._pct_size}px; font-weight: 700;")

    def set_data(self, pct, seconds, stale):
        if pct is None:
            self.pct.setText("--")
            self._set_pct_color(FG3)
            self.bar.set_value(None, FG3)
            self.sub.hide()
            return
        c = FG3 if stale else color(pct)
        self.pct.setText(f"{pct:.0f}%")
        self._set_pct_color(c)
        self.bar.set_value(pct, c)
        if seconds is not None:
            self.sub.setText(f"reinicia em {fmt_time(seconds)}")
            self.sub.show()
        else:
            self.sub.hide()


class DashboardWidget(QWidget):
    def __init__(self, cfg: dict, dongle=None):
        super().__init__()
        self.cfg = cfg
        self.dongle = dongle
        self._scoped_rows = {}

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
        self.adjustSize()

    # ---- construction -----------------------------------------------------

    def _section(self, text):
        l = QLabel(text.upper())
        f = QFont("Cantarell", 8, QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        l.setFont(f)
        l.setStyleSheet(f"color: {FG2};")
        return l

    def _sep(self):
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {SEP};")
        return f

    def _section_break(self, main, title):
        main.addSpacing(16)
        main.addWidget(self._sep())
        main.addSpacing(14)
        main.addWidget(self._section(title))
        main.addSpacing(10)

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 22, 24, 22)
        main.setSpacing(0)

        # Account header
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.acc_name = QLabel("—")
        self.acc_name.setStyleSheet("font-size: 14px; font-weight: 600;")
        head.addWidget(self.acc_name)
        head.addStretch()
        self.acc_plan = QLabel("")
        self.acc_plan.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        head.addWidget(self.acc_plan, 0, Qt.AlignmentFlag.AlignBottom)
        main.addLayout(head)
        self.acc_email = QLabel("")
        self.acc_email.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        main.addWidget(self.acc_email)

        # Usage (the star)
        main.addSpacing(16)
        main.addWidget(self._section("Uso"))
        main.addSpacing(10)
        self.bars_box = QVBoxLayout()
        self.bars_box.setContentsMargins(0, 0, 0, 0)
        self.bars_box.setSpacing(13)
        self.row_5h = UsageRow("Sessão (5h)")
        self.row_7d = UsageRow("Semana", compact=True)
        self.bars_box.addWidget(self.row_5h)
        self.bars_box.addWidget(self.row_7d)
        main.addLayout(self.bars_box)
        main.addSpacing(10)
        self.meta = QLabel("")
        self.meta.setStyleSheet(f"color: {FG3}; font-size: 11px;")
        main.addWidget(self.meta)

        # Dongle
        self._section_break(main, "Dongle")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        op_lbl = QLabel("Opacidade")
        op_lbl.setStyleSheet("font-size: 12px;")
        row.addWidget(op_lbl)
        row.addSpacing(12)
        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(30, 100)
        self.op_slider.setValue(int(self.cfg.get("dongle_opacity", 0.85) * 100))
        self.op_slider.valueChanged.connect(self._on_opacity)
        row.addWidget(self.op_slider, 1)
        self.op_label = QLabel(f"{self.op_slider.value()}%")
        self.op_label.setStyleSheet(f"color: {FG2}; font-size: 11px;")
        self.op_label.setFixedWidth(38)
        self.op_label.setAlignment(Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.op_label)
        main.addLayout(row)

        # Visibility
        self._section_break(main, "Visibilidade")
        self.show_group = QButtonGroup(self)
        current = self.cfg.get("show_mode", "always")
        for i, (text, val) in enumerate(SHOW_MODES):
            rb = QRadioButton(text)
            rb.setChecked(current == val)
            self.show_group.addButton(rb, i)
            main.addWidget(rb)
            if i < len(SHOW_MODES) - 1:
                main.addSpacing(6)
        self.show_group.idToggled.connect(self._on_mode)

        # Notification thresholds
        self._section_break(main, "Notificações")
        self.thr_grid = QGridLayout()
        self.thr_grid.setContentsMargins(0, 0, 0, 0)
        self.thr_grid.setHorizontalSpacing(10)
        self.thr_grid.setVerticalSpacing(8)
        main.addLayout(self.thr_grid)
        self._render_thresholds()
        main.addSpacing(6)
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+ Adicionar")
        add_btn.setProperty("kind", "ghost")
        add_btn.clicked.connect(self._add_thr)
        add_row.addWidget(add_btn)
        add_row.addStretch()
        main.addLayout(add_row)

        # Actions
        main.addSpacing(22)
        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        quit_btn = QPushButton("Sair do monitor")
        quit_btn.setProperty("kind", "danger")
        quit_btn.clicked.connect(QApplication.quit)
        btns.addWidget(quit_btn)
        btns.addStretch()
        close_btn = QPushButton("Fechar")
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
        stale = u.get("stale", False)
        now = time.time()

        self.acc_name.setText(u.get("account") or "—")
        self.acc_plan.setText(u.get("plan") or "")
        self.acc_email.setText(u.get("email") or "")

        pct_5h = u.get("pct_5h")
        self.row_5h.setVisible(pct_5h is not None)
        self.row_5h.set_data(pct_5h, u.get("seconds_until_reset_5h"), stale)

        def until(epoch, fallback=None):
            if epoch:
                return max(0, int(epoch - now))
            return fallback

        breakdown = u.get("weekly_breakdown") or []
        general = next((w for w in breakdown if w.get("kind") == "weekly_all"), None)
        if general:
            self.row_7d.set_data(general.get("pct"),
                                 until(general.get("reset"),
                                       u.get("seconds_until_reset")), stale)
        else:
            self.row_7d.set_data(u.get("pct_7d", u.get("pct")),
                                 u.get("seconds_until_reset"), stale)

        seen = set()
        for w in breakdown:
            if w.get("kind") != "weekly_scoped":
                continue
            model = w.get("model") or "por modelo"
            seen.add(model)
            row = self._scoped_rows.get(model)
            if row is None:
                row = UsageRow(f"Semana · {model}", compact=True)
                self._scoped_rows[model] = row
                self.bars_box.addWidget(row)
            row.set_data(w.get("pct"), until(w.get("reset")), stale)
        for model in list(self._scoped_rows):
            if model not in seen:
                self._scoped_rows.pop(model).deleteLater()

        self.meta.setText(self._meta_text(u))

    def _meta_text(self, u):
        parts = [SOURCE_LABELS.get(u.get("source"), u.get("source") or "?")]
        if u.get("stale"):
            age = u.get("proxy_age_seconds")
            parts.append(f"dado antigo · há {fmt_time(age)}" if age is not None
                         else "dado antigo")
        act = u.get("active_sessions") or 0
        if act:
            parts.append("1 sessão ativa" if act == 1 else f"{act} sessões ativas")
        if u.get("overage_status") == "enabled":
            parts.append("uso extra ativo")
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
        while self.thr_grid.count():
            w = self.thr_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, t in enumerate(self.cfg.get("thresholds", [])):
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            e = QLineEdit(str(t))
            e.setFixedWidth(42)
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.textChanged.connect(lambda txt, idx=i: self._upd_thr(idx, txt))
            lay.addWidget(e)
            pc = QLabel("%")
            pc.setStyleSheet(f"color: {FG2}; font-size: 11px;")
            lay.addWidget(pc)
            rm = QPushButton("✕")
            rm.setProperty("kind", "icon")
            rm.setFixedWidth(24)
            rm.clicked.connect(lambda checked=False, idx=i: self._del_thr(idx))
            lay.addWidget(rm)
            lay.addStretch()
            self.thr_grid.addWidget(cell, i // 4, i % 4)

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
