import subprocess, json, time, sys, os
from pathlib import Path
from .utils import fmt_time as _fmt_time


def _win_toast(title, message):
    # Native balloon via PowerShell (no dependency); title/text via env vars to
    # avoid escaping issues. CREATE_NO_WINDOW keeps the console from flashing.
    ps = ("[reflection.assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
          "$n=New-Object System.Windows.Forms.NotifyIcon;"
          "$n.Icon=[System.Drawing.SystemIcons]::Information;"
          "$n.BalloonTipTitle=$env:CM_TITLE;$n.BalloonTipText=$env:CM_MSG;"
          "$n.Visible=$true;$n.ShowBalloonTip(6000);Start-Sleep -Seconds 6;$n.Dispose()")
    env = dict(os.environ, CM_TITLE=title, CM_MSG=message)
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], env=env,
                     creationflags=0x08000000)


def send(title: str, message: str, urgency: str = "normal"):
    """Cross-platform desktop notification; never propagates errors."""
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
                ["notify-send", "-a", "Claude Dongle", "-u", urgency, title, message],
                capture_output=True, timeout=5)
    except Exception:
        pass


def _weekly_series(usage: dict) -> list:
    """One item per weekly limit — the overall one and EACH scoped model are
    independent series (the dongle/dashboard already show them separately).
    Collapsing into the "worst" (usage['pct']) made a notification labeled
    'weekly' report one model's number and silenced the overall one through
    the shared dedup.

    tag: stable suffix of the dedup key (per metric).
    fc_key: matching key in the usage['forecast'] dict.
    """
    now = time.time()
    fallback_reset = usage.get("seconds_until_reset")

    def secs(epoch):
        return max(0, int(epoch - now)) if epoch else fallback_reset

    breakdown = usage.get("weekly_breakdown") or []
    if not breakdown:
        return [{"label": "Overall week", "tag": "all", "pct": usage["pct"],
                 "secs": fallback_reset, "fc_key": "7d"}]
    out = []
    for w in breakdown:
        p = w.get("pct")
        if p is None:
            continue
        if w.get("kind") == "weekly_all":
            out.append({"label": "Overall week", "tag": "all", "pct": p,
                        "secs": secs(w.get("reset")), "fc_key": "7d"})
        elif w.get("kind") == "weekly_scoped":
            model = w.get("model") or "model"
            out.append({"label": f"Week {model}", "tag": model, "pct": p,
                        "secs": secs(w.get("reset")), "fc_key": f"7d:{model}"})
    return out


def check_telemetry(usage: dict, state: dict, flag_path: str) -> bool:
    """Warn ONCE when the monitor has had no fresh data for too long (expired
    token / API down) — otherwise the failure is completely silent. The on-disk
    flag resets by itself when data comes back, avoiding spam.
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
    if age is not None:  # stale data carries its real age; use the larger measure
        lost_for = max(lost_for, age)

    triggered = False
    if lost_for >= limit_s and not st.get("notified"):
        send("No usage telemetry",
             f"No fresh data for {_fmt_time(int(lost_for))} — the token may have "
             f"expired or the API is unavailable.", "normal")
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

    # Keys carry the window's reset epoch: each new window starts clean and
    # keys from past windows are dropped on save.
    w_epoch = usage.get("reset_7d_epoch") or 0
    s_epoch = usage.get("reset_5h_epoch") or 0
    thresholds = sorted(state["thresholds"])
    fc = usage.get("forecast") or {}
    forecast_on = state.get("forecast_notify", True) and not usage.get("stale")
    threshold_on = state.get("notify_on_threshold", True)
    limit_on = state.get("notify_on_limit", True)

    # Each bucket (5h session, overall week, week per model) is an independent
    # series. The label opens EVERY title so a notification is never ambiguous
    # about which limit it refers to, and the body talks only about that bucket.
    buckets = []
    if pct_5h is not None:
        buckets.append({
            "label": "5h session", "pct": pct_5h,
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
        reset = f"Resets in {_fmt_time(secs)}"

        # Crossing several thresholds at once (first read of a window, or
        # coming back from a period offline) fires ONE notification — the
        # highest crossed — instead of N identical ones. The lower ones are
        # only marked as seen.
        if threshold_on:
            crossed = [t for t in thresholds
                       if t < 100 and bpct >= t and f"{pref}{t}" not in sent]
            if crossed:
                for t in crossed:
                    sent.add(f"{pref}{t}")
                if bpct < 100:  # at 100%+ the limit notification below covers it
                    top = max(crossed)
                    send(f"{label} · {bpct:.0f}%", reset,
                         "critical" if top >= 95 else "normal")
                    triggered = True

        key = f"{pref}limit"
        if limit_on and bpct >= 100 and key not in sent:
            send(f"{label} · 100%", f"Limit reached · {reset.lower()}",
                 "critical")
            sent.add(key)
            triggered = True

        # Forecast: at the current pace this bucket overflows before the reset.
        # Once per window and only above a floor — early in the window the
        # regression is noisy and would alarm on every initial burst.
        f = b["fc"]
        key = f"{pref}forecast"
        if (forecast_on and f.get("overflow_before_reset")
                and b["fc_floor"] <= bpct < 100 and key not in sent):
            send(
                f"{label} · overflow forecast",
                f"{bpct:.0f}% now · +{f['rate_pph']:.1f} pp/h · "
                f"overflows in {_fmt_time(f['eta_seconds'])}, "
                f"before the reset in {_fmt_time(secs)}",
                "critical"
            )
            sent.add(key)
            triggered = True

    sent = {k for k in sent
            if k.startswith(f"w{w_epoch}:") or k.startswith(f"s{s_epoch}:")}
    sent_file.parent.mkdir(parents=True, exist_ok=True)
    sent_file.write_text(json.dumps(sorted(sent)))
    return triggered
