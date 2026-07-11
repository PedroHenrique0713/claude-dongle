import subprocess, json, time, sys, os
from pathlib import Path
from .utils import fmt_time as _fmt_time


def _win_toast(title, message):
    # Balloon nativo via PowerShell (sem dependência); título/texto via env p/
    # não sofrer com escaping. CREATE_NO_WINDOW evita a janela piscar.
    ps = ("[reflection.assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
          "$n=New-Object System.Windows.Forms.NotifyIcon;"
          "$n.Icon=[System.Drawing.SystemIcons]::Information;"
          "$n.BalloonTipTitle=$env:CM_TITLE;$n.BalloonTipText=$env:CM_MSG;"
          "$n.Visible=$true;$n.ShowBalloonTip(6000);Start-Sleep -Seconds 6;$n.Dispose()")
    env = dict(os.environ, CM_TITLE=title, CM_MSG=message)
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], env=env,
                     creationflags=0x08000000)


def send(title: str, message: str, urgency: str = "normal"):
    """Notificação de desktop cross-platform; nunca propaga erro."""
    try:
        if sys.platform == "darwin":
            t = title.replace('"', '\\"')
            m = message.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'display notification "{m}" with title "{t}"'],
                capture_output=True, timeout=5)
        elif sys.platform == "win32":
            _win_toast(title, message)
        else:
            subprocess.run(
                ["notify-send", "-a", "Claude Monitor", "-u", urgency, title, message],
                capture_output=True, timeout=5)
    except Exception:
        pass


def _weekly_series(usage: dict) -> list[dict]:
    """Um item por limite semanal — geral e CADA modelo scoped são séries
    independentes (o dongle/dashboard já os mostram separados). Colapsar no
    "pior" (usage['pct']) fazia a notificação rotulada 'semanal' reportar o
    número do Fable e silenciava o geral pela dedup compartilhada.

    tag: sufixo estável da chave de dedup (por métrica).
    fc_key: chave correspondente no dict usage['forecast'].
    """
    now = time.time()
    fallback_reset = usage.get("seconds_until_reset")

    def secs(epoch):
        return max(0, int(epoch - now)) if epoch else fallback_reset

    breakdown = usage.get("weekly_breakdown") or []
    if not breakdown:
        return [{"label": "Semana geral", "tag": "all", "pct": usage["pct"],
                 "secs": fallback_reset, "fc_key": "7d"}]
    out = []
    for w in breakdown:
        p = w.get("pct")
        if p is None:
            continue
        if w.get("kind") == "weekly_all":
            out.append({"label": "Semana geral", "tag": "all", "pct": p,
                        "secs": secs(w.get("reset")), "fc_key": "7d"})
        elif w.get("kind") == "weekly_scoped":
            model = w.get("model") or "modelo"
            out.append({"label": f"Semana {model}", "tag": model, "pct": p,
                        "secs": secs(w.get("reset")), "fc_key": f"7d:{model}"})
    return out


def check_telemetry(usage: dict, state: dict, flag_path: str) -> bool:
    """Avisa UMA vez quando o monitor fica sem dado novo por muito tempo
    (token expirado / API fora) — hoje a falha é totalmente silenciosa. O flag
    em disco reseta sozinho quando o dado volta, evitando spam.
    """
    limit_s = int(state.get("telemetry_stale_minutes", 60)) * 60
    healthy = usage.get("source") == "api" and not usage.get("stale")
    fp = Path(flag_path)
    st = {}
    if fp.exists():
        try:
            st = json.loads(fp.read_text())
        except (json.JSONDecodeError, OSError):
            st = {}
    now = time.time()

    if healthy:
        if st:
            try:
                fp.unlink()
            except OSError:
                pass
        return False

    if not st.get("since"):
        st["since"] = now
    lost_for = now - st["since"]
    age = usage.get("stale_age_seconds")
    if age is not None:  # dado stale carrega a idade real; usa a maior medida
        lost_for = max(lost_for, age)

    triggered = False
    if lost_for >= limit_s and not st.get("notified"):
        send("Monitor sem telemetria de uso",
             f"Sem dado novo há {_fmt_time(int(lost_for))} — o token pode ter "
             f"expirado ou a API está indisponível.", "normal")
        st["notified"] = True
        triggered = True
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(st))
    return triggered


