import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from . import config

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
# On macOS, Claude Code stores its credentials in the Keychain under this
# service name instead of (or in addition to) ~/.claude/.credentials.json.
MAC_KEYCHAIN_SERVICE = "Claude Code-credentials"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_PATH = config.CONFIG_DIR / "usage_cache.json"
# The monitor's own cache for refreshed tokens — it NEVER writes to Claude
# Code's .credentials.json (avoids racing/corrupting a file Claude Code owns).
TOKEN_CACHE_PATH = config.CONFIG_DIR / "token_cache.json"
# Endpoint and client_id validated 2026-07-10 with a fake refreshToken: the
# server answered invalid_grant (it understood grant_type/client_id/format).
# console.* gives 404/Cloudflare; the right host is api.anthropic.com with no
# special User-Agent.
OAUTH_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Claude Code's public client id
TOKEN_SKEW = 60  # refresh 60s before expiresAt

_cache = {"data": None, "fetched_at": 0, "next_try": 0, "account": None}
_disk_checked = False


def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_private(path: Path, text: str):
    """Write a file containing token material with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _mac_keychain_oauth():
    """Claude Code credentials from the macOS Keychain, or {}."""
    try:
        out = subprocess.check_output(
            ["security", "find-generic-password", "-s", MAC_KEYCHAIN_SERVICE, "-w"],
            text=True, timeout=5, stderr=subprocess.DEVNULL)
        d = json.loads(out)
        return d.get("claudeAiOauth", d) if isinstance(d, dict) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return {}


def claude_oauth():
    """Claude Code's stored OAuth blob: credentials file, then macOS Keychain."""
    d = _load_json(CREDENTIALS_PATH)
    oauth = d.get("claudeAiOauth", d) if isinstance(d, dict) else {}
    if not oauth.get("accessToken") and sys.platform == "darwin":
        oauth = _mac_keychain_oauth() or oauth
    return oauth


def _valid_access(oauth):
    """accessToken if present and not about to expire, else None."""
    tok = oauth.get("accessToken") if isinstance(oauth, dict) else None
    exp = oauth.get("expiresAt", 0) if isinstance(oauth, dict) else 0
    if tok and (not exp or exp / 1000 > time.time() + TOKEN_SKEW):
        return tok
    return None


def _refresh_token(refresh_token):
    """Exchange the refreshToken for a new accessToken via OAuth. Returns the
    monitor's own cache dict {access_token, expires_at, refresh_token} or None.
    Does NOT write to Claude Code's file."""
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError,
            json.JSONDecodeError, OSError):
        return None
    at = resp.get("access_token")
    if not at:
        return None
    return {
        "access_token": at,
        "expires_at": time.time() + resp.get("expires_in", 3600),
        "refresh_token": resp.get("refresh_token") or refresh_token,
    }


def _read_token():
    """Token for the usage API, resilient to Claude Code being closed. Order:
    (1) valid accessToken from Claude Code; (2) valid own cache;
    (3) refresh, but only with an OWN refreshToken. Never writes to
    .credentials.json.

    IMPORTANT (verified 2026-07-10): Anthropic ROTATES the refreshToken on
    every refresh. If the monitor used Claude Code's refreshToken it would
    invalidate it and log Claude Code's session out. That's why we never fall
    back to Claude Code's token — we only refresh with our own cached
    refreshToken (which nothing seeds automatically today, so the refresh
    path stays inert and safe)."""
    tok = _valid_access(claude_oauth())
    if tok:
        return tok
    cache = _load_json(TOKEN_CACHE_PATH)
    if cache.get("access_token") and cache.get("expires_at", 0) > time.time() + TOKEN_SKEW:
        return cache["access_token"]
    rt = cache.get("refresh_token")  # NEVER Claude Code's (rotates → logs it out)
    if not rt:
        return None
    new = _refresh_token(rt)
    if not new:
        return None
    try:
        _write_private(TOKEN_CACHE_PATH, json.dumps(new))
    except OSError:
        pass
    return new["access_token"]


def _parse_iso(ts):
    """Epoch of an API timestamp, ROUNDED TO THE MINUTE.

    resets_at carries sub-second jitter around the whole minute
    (…T21:00:00.314 on one response, …T20:59:59.87 on the next). Truncating
    with int() made the same reset alternate between X and X-1, and that epoch
    is the identity of a window: it keys the notification dedup (the "100%"
    alert fired again on every flip) and the history's window_epoch (one
    series split into two). Resets land on whole minutes, so rounding there
    absorbs the jitter."""
    try:
        return int(round(datetime.fromisoformat(ts).timestamp() / 60) * 60)
    except (ValueError, TypeError):
        return None


# Weekly windows the API also exposes as top-level keys. Most accounts get
# their per-model breakdown through limits[]; these are the fallback for the
# ones that only get the flat keys. Value = the name we show.
TOP_LEVEL_WEEKLY = {
    "seven_day_opus": "Opus",
    "seven_day_sonnet": "Sonnet",
    "seven_day_cowork": "Cowork",
    "seven_day_oauth_apps": "OAuth apps",
}


