import json, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import usage_api

CLAUDE_JSON = Path.home() / ".claude" / ".claude.json"
PROXY_STATE = Path("/tmp/claude-monitor-proxy.json")
_prev_identity = None

def read_jobs(claude_dir: str) -> list[dict]:
    jobs_dir = Path(claude_dir) / "jobs"
    if not jobs_dir.exists():
        return []
    jobs = []
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        state_file = job_dir / "state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text())
            jobs.append({
                "id": job_dir.name,
                "state": data.get("state", "unknown"),
                "tokens": data.get("tokens", 0),
                "name": data.get("name", ""),
                "created_at": data.get("createdAt", ""),
                "updated_at": data.get("updatedAt", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return jobs

def read_sessions(claude_dir: str) -> list[dict]:
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

def get_account_identity() -> dict:
    info = {"account_name": None, "org_name": None, "plan": None, "email": None, "uuid": None}
    try:
        data = json.loads(CLAUDE_JSON.read_text())
        oa = data.get("oauthAccount", {})
        info["account_name"] = oa.get("displayName") or oa.get("organizationName") or oa.get("emailAddress", "default")
        info["org_name"] = oa.get("organizationName")
        info["plan"] = oa.get("organizationType") or oa.get("organizationRateLimitTier", "?")
        info["email"] = oa.get("emailAddress")
        info["uuid"] = oa.get("accountUuid", "")
    except (OSError, json.JSONDecodeError):
        pass
    return info

def detect_account_change() -> tuple[bool, str | None]:
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
    )
    _prev_identity = cur
    return changed, name

def calc_usage(state: dict) -> dict:
    now = datetime.now(timezone.utc)
    now_ts = time.time()
    last_reset = _last_reset(state["reset_day"], state["reset_time"], state["reset_timezone"])
    next_reset = last_reset + timedelta(days=7)
    seconds_until_reset = int((next_reset - now).total_seconds())
    seconds_until_reset_5h = None

    jobs = read_jobs(state["claude_dir"])
    sessions = read_sessions(state["claude_dir"])
    account = get_account_identity()
    account_changed, _ = detect_account_change()

    api_data = usage_api.fetch(state.get("api_poll_interval", 60))

    proxy_data = None
    if PROXY_STATE.exists():
        try:
            pd = json.loads(PROXY_STATE.read_text())
            if now_ts - pd.get("_updated_at", 0) < 600:
                proxy_data = pd
        except (json.JSONDecodeError, OSError):
            pass

    stale = False
    scope_7d = None
    weekly_breakdown = None
    reset_7d_epoch = None
    reset_5h_epoch = None

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
        proxy_age = api_data.get("age_seconds")
        overage = "enabled" if api_data.get("overage_enabled") else None
    elif proxy_data and "pct_7d" in proxy_data:
        pct_7d = round(proxy_data["pct_7d"] * 100, 1)
        pct_5h = round(proxy_data.get("pct_5h", 0) * 100, 1)
        reset_7d_epoch = proxy_data.get("reset_7d") or None
        reset_5h_epoch = proxy_data.get("reset_5h") or None
        if reset_7d_epoch:
            next_reset = datetime.fromtimestamp(reset_7d_epoch, tz=timezone.utc)
            seconds_until_reset = int((next_reset - now).total_seconds())
        if reset_5h_epoch:
            reset_5h = datetime.fromtimestamp(reset_5h_epoch, tz=timezone.utc)
            seconds_until_reset_5h = max(0, int((reset_5h - now).total_seconds()))
        source = "proxy"
        proxy_age = int(now_ts - proxy_data["_updated_at"])
        overage = proxy_data.get("overage_status", "")
    else:
        # Last resort: estimate from background-job token counts. Only covers
        # bg jobs (not interactive sessions) against a user-guessed limit, so
        # it is a rough floor, never the real account utilization.
        pct_5h = None
        overage = None
        proxy_age = None
        def parse_ts(ts_str):
            try:
                return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return None
        done_tokens = 0
        running_tokens = 0
        for j in jobs:
            created = parse_ts(j.get("created_at", ""))
            if created and created < last_reset:
                continue
            if j["state"] in ("done", "running"):
                if j["state"] == "done":
                    done_tokens += j["tokens"]
                else:
                    running_tokens += j["tokens"]
        total_tokens = done_tokens + running_tokens
        limit = state["weekly_limit"]
        pct_7d = round((total_tokens / limit * 100) if limit > 0 else 0, 1)
        reset_7d_epoch = int(next_reset.timestamp())
        source = "jobs"

    active_sessions = [s for s in sessions if s["status"] == "busy"]
    idle_sessions = [s for s in sessions if s["status"] == "idle"]

    result = {
        "pct": pct_7d,
        "pct_7d": pct_7d,
        "pct_5h": pct_5h,
        "source": source,
        "stale": stale,
        "account_changed": account_changed,
        "account": account.get("account_name", "desconhecida"),
        "plan": account.get("plan", "desconhecido"),
        "email": account.get("email", ""),
        "active_sessions": len(active_sessions),
        "idle_sessions": len(idle_sessions),
        "last_reset": last_reset.isoformat(),
        "next_reset": next_reset.isoformat(),
        "seconds_until_reset": seconds_until_reset,
        "seconds_until_reset_5h": seconds_until_reset_5h,
        "reset_7d_epoch": reset_7d_epoch,
        "reset_5h_epoch": reset_5h_epoch,
    }
    if scope_7d and scope_7d != "all":
        result["pct_7d_scope"] = scope_7d
    if weekly_breakdown:
        result["weekly_breakdown"] = weekly_breakdown
    if proxy_age is not None:
        result["proxy_age_seconds"] = proxy_age
    if overage:
        result["overage_status"] = overage
    if source == "jobs":
        result.update({
            "total_tokens": total_tokens,
            "done_tokens": done_tokens,
            "running_tokens": running_tokens,
            "limit": limit,
        })
    return result

def _last_reset(day: str, time_str: str, tz_name: str) -> datetime:
    days_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    h, m = map(int, time_str.split(":"))
    target_dow = days_map.get(day.lower(), 3)
    days_ago = (now.weekday() - target_dow) % 7
    if days_ago == 0 and (now.hour, now.minute) < (h, m):
        days_ago = 7
    last = now - timedelta(days=days_ago)
    last = last.replace(hour=h, minute=m, second=0, microsecond=0)
    return last.astimezone(timezone.utc)
