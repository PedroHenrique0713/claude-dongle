import subprocess, time, math, sys

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
                         QLinearGradient, QPainterPath, QRegion)

import monitor, config, notifier, usage_api
from utils import (color as _color, fmt_time as _fmt_time,
                   FG, FG2, FG3, ORANGE, RED, UI_FONT)

SENT_PATH = str(config.CONFIG_DIR / "sent_thresholds.json")
TELEMETRY_PATH = str(config.CONFIG_DIR / "telemetry_state.json")

DONGLE_W, DONGLE_H = 216, 36
DONGLE_R = 18
PAD = 14
BAR_Y = 27.0
CLICK_SLOP = 8  # px manhattan: abaixo disso o release conta como clique
HOT_RESET_S = 30 * 60  # sessão resetando em menos que isso: countdown ganha destaque
VIS_CHECK_MS = 5000  # gatilho de visibilidade (abrir/fechar terminal reage rápido)

# comm dos processos que caracterizam "trabalhando em dev" (modo show_mode=dev)
DEV_PROCS = ["code", "cursor", "ptyxis", "gnome-terminal", "kgx", "konsole",
             "alacritty", "kitty", "wezterm", "tilix", "windowsterminal",
             "iterm", "terminal"]


def _list_processes():
    """Nomes de processos rodando, em minúsculo. Vazio se indisponível.
    Cross-platform: tasklist no Windows, ps no Linux/macOS."""
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"], text=True, timeout=3)
            return [ln.split('","')[0].lstrip('"').lower()
                    for ln in out.splitlines() if ln]
        out = subprocess.check_output(["ps", "-eo", "comm="], text=True, timeout=3)
        # comm pode vir com caminho no macOS: fica só com o basename
        return [l.strip().rsplit("/", 1)[-1].lower() for l in out.splitlines()]
    except Exception:
        return []


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

        self._restore_position()

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
        self._reset_5h_epoch = None  # epoch p/ countdown ao vivo (recomputado no paint)
        self._reset_w_epoch = None
        self._overflow = False    # algum balde com previsão de estouro antes do reset
        self._critical = False    # algum pct >= 95: borda pulsa
        self._hidden = False
        self._idle_secs = 0
        self._ps_cache = None     # (t_monotonic, visible) p/ não rodar ps 2x/5s

        self._font_label = QFont(UI_FONT, 7)
        self._font_value_5h = QFont(UI_FONT, 13, QFont.Weight.Bold)
        self._font_value_7d = QFont(UI_FONT, 9, QFont.Weight.DemiBold)
        self._font_reset = QFont(UI_FONT, 8)
        self._font_reset_hot = QFont(UI_FONT, 8, QFont.Weight.Bold)

        self._setup_timer()
        self.show()
        self.raise_()

    def _apply_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, DONGLE_W, DONGLE_H), DONGLE_R, DONGLE_R)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _pos_on_screen(self, x, y):
        # a posição arrastada precisa cair (com folga visível) em alguma tela
        # conectada — senão o dongle sumiria fora da área após trocar de monitor
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
        # Visibilidade num timer próprio, mais ágil que o poll de dados
        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._tick_visibility)
        self._vis_timer.start(VIS_CHECK_MS)
        # Animação: countdown ao vivo (1s) e pulso da borda quando crítico (~90ms,
        # ajustado no poll conforme o estado)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim)
        self._anim_timer.start(1000)
        self.poll()

    def _on_anim(self):
        if not self._hidden:
            self.update()

    def _tick_visibility(self):
        was_hidden = self._hidden
        self._update_display()
        if was_hidden and not self._hidden:
            self._idle_secs = 0
            self.poll()  # reapareceu: dado fresco na hora
            return
        if not self._hidden:
            self._idle_secs = 0
            return
        # Escondido: sem dev tools abertos o serviço não tem por que viver.
        # O hook do bashrc ressuscita no próximo terminal (0 = nunca sair).
        quit_min = self.cfg.get("idle_quit_minutes", 10)
        if quit_min:
            self._idle_secs += VIS_CHECK_MS / 1000
            if self._idle_secs >= quit_min * 60:
                print(f"[dongle] idle há {quit_min}min sem dev tools — encerrando", flush=True)
                QApplication.quit()

    def _compute_visible(self):
        mode = self.cfg.get("show_mode", "always")
        if mode == "always":
            return True
        # poll (dados) e _vis_timer chamam a cada 5s cada; cachear o ps por 4s
        # evita rodar o subprocess duas vezes por ciclo.
        now = time.monotonic()
        if self._ps_cache and now - self._ps_cache[0] < 4:
            return self._ps_cache[1]
        names = {"claude": ["claude"], "dev": DEV_PROCS,
                 "custom": self.cfg.get("show_processes", [])}.get(mode, [])
        visible = False
        if names:
            # match por prefixo (o comm do Linux trunca em 15 chars); nunca
            # substring no blob inteiro ("code" casaria "opencode")
            procs = _list_processes()
            names = [n.lower() for n in names]
            visible = any(p.startswith(n) for p in procs for n in names)
        self._ps_cache = (now, visible)
        return visible

    def _update_display(self):
        visible = self._compute_visible()
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
            if self._hidden:
                return  # sem dev tools abertos: não gasta chamada de API
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
            self._reset_5h_epoch = u.get("reset_5h_epoch")
            self._reset_w_epoch = u.get("reset_7d_epoch")
            fcs = u.get("forecast") or {}
            self._overflow = (not self._stale) and any(
                v.get("overflow_before_reset") for v in fcs.values())
            pcts = [p for p in (self._s_pct, self._w_all, self._scoped_pct)
                    if p is not None]
            self._critical = (not self._stale) and any(p >= 95 for p in pcts)
            # pulso rápido só quando crítico/estouro; senão 1s só p/ o countdown
            self._anim_timer.setInterval(
                90 if (self._critical or self._overflow) else 1000)
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
        # countdown ao vivo: recomputa do epoch se houver, senão usa o valor fixo
        if epoch:
            return max(0, int(epoch - time.time()))
        return fallback

    def _update_tooltip(self):
        src = {"api": "API oficial", "none": "sem dado"}.get(self._source, self._source)
        lines = [f"Fonte: {src}" + (" · dado antigo" if self._stale else "")]
        if self._s_pct is not None:
            lines.append(f"Sessão 5h: {self._s_pct:.0f}% · reinicia em {_fmt_time(self._reset_5h)}")
        if self._w_all is not None:
            lines.append(f"Semana geral: {self._w_all:.0f}% · reinicia em {_fmt_time(self._reset_w)}")
        if self._scoped_pct is not None:
            lines.append(f"Semana {self._scoped_name}: {self._scoped_pct:.0f}%")
        if self._overflow:
            lines.append("⚠ no ritmo atual, estoura antes do reset")
        lines.append("clique: abrir painel · meio: atualizar agora")
        self.setToolTip("\n".join(lines))

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
        # Borda pulsante: vermelha quando algum limite passou de 95%, âmbar
        # quando há previsão de estouro — aviso de relance sem poluir os 216×36.
        if self._critical or self._overflow:
            pulse = (math.sin(time.monotonic() * 5) + 1) / 2  # 0..1
            edge = QColor(RED if self._critical else ORANGE)
            edge.setAlpha(int(150 + 105 * pulse))
            p.setPen(QPen(edge, 1.5 + 0.8 * pulse))
        else:
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

        # Countdown do reset da sessão (ao vivo: recomputa do epoch a cada paint)
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
        dragged = self._dragging  # só o botão esquerdo seta _dragging no move
        self._press_pos = None
        self._dragging = False
        if dragged:  # arrasto real: gruda na borda e persiste (sobrevive ao idle-kill)
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
        # Arrastou pra perto de uma borda da tela atual → gruda no canto.
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
        # Clique do meio: ignora o cache e busca dado fresco na hora.
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
