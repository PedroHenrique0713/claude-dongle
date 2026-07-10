import json, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

import config

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CACHE_PATH = config.CONFIG_DIR / "usage_cache.json"
# Cache próprio do token renovado — o monitor NUNCA grava no .credentials.json
# do Claude Code (evita corrida/corrupção do arquivo que o Claude Code é dono).
TOKEN_CACHE_PATH = config.CONFIG_DIR / "token_cache.json"
# Endpoint e client_id validados 2026-07-10 com um refreshToken fake: o servidor
# respondeu invalid_grant (entendeu grant_type/client_id/formato). console.* dá
# 404/Cloudflare; o correto é api.anthropic.com sem User-Agent especial.
OAUTH_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_SKEW = 60  # renova com 60s de folga antes do expiresAt

_cache = {"data": None, "fetched_at": 0, "next_try": 0, "account": None}
_disk_checked = False


def _load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _claude_oauth():
    d = _load_json(CREDENTIALS_PATH)
    return d.get("claudeAiOauth", d) if isinstance(d, dict) else {}


def _valid_access(oauth):
    """accessToken se presente e não perto de expirar, senão None."""
    tok = oauth.get("accessToken") if isinstance(oauth, dict) else None
    exp = oauth.get("expiresAt", 0) if isinstance(oauth, dict) else 0
    if tok and (not exp or exp / 1000 > time.time() + TOKEN_SKEW):
        return tok
    return None


def _refresh_token(refresh_token):
    """Troca o refreshToken por um accessToken novo via OAuth. Devolve o dict do
    cache próprio {access_token, expires_at, refresh_token} ou None. NÃO grava no
    arquivo do Claude Code."""
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
    """Token para a usage API, resiliente ao Claude Code fechado. Ordem:
    (1) accessToken válido do Claude Code; (2) cache próprio válido;
    (3) refresh só com um refreshToken PRÓPRIO. Nunca escreve no .credentials.json.

    IMPORTANTE (verificado 2026-07-10): o Anthropic ROTACIONA o refreshToken a
    cada refresh. Se o monitor usasse o refreshToken do Claude Code, o
    invalidaria e deslogaria a sessão dele. Por isso NÃO recorremos ao token do
    Claude Code — só refrescamos com um refreshToken próprio no cache (que hoje
    nada semeia automaticamente, então o refresh fica inerte e seguro)."""
    tok = _valid_access(_claude_oauth())
    if tok:
        return tok
    cache = _load_json(TOKEN_CACHE_PATH)
    if cache.get("access_token") and cache.get("expires_at", 0) > time.time() + TOKEN_SKEW:
        return cache["access_token"]
    rt = cache.get("refresh_token")  # NUNCA o do Claude Code (rotaciona → desloga)
    if not rt:
        return None
    new = _refresh_token(rt)
    if not new:
        return None
    try:
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_PATH.write_text(json.dumps(new))
    except OSError:
        pass
    return new["access_token"]


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


def _load_disk():
    # Sobrevive a restart e desduplica entre processos: o último dado real
    # fica em disco e qualquer processo novo parte dele em vez da rede.
    global _disk_checked
    if _disk_checked:
        return
    _disk_checked = True
    try:
        d = json.loads(CACHE_PATH.read_text())
        d["data"].setdefault("fetched_at", d["fetched_at"])  # cache de versão antiga
        _cache["data"] = d["data"]
        _cache["fetched_at"] = d["fetched_at"]
        _cache["account"] = d.get("account")  # None em cache de versão antiga
    except (OSError, json.JSONDecodeError, KeyError, AttributeError):
        pass


def invalidate():
    """Força o próximo fetch a ir à rede (ignora o min_interval). Respeita o
    backoff de 429 ativo — não re-dispara um endpoint que acabou de nos limitar."""
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
    # Conta trocou: o dado cacheado (memória ou disco, compartilhado entre
    # contas) é de OUTRA conta. Descartar em vez de exibir uso alheio — número
    # de outra conta é pior que "--". Cache sem carimbo (None, versão antiga)
    # é tratado como compatível até o próximo fetch o carimbar.
    if account is not None and _cache["account"] not in (None, account):
        _cache["data"] = None
        _cache["account"] = None
        _cache["next_try"] = 0
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
        # 429 tem janela longa e retry renova a penalidade: espaçar bem
        _cache["next_try"] = now + (900 if e.code == 429 else min_interval)
        return _stale()
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        _cache["next_try"] = now + min_interval
        return _stale()
    data = _normalize(body)
    if data.get("pct_7d") is None and data.get("pct_5h") is None:
        _cache["next_try"] = now + min_interval
        return _stale()
    data["fetched_at"] = now  # carimbo do dado; o histórico deduplica por ele
    _cache["data"] = data
    _cache["fetched_at"] = now
    _cache["next_try"] = 0
    _cache["account"] = account
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(
            {"data": data, "fetched_at": now, "account": account}))
    except OSError:
        pass
    return data
