import subprocess, json, os, time, sys, tempfile
from pathlib import Path
from contextlib import contextmanager
from .i18n import t as _t
from .utils import fmt_time as _fmt_time

try:  # POSIX only; Windows falls back to best-effort (no cross-process lock)
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


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


# ---------------------------------------------------------------- state file
# The dongle (every poll) and the systemd timer (every 10 min) are DIFFERENT
# processes sharing this file. Without a lock both read the same "not sent yet"
# state and both notify — that is half of the duplicate alerts. The whole
# read → decide → send → write cycle runs under an exclusive lock.

def _read_state(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, list):  # pre-cooldown format: a bare list of sent keys
        return {"keys": raw}
    return raw if isinstance(raw, dict) else {}


def _write_state(path: Path, st: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sent-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(st, f)
        os.replace(tmp, path)  # atomic: a reader never sees a half-written file
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@contextmanager
def _locked_state(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = None
    if fcntl is not None:
        try:
            lock = open(str(p) + ".lock", "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError:
            lock = None
    st = _read_state(p)
    try:
        yield st
        _write_state(p, st)
    finally:
        if lock is not None:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()
            except OSError:
                pass


def mute(sent_path, minutes: int):
    """Silence every usage notification for N minutes (0 = unmute now)."""
    with _locked_state(sent_path) as st:
        st["muted_until"] = time.time() + minutes * 60 if minutes else 0
        return st["muted_until"]


def muted_until(sent_path) -> float:
    """Epoch until which notifications are silenced (0 = not muted)."""
    st = _read_state(Path(sent_path))
    until = st.get("muted_until") or 0
    return until if until > time.time() else 0


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
        return [{"label": _t("n.week_all"), "tag": "all", "pct": usage["pct"],
                 "secs": fallback_reset, "fc_key": "7d"}]
    out = []
    for w in breakdown:
        p = w.get("pct")
        if p is None:
            continue
        if w.get("kind") == "weekly_all":
            out.append({"label": _t("n.week_all"), "tag": "all", "pct": p,
                        "secs": secs(w.get("reset")), "fc_key": "7d"})
        elif w.get("kind") == "weekly_scoped":
            model = w.get("model") or "model"
            out.append({"label": _t("n.week_model", model=model), "tag": model,
                        "pct": p, "secs": secs(w.get("reset")),
                        "fc_key": f"7d:{model}"})
    return out


def check_telemetry(usage: dict, state: dict, flag_path: str) -> bool:
    """Warn ONCE when the monitor has had no fresh data for too long (expired
    token / API down) — otherwise the failure is completely silent. The on-disk
    flag resets by itself when data comes back, avoiding spam.
    """
    if not state.get("notify_on_telemetry", True):
        return False
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
        send(_t("n.telemetry_title"),
             _t("n.telemetry_body", time=_fmt_time(int(lost_for))), "normal")
        st["notified"] = True
        triggered = True
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(st))
    return triggered


def _events(usage: dict, state: dict, sent: set) -> list:
    """Alerts this reading earns, as {title, body, urgency, keys}. Nothing is
    sent here: the caller aggregates so one poll produces ONE notification."""
    pct = usage["pct"]
    pct_5h = usage.get("pct_5h")
    # Keys carry the window's reset epoch: each new window starts clean and
    # keys from past windows are dropped on save.
    w_epoch = usage.get("reset_7d_epoch") or 0
    s_epoch = usage.get("reset_5h_epoch") or 0
    thresholds = sorted({int(t) for t in state["thresholds"] if 0 < int(t) < 100})
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
            "label": _t("n.session"), "pct": pct_5h,
            "secs": usage.get("seconds_until_reset_5h"),
            "prefix": f"s{s_epoch}:", "fc": fc.get("5h") or {}, "fc_floor": 50,
        })
    for s in _weekly_series(usage):
        buckets.append({
            "label": s["label"], "pct": s["pct"], "secs": s["secs"],
            "prefix": f"w{w_epoch}:{s['tag']}:",
            "fc": fc.get(s["fc_key"]) or {}, "fc_floor": 30,
        })

    events = []
    for b in buckets:
        label, bpct, secs, pref = b["label"], b["pct"], b["secs"], b["prefix"]
        reset = _t("n.resets_in", time=_fmt_time(secs))

        # Crossing several thresholds at once (first read of a window, or
        # coming back from a period offline) fires ONE notification — the
        # highest crossed — instead of N identical ones. The lower ones are
        # only marked as seen.
        if threshold_on:
            crossed = [t for t in thresholds
                       if bpct >= t and f"{pref}{t}" not in sent]
            if crossed:
                keys = [f"{pref}{t}" for t in crossed]
                if bpct < 100:  # at 100%+ the limit event below covers it
                    top = max(crossed)
                    events.append({
                        "title": _t("n.pct_title", label=label, pct=f"{bpct:.0f}"),
                        "body": reset,
                        "urgency": "critical" if top >= 95 else "normal",
                        "keys": keys})
                else:
                    events.append({"title": None, "body": None, "keys": keys})

        key = f"{pref}limit"
        if limit_on and bpct >= 100 and key not in sent:
            events.append({"title": _t("n.limit_title", label=label),
                           "body": _t("n.limit_body", time=_fmt_time(secs)),
                           "urgency": "critical", "keys": [key]})

        # Forecast: at the current pace this bucket overflows before the reset.
        # Once per window and only above a floor — early in the window the
        # regression is noisy and would alarm on every initial burst.
        f = b["fc"]
        key = f"{pref}forecast"
        if (forecast_on and f.get("overflow_before_reset")
                and b["fc_floor"] <= bpct < 100 and key not in sent):
            events.append({
                "title": _t("n.forecast_title", label=label),
                "body": _t("n.forecast_body", pct=f"{bpct:.0f}",
                           rate=f"{f['rate_pph']:.1f}",
                           eta=_fmt_time(f["eta_seconds"]),
                           reset=_fmt_time(secs)),
                "urgency": "critical", "keys": [key]})
    return events