def check_thresholds(usage: dict, state: dict, sent_path: str) -> bool:
    pct = usage["pct"]
    if pct is None:
        return False
    pct_5h = usage.get("pct_5h")
    sent_file = Path(sent_path)
    sent = set()
    if sent_file.exists():
        sent = set(json.loads(sent_file.read_text()))

    # As chaves carregam o epoch de reset da janela: cada janela nova começa
    # limpa e as chaves de janelas passadas são descartadas no save.
    w_epoch = usage.get("reset_7d_epoch") or 0
    s_epoch = usage.get("reset_5h_epoch") or 0
    thresholds = sorted(state["thresholds"])
    fc = usage.get("forecast") or {}
    forecast_on = state.get("forecast_notify", True) and not usage.get("stale")
    threshold_on = state.get("notify_on_threshold", True)
    limit_on = state.get("notify_on_limit", True)

    # Cada "balde" (sessão 5h, semana geral, semana por modelo) é uma série
    # independente. O rótulo abre TODO título para a notificação nunca ser
    # ambígua sobre a qual limite se refere, e o corpo fala só desse balde.
    buckets = []
    if pct_5h is not None:
        buckets.append({
            "label": "Sessão 5h", "pct": pct_5h,
            "secs": usage.get("seconds_until_reset_5h"),
            "prefix": f"s{s_epoch}:", "fc": fc.get("5h") or {}, "fc_floor": 50,
        })
    for s in _weekly_series(usage):
        buckets.append({
            "label": s["label"], "pct": s["pct"], "secs": s["secs"],
            "prefix": f"w{w_epoch}:{s['tag']}:",
            "fc": fc.get(s["fc_key"]) or {}, "fc_floor": 30,
        })

    triggered = False
    for b in buckets:
        label, bpct, secs, pref = b["label"], b["pct"], b["secs"], b["prefix"]
        reset = f"Reinicia em {_fmt_time(secs)}"

        # Cruzar vários thresholds de uma vez (1ª leitura da janela, ou volta de
        # um período desligado) dispara UMA notificação — a do maior cruzado —
        # em vez de N idênticas. Os menores só são marcados como já vistos.
        if threshold_on:
            crossed = [t for t in thresholds
                       if t < 100 and bpct >= t and f"{pref}{t}" not in sent]
            if crossed:
                for t in crossed:
                    sent.add(f"{pref}{t}")
                if bpct < 100:  # em 100%+ a notificação de limite abaixo já cobre
                    top = max(crossed)
                    send(f"{label} · {bpct:.0f}%", reset,
                         "critical" if top >= 95 else "normal")
                    triggered = True

        key = f"{pref}limit"
        if limit_on and bpct >= 100 and key not in sent:
            send(f"{label} · 100%", f"Limite atingido · {reset.lower()}",
                 "critical")
            sent.add(key)
            triggered = True

        # Previsão: no ritmo atual este balde estoura antes do reinício. Uma vez
        # por janela e só acima de um piso — no começo da janela a regressão é
        # ruidosa e dispararia alarme em todo burst inicial.
        f = b["fc"]
        key = f"{pref}forecast"
        if (forecast_on and f.get("overflow_before_reset")
                and b["fc_floor"] <= bpct < 100 and key not in sent):
            send(
                f"{label} · previsão de estouro",
                f"{bpct:.0f}% agora · +{f['rate_pph']:.1f} p.p./h · "
                f"estoura em {_fmt_time(f['eta_seconds'])}, "
                f"antes do reinício em {_fmt_time(secs)}",
                "critical"
            )
            sent.add(key)
            triggered = True

    sent = {k for k in sent
            if k.startswith(f"w{w_epoch}:") or k.startswith(f"s{s_epoch}:")}
    sent_file.parent.mkdir(parents=True, exist_ok=True)
    sent_file.write_text(json.dumps(sorted(sent)))
    return triggered
