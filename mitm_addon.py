import json, time
from mitmproxy import http

STATE_FILE = "/tmp/claude-monitor-proxy.json"
CAPTURE_HOSTS = {"api.anthropic.com"}

def write_state(data: dict):
    # Merge over the existing state: a /settings response must not wipe the
    # pct_* fields captured from an earlier /v1/messages response.
    existing = {}
    try:
        with open(STATE_FILE) as f:
            existing = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    existing.update(data)
    existing["_updated_at"] = time.time()
    with open(STATE_FILE, "w") as f:
        json.dump(existing, f)

def request(flow: http.HTTPFlow):
    pass

def response(flow: http.HTTPFlow):
    host = flow.request.pretty_host
    if host not in CAPTURE_HOSTS:
        return
    path = flow.request.path
    headers = dict(flow.response.headers)
    is_messages = "/v1/messages" in path
    is_settings = "/api/oauth/account/settings" in path
    if not is_messages and not is_settings:
        return
    rate = {}
    for k, v in headers.items():
        kl = k.lower()
        if "ratelimit" in kl or "usage" in kl or "limit" in kl or "overage" in kl:
            rate[k] = v
    data = {"rate_headers": rate}
    if is_messages and "anthropic-ratelimit-unified-7d-utilization" in rate:
        data["pct_7d"] = float(rate["anthropic-ratelimit-unified-7d-utilization"])
        data["pct_5h"] = float(rate.get("anthropic-ratelimit-unified-5h-utilization", 0))
        data["reset_7d"] = int(rate.get("anthropic-ratelimit-unified-7d-reset", 0))
        data["reset_5h"] = int(rate.get("anthropic-ratelimit-unified-5h-reset", 0))
        data["status_7d"] = rate.get("anthropic-ratelimit-unified-7d-status", "")
        data["status_5h"] = rate.get("anthropic-ratelimit-unified-5h-status", "")
        data["overage_disabled"] = rate.get("anthropic-ratelimit-unified-overage-disabled-reason", "")
        data["overage_status"] = rate.get("anthropic-ratelimit-unified-overage-status", "")
        data["source"] = "proxy"
        if "anthropic-ratelimit-unified-7d_oi-utilization" in rate:
            data["pct_7d_oi"] = float(rate["anthropic-ratelimit-unified-7d_oi-utilization"])
    if is_settings and len(flow.response.content) < 50000:
        try:
            body = json.loads(flow.response.text)
            data["account_settings"] = body
        except (json.JSONDecodeError, ValueError):
            pass
    write_state(data)
