import json, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

_cache = {"data": None, "fetched_at": 0, "next_try": 0}


def _read_token():
    try:
        d = json.loads(CREDENTIALS_PATH.read_text())
        oauth = d.get("claudeAiOauth", d)
        token = oauth.get("accessToken")
        exp = oauth.get("expiresAt", 0)
        if not token or (exp and exp / 1000 < time.time()):
            return None
        return token
    except (OSError, json.JSONDecodeError):
        return None


def _parse_iso(ts):
    try:
        return int(datetime.fromisoformat(ts).timestamp())
    except (ValueError, TypeError):
        return None


def _normalize(body):
    out = {"source": "api", "stale": False}
    fh = body.get("five_hour") or {}
    sd = body.get("seven_day") or {}
    out["pct_5h"] = fh.get("utilization")
    out["pct_7d"] = sd.get("utilization")
    out["reset_5h"] = _parse_iso(fh.get("resets_at"))
    out["reset_7d"] = _parse_iso(sd.get("resets_at"))

    # limits[] is richer: session + weekly_all + weekly_scoped (per-model).
    # For warning purposes the effective weekly pct is whichever bites first.
    weekly = []
    for lim in body.get("limits") or []:
        pct = lim.get("percent")
        if pct is None:
            continue
        if lim.get("kind") == "session":
            out["pct_5h"] = float(pct)
            out["reset_5h"] = _parse_iso(lim.get("resets_at")) or out["reset_5h"]
        elif lim.get("group") == "weekly":
            scope = lim.get("scope") or {}
            model = (scope.get("model") or {}).get("display_name")
            weekly.append({
                "pct": float(pct),
                "kind": lim.get("kind"),
                "model": model,
                "reset": _parse_iso(lim.get("resets_at")),
                "severity": lim.get("severity"),
            })
    if weekly:
        top = max(weekly, key=lambda w: w["pct"])
        out["pct_7d"] = top["pct"]
        out["reset_7d"] = top["reset"] or out["reset_7d"]
        out["pct_7d_scope"] = top["model"] or "all"
        out["weekly_breakdown"] = weekly

    extra = body.get("extra_usage") or {}
    out["overage_enabled"] = bool(extra.get("is_enabled"))
    return out


def _stale():
    if _cache["data"] is None:
        return None
    d = dict(_cache["data"])
    d["stale"] = True
    d["age_seconds"] = int(time.time() - _cache["fetched_at"])
    return d


def fetch(min_interval=60):
    now = time.time()
    if _cache["data"] is not None and now - _cache["fetched_at"] < min_interval:
        return _cache["data"]
    # Backoff também sobre tentativas falhas, senão cada poll (dongle 30s,
    # dashboard 5s) re-dispara a request e alimenta o próprio 429.
    if now < _cache["next_try"]:
        return _stale()
    token = _read_token()
    if not token:
        _cache["next_try"] = now + min_interval
        return _stale()
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        _cache["next_try"] = now + (300 if e.code == 429 else min_interval)
        return _stale()
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        _cache["next_try"] = now + min_interval
        return _stale()
    data = _normalize(body)
    if data.get("pct_7d") is None and data.get("pct_5h") is None:
        _cache["next_try"] = now + min_interval
        return _stale()
    _cache["data"] = data
    _cache["fetched_at"] = now
    _cache["next_try"] = 0
    return data