def _adopt_keys(keys, w_epoch, s_epoch) -> set:
    """Re-stamp keys written before reset epochs were rounded to the minute.

    The same window used to be keyed as X on one reading and X-1 on the next,
    so every flip looked like a brand-new window and re-fired the alerts. The
    rounding fixed that going forward; this adopts what is already on disk so
    upgrading doesn't produce one last spurious round."""
    out = set()
    for k in keys:
        prefix, sep, rest = str(k).partition(":")
        if not sep or prefix[:1] not in ("w", "s"):
            out.add(k)
            continue
        try:
            epoch = int(prefix[1:])
        except ValueError:
            out.add(k)
            continue
        target = w_epoch if prefix[0] == "w" else s_epoch
        if target and abs(epoch - target) <= 60:
            epoch = target
        out.add(f"{prefix[0]}{epoch}:{rest}")
    return out


def check_thresholds(usage: dict, state: dict, sent_path: str) -> bool:
    if usage.get("pct") is None:
        return False
    w_epoch = usage.get("reset_7d_epoch") or 0
    s_epoch = usage.get("reset_5h_epoch") or 0
    cooldown = max(0, int(state.get("notify_cooldown_minutes", 15))) * 60
    now = time.time()

    with _locked_state(sent_path) as st:
        sent = _adopt_keys(st.get("keys") or [], w_epoch, s_epoch)
        events = _events(usage, state, sent)
        for e in events:  # a key is spent once it is decided, sent or not
            sent.update(e["keys"])
        speak = [e for e in events if e.get("title")]

        triggered = False
        muted = (st.get("muted_until") or 0) > now
        # The cooldown paces routine alerts; a critical one (limit reached,
        # overflow forecast) is never held back — it is the alert that matters
        # and the dedup already caps it at one per window.
        urgent = any(e["urgency"] == "critical" for e in speak)
        paced = urgent or now - (st.get("last_sent") or 0) >= cooldown
        # One notification per reading. Several buckets crossing at the same
        # time used to mean several pop-ups; they now share one, and the
        # cooldown keeps consecutive readings from stacking up.
        if speak and not muted and paced:
            if len(speak) == 1:
                send(speak[0]["title"], speak[0]["body"], speak[0]["urgency"])
            else:
                urgency = ("critical" if any(e["urgency"] == "critical" for e in speak)
                           else "normal")
                send(_t("n.multi_title"),
                     "\n".join(f"{e['title']} · {e['body']}" for e in speak), urgency)
            st["last_sent"] = now
            triggered = True

        st["keys"] = sorted(k for k in sent
                            if k.startswith(f"w{w_epoch}:") or k.startswith(f"s{s_epoch}:"))
    return triggered