def _normalize(body):
    out = {"source": "api", "stale": False}
    fh = body.get("five_hour") or {}
    sd = body.get("seven_day") or {}
    out["pct_5h"] = fh.get("utilization")
    out["pct_7d"] = sd.get("utilization")
    out["reset_5h"] = _parse_iso(fh.get("resets_at"))
    out["reset_7d"] = _parse_iso(sd.get("resets_at"))

    # locked_reason is the API saying this window is closed for good reasons of
    # its own (not merely 100% burned) — surface the reason instead of guessing.
    locked = []
    for label, win in (("5h session", fh), ("Week", sd)):
        if win.get("locked_reason"):
            locked.append({"label": label, "reason": win["locked_reason"]})

    # limits[] is richer: session + weekly_all + weekly_scoped (per-model).
    # For warning purposes the effective weekly pct is whichever bites first.
    weekly = []
    for lim in body.get("limits") or []:
        pct = lim.get("percent")
        if pct is None:
            continue
        scope = lim.get("scope") or {}
        model = (scope.get("model") or {}).get("display_name")
        active = bool(lim.get("is_active"))
        if lim.get("kind") == "session":
            out["pct_5h"] = float(pct)
            out["reset_5h"] = _parse_iso(lim.get("resets_at")) or out["reset_5h"]
            if active:
                out["active_limit"] = "5h"
        elif lim.get("group") == "weekly":
            weekly.append({
                "pct": float(pct),
                "kind": lim.get("kind"),
                "model": model,
                "reset": _parse_iso(lim.get("resets_at")),
                "severity": lim.get("severity"),
                "active": active,
            })
            if active:
                out["active_limit"] = f"7d:{model}" if model else "7d"
        if lim.get("locked_reason"):
            locked.append({"label": model or lim.get("kind") or "limit",
                           "reason": lim["locked_reason"]})

    # Fallback for accounts whose per-model weeks only come as top-level keys.
    known = {w["model"] for w in weekly if w["model"]}
    for key, name in TOP_LEVEL_WEEKLY.items():
        win = body.get(key)
        if not isinstance(win, dict) or win.get("utilization") is None:
            continue
        if name in known:
            continue
        weekly.append({
            "pct": float(win["utilization"]),
            "kind": "weekly_scoped",
            "model": name,
            "reset": _parse_iso(win.get("resets_at")) or out["reset_7d"],
            "severity": None,
            "active": False,
        })
        if win.get("locked_reason"):
            locked.append({"label": name, "reason": win["locked_reason"]})

    if weekly:
        top = max(weekly, key=lambda w: w["pct"])
        out["pct_7d"] = top["pct"]
        out["reset_7d"] = top["reset"] or out["reset_7d"]
        out["pct_7d_scope"] = top["model"] or "all"
        out["weekly_breakdown"] = weekly
    if locked:
        out["locked"] = locked

    # Extra usage = the paid overflow pool. We keep the PERCENTAGE and the
    # flags, never the amount: this monitor reports limits, not money spent
    # (a subscription is a flat fee — a "$ burned" number would be fiction).
    extra = body.get("extra_usage") or {}
    out["overage_enabled"] = bool(extra.get("is_enabled"))
    if extra.get("is_enabled") or extra.get("utilization") is not None:
        out["extra"] = {
            "enabled": bool(extra.get("is_enabled")),
            "pct": extra.get("utilization"),
            "limit_reached": bool(extra.get("spend_limit_reached")),
            "disabled_reason": extra.get("disabled_reason"),
        }
    return out


def _load_disk():
    # Survives restarts and dedupes across processes: the last real data point
    # lives on disk and any new process starts from it instead of the network.
    global _disk_checked
    if _disk_checked:
        return
    _disk_checked = True
    try:
        d = json.loads(CACHE_PATH.read_text())
        d["data"].setdefault("fetched_at", d["fetched_at"])  # old-version cache
        _cache["data"] = d["data"]
        _cache["fetched_at"] = d["fetched_at"]
        _cache["account"] = d.get("account")  # None in old-version cache
    except (OSError, json.JSONDecodeError, KeyError, AttributeError):
        pass


def invalidate():
    """Force the next fetch to hit the network (ignores min_interval). Respects
    an active 429 backoff — never re-fires an endpoint that just limited us."""
    _cache["fetched_at"] = 0


def _stale():
    if _cache["data"] is None:
        _load_disk()
    if _cache["data"] is None:
        return None
    d = dict(_cache["data"])
    d["stale"] = True
    d["age_seconds"] = int(time.time() - _cache["fetched_at"])
    return d


def fetch(min_interval=60, account=None):
    now = time.time()
    if _cache["data"] is None:
        _load_disk()
    # Account switched: the cached data (memory or disk, shared across
    # accounts) belongs to ANOTHER account. Drop it rather than show someone
    # else's usage — a wrong number is worse than "--". A cache without a
    # stamp (None, old version) is treated as compatible until the next fetch
    # stamps it.
    if account is not None and _cache["account"] not in (None, account):
        _cache["data"] = None
        _cache["account"] = None
        _cache["next_try"] = 0
    if _cache["data"] is not None and now - _cache["fetched_at"] < min_interval:
        return _cache["data"]
    # Back off on failed attempts too, otherwise every poll (dongle 30s,
    # dashboard 5s) re-fires the request and feeds its own 429.
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
        # 429 windows are long and retrying renews the penalty: space out well
        _cache["next_try"] = now + (900 if e.code == 429 else min_interval)
        return _stale()
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        _cache["next_try"] = now + min_interval
        return _stale()
    data = _normalize(body)
    if data.get("pct_7d") is None and data.get("pct_5h") is None:
        _cache["next_try"] = now + min_interval
        return _stale()
    data["fetched_at"] = now  # data timestamp; history dedupes by it
    _cache["data"] = data
    _cache["fetched_at"] = now
    _cache["next_try"] = 0
    _cache["account"] = account
    try:
        _write_private(CACHE_PATH, json.dumps(
            {"data": data, "fetched_at": now, "account": account}))
    except OSError:
        pass
    return data
