"""Usage time series + burn rate + overflow forecast.

Snapshots come in through the single funnel (monitor.calc_usage). The PK
(metric, window_epoch, ts) makes writes idempotent: the dongle (30s), the
dashboard (5s) and the CLI may all try to record the same API sample and only
the first INSERT lands. WAL + busy_timeout cover the multi-process case
(the service dies when idle and is reborn with every terminal).
"""
import sqlite3, time, threading

from . import config

DB_PATH = config.CONFIG_DIR / "history.db"
MIN_RATE_PPH = 0.2  # below this the pace is "flat": an ETA would be noise
CLOCK_SKEW_S = 60

# One connection per thread: the projects parser runs in its own thread and a
# single sqlite connection can't be used by two threads at once. WAL allows N
# connections (1 writer + readers) over the same file.
_local = threading.local()
_gc_done = False
_last_written = {}  # metric -> ts; saves redundant INSERTs on every 5s refresh


def _conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is not None:
        return c
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=5, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        " metric TEXT NOT NULL,"          # '5h' | '7d' | '7d:<model>'
        " window_epoch INTEGER NOT NULL,"  # window's reset epoch (0 = unknown)
        " ts INTEGER NOT NULL,"            # when the DATA was fetched (fetched_at)
        " pct REAL NOT NULL,"
        " account TEXT NOT NULL DEFAULT '',"
        " source TEXT NOT NULL DEFAULT 'api',"
        " PRIMARY KEY (metric, window_epoch, ts)"
        ") WITHOUT ROWID")
    c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts)")
    c.commit()
    _local.conn = c
    return c


def _metrics_from(usage: dict) -> list:
    """(metric, window_epoch, pct) for each metric present in calc_usage's dict."""
    out = []
    if usage.get("pct_5h") is not None:
        out.append(("5h", usage.get("reset_5h_epoch") or 0, float(usage["pct_5h"])))
    breakdown = usage.get("weekly_breakdown")
    if breakdown:
        for w in breakdown:
            if w.get("pct") is None:
                continue
            if w.get("kind") == "weekly_all":
                metric = "7d"
            elif w.get("kind") == "weekly_scoped":
                metric = f"7d:{w.get('model') or 'scoped'}"
            else:
                continue
            out.append((metric, w.get("reset") or 0, float(w["pct"])))
    elif usage.get("pct_7d") is not None:
        # Source without a breakdown (proxy/old cache): record the effective weekly.
        out.append(("7d", usage.get("reset_7d_epoch") or 0, float(usage["pct_7d"])))
    return out


def record(usage: dict) -> None:
    """Records one snapshot per metric. Idempotent; never raises."""
    if usage.get("source") == "none" or not usage.get("data_ts"):
        return
    ts = int(usage["data_ts"])
    account = usage.get("account") or ""
    source = usage.get("source") or "api"
    rows = [(metric, epoch, ts, pct, account, source)
            for metric, epoch, pct in _metrics_from(usage)
            if _last_written.get(metric) != ts]
    if not rows:
        return
    try:
        c = _conn()
        c.executemany("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?)", rows)
        c.commit()
        for metric, *_ in rows:
            _last_written[metric] = ts
    except sqlite3.Error as e:
        print(f"history.record: {e}", flush=True)


def series(metric: str, window_epoch: int, account: str = "") -> list:
    """(ts, pct) points of the current window, in chronological order."""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT ts, pct FROM snapshots"
            " WHERE metric=? AND window_epoch=? AND account=? AND ts<=?"
            " ORDER BY ts ASC",
            (metric, window_epoch, account or "",
             int(time.time()) + CLOCK_SKEW_S)).fetchall()
        return [(int(t), float(p)) for t, p in rows]
    except sqlite3.Error:
        return []


def burn_rate(points, now=None, lookback_s=3600, min_points=3, min_span_s=600):
    """Percentage points per HOUR (simple linear regression), or None.

    Regression instead of a delta between endpoints: with a sample every
    ~300s, one noisy point (or a small pct dip) doesn't flip the sign.
    """
    now = time.time() if now is None else now
    pts = [(t, y) for t, y in points if t >= now - lookback_s]
    if len(pts) < min_points:
        return None
    t0 = pts[0][0]
    if pts[-1][0] - t0 < min_span_s:
        return None
    xs = [(t - t0) / 3600 for t, _ in pts]
    ys = [y for _, y in pts]
    n = len(pts)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def forecast(pct_latest, latest_ts, rate_pph, seconds_until_reset, now=None):
    """ETA to 100% at the current pace, and whether it overflows before the
    window's reset.

    With no upward trend (rate <= MIN_RATE_PPH) there is no overflow forecast,
    even at 100% already — there the limit notification does the warning, not
    a "forecast" of something that already happened (and stopped).
    """
    now = time.time() if now is None else now
    out = {"rate_pph": rate_pph, "eta_seconds": None, "overflow_before_reset": None}
    if rate_pph is None or rate_pph <= MIN_RATE_PPH:
        return out
    pct_now = pct_latest + rate_pph * (now - latest_ts) / 3600
    out["eta_seconds"] = (0 if pct_now >= 100
                          else max(0, int((100 - pct_now) / rate_pph * 3600)))
    if seconds_until_reset is not None:
        out["overflow_before_reset"] = out["eta_seconds"] < seconds_until_reset
    return out


def attach_forecasts(usage: dict, cfg: dict) -> dict:
    """{metric: forecast} for each metric in the usage dict. Never raises."""
    if usage.get("source") == "none":
        return {}
    try:
        _gc_once(cfg)
        lookback_s = int(cfg.get("burn_lookback_minutes", 60)) * 60
        min_points = int(cfg.get("burn_min_points", 3))
        account = usage.get("account") or ""
        now = time.time()
        fallback_reset = {"5h": usage.get("seconds_until_reset_5h"),
                          "7d": usage.get("seconds_until_reset")}
        out = {}
        for metric, epoch, pct in _metrics_from(usage):
            pts = series(metric, epoch, account)
            rate = burn_rate(pts, now=now, lookback_s=lookback_s,
                             min_points=min_points)
            latest_ts = pts[-1][0] if pts else int(now)
            reset_s = max(0, int(epoch - now)) if epoch else fallback_reset.get(metric)
            fc = forecast(pct, latest_ts, rate, reset_s, now=now)
            fc["points"] = len(pts)
            # 'alert' = RELEVANT overflow (what lights the visual warning /
            # notification): a predicted overflow AND the bucket already past a
            # floor. Without the floor, a short-term burn rate on a low pct
            # (e.g. a model at 4%) projects an overflow days away and raises a
            # non-actionable alarm.
            floor = 50 if metric == "5h" else 30
            fc["alert"] = bool(fc.get("overflow_before_reset")) and pct >= floor
            out[metric] = fc
        return out
    except Exception as e:
        print(f"history.attach_forecasts: {e}", flush=True)
        return {}


def _gc_once(cfg: dict) -> None:
    global _gc_done
    if _gc_done:
        return
    _gc_done = True
    days = int(cfg.get("history_retention_days", 21))
    try:
        c = _conn()
        c.execute("DELETE FROM snapshots WHERE ts < ?",
                  (int(time.time()) - days * 86400,))
        c.commit()
    except sqlite3.Error:
        pass
