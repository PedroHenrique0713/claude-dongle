import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from . import history
from . import usage_api
from .utils import availability

CLAUDE_JSON = Path.home() / ".claude" / ".claude.json"
_prev_identity = None


def read_sessions(claude_dir: str) -> list:
    sess_dir = Path(claude_dir) / "sessions"
    if not sess_dir.exists():
        return []
    sessions = []
    for f in sorted(sess_dir.iterdir()):
        if not f.name.endswith(".json"):
            continue
        try:
            data = json.loads(f.read_text())
            sessions.append({
                "pid": data.get("pid"),
                "status": data.get("status", "unknown"),
                "version": data.get("version", ""),
                "cwd": data.get("cwd", ""),
                "started_at": data.get("startedAt", 0),
                "name": data.get("name", ""),
            })
        except json.JSONDecodeError:
            continue
    return sessions


def _active_token_tier():
    """(subscriptionType, rateLimitTier) of the ACTIVE account, read from the
    stored token — more current than oauthAccount, which Claude Code is slow
    to rewrite after an account switch."""
    o = usage_api.claude_oauth()
    return o.get("subscriptionType"), o.get("rateLimitTier")


def get_account_identity() -> dict:
    info = {"account_name": None, "org_name": None, "plan": None, "email": None,
            "uuid": None, "identity_stale": False}
    try:
        data = json.loads(CLAUDE_JSON.read_text())
        oa = data.get("oauthAccount", {})
        info["account_name"] = oa.get("displayName") or oa.get("organizationName") or oa.get("emailAddress", "default")
        info["org_name"] = oa.get("organizationName")
        info["plan"] = oa.get("organizationType") or oa.get("organizationRateLimitTier", "?")
        info["email"] = oa.get("emailAddress")
        info["uuid"] = oa.get("accountUuid", "")
        # The ACTIVE account comes from the token. If the token's tier diverges
        # from oauthAccount, oauthAccount is STALE (an account switch Claude
        # Code hasn't rewritten yet) → the old name/email can't be trusted;
        # the real plan comes from the token.
        sub, tier = _active_token_tier()
        info["tier"] = tier  # token tier: identifies the active account for the cache
        oa_tiers = {oa.get("organizationRateLimitTier"), oa.get("userRateLimitTier")}
        if tier and tier not in oa_tiers:
            info["identity_stale"] = True
            info["plan"] = sub or tier
    except (OSError, json.JSONDecodeError):
        pass
    return info


def detect_account_change():
    global _prev_identity
    cur = get_account_identity()
    name = cur.get("account_name")
    if _prev_identity is None:
        _prev_identity = cur
        return False, name
    changed = (
        cur.get("uuid") != _prev_identity.get("uuid")
        or cur.get("account_name") != _prev_identity.get("account_name")
        or cur.get("email") != _prev_identity.get("email")
        or cur.get("identity_stale") != _prev_identity.get("identity_stale")
    )
    _prev_identity = cur
    return changed, name


def calc_usage(state: dict) -> dict:
    now = datetime.now(timezone.utc)
    now_ts = time.time()
    # Manual fallback for the weekly reset — only used when the API never gave
    # a real resets_at. Unconfigured (the default): no guess, the UI shows "--".
    last_reset = _last_reset(state.get("reset_day"), state.get("reset_time"),
                             state.get("reset_timezone"))
    next_reset = last_reset + timedelta(days=7) if last_reset else None
    seconds_until_reset = (int((next_reset - now).total_seconds())
                           if next_reset else None)
    seconds_until_reset_5h = None

    sessions = read_sessions(state["claude_dir"])
    account = get_account_identity()
    account_changed, _ = detect_account_change()

    # Cache account key = uuid + token tier. The tier changes on an account
    # switch even while oauthAccount (uuid) is stale, so the previous account's
    # cached usage never leaks into the new one.
    acct_key = account.get("uuid") or ""
    if account.get("tier"):
        acct_key = f"{acct_key}:{account['tier']}"
    api_data = usage_api.fetch(state.get("api_poll_interval", 60), account=acct_key)

    stale = False
    scope_7d = None
    weekly_breakdown = None
    reset_7d_epoch = None
    reset_5h_epoch = None
    data_ts = None

    if api_data and api_data.get("pct_7d") is not None:
        pct_7d = round(api_data["pct_7d"], 1)
        pct_5h = round(api_data["pct_5h"], 1) if api_data.get("pct_5h") is not None else None
        reset_7d_epoch = api_data.get("reset_7d")
        reset_5h_epoch = api_data.get("reset_5h")
        if reset_7d_epoch:
            next_reset = datetime.fromtimestamp(reset_7d_epoch, tz=timezone.utc)
            seconds_until_reset = int((next_reset - now).total_seconds())
        if reset_5h_epoch:
            seconds_until_reset_5h = max(0, int(reset_5h_epoch - now_ts))
        source = "api"
        stale = api_data.get("stale", False)
        scope_7d = api_data.get("pct_7d_scope")
        weekly_breakdown = api_data.get("weekly_breakdown")
        stale_age = api_data.get("age_seconds")
        overage = "enabled" if api_data.get("overage_enabled") else None
        locked = api_data.get("locked")
        extra = api_data.get("extra")
        active_limit = api_data.get("active_limit")
        data_ts = api_data.get("fetched_at")
    else:
        # No real source (API unavailable, no cache): show "--".
        # An invented number on screen is worse than no number.
        pct_7d = None
        pct_5h = None
        overage = None
        locked = None
        extra = None
        active_limit = None
        stale_age = None
        source = "none"

    active_sessions = [s for s in sessions if s["status"] == "busy"]
    idle_sessions = [s for s in sessions if s["status"] == "idle"]

    result = {
        "pct": pct_7d,
        "pct_7d": pct_7d,
        "pct_5h": pct_5h,
        "source": source,
        "stale": stale,
        "account_changed": account_changed,
        "account": account.get("account_name") or "unknown",
        "plan": account.get("plan") or "unknown",
        "email": account.get("email", ""),
        "identity_stale": account.get("identity_stale", False),
        "active_sessions": len(active_sessions),
        "idle_sessions": len(idle_sessions),
        "last_reset": last_reset.isoformat() if last_reset else None,
        "next_reset": next_reset.isoformat() if next_reset else None,
        "seconds_until_reset": seconds_until_reset,
        "seconds_until_reset_5h": seconds_until_reset_5h,
        "reset_7d_epoch": reset_7d_epoch,
        "reset_5h_epoch": reset_5h_epoch,
        "data_ts": int(data_ts) if data_ts else None,
    }
    if scope_7d and scope_7d != "all":
        result["pct_7d_scope"] = scope_7d
    if weekly_breakdown:
        result["weekly_breakdown"] = weekly_breakdown
    # What is spent and what still runs — the panel, the tooltip and the
    # "limit is back" notification all read this instead of re-deriving it.
    if pct_7d is not None:
        result["availability"] = availability(pct_5h, weekly_breakdown)
    if stale_age is not None:
        result["stale_age_seconds"] = stale_age
    if overage:
        result["overage_status"] = overage
    if locked:
        result["locked"] = locked
    if extra:
        result["extra"] = extra
    if active_limit:
        result["active_limit"] = active_limit
    # History/forecast must never take down the usage pipeline.
    try:
        history.record(result)
        fc = history.attach_forecasts(result, state)
        if fc:
            result["forecast"] = fc
    except Exception:
        import traceback
        traceback.print_exc()
    return result


def _last_reset(day, time_str, tz_name):
    """Most recent manual weekly reset, or None when not configured.
    tz_name None = system local timezone."""
    if not day or not time_str:
        return None
    days_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    try:
        tz = ZoneInfo(tz_name) if tz_name else datetime.now().astimezone().tzinfo
        now = datetime.now(tz)
        h, m = map(int, time_str.split(":"))
    except (ValueError, KeyError, OSError):
        return None
    target_dow = days_map.get(day.lower(), 3)
    days_ago = (now.weekday() - target_dow) % 7
    if days_ago == 0 and (now.hour, now.minute) < (h, m):
        days_ago = 7
    last = now - timedelta(days=days_ago)
    last = last.replace(hour=h, minute=m, second=0, microsecond=0)
    return last.astimezone(timezone.utc)
