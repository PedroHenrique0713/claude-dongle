#!/usr/bin/env bash
# claude-wrapper.sh — runs Claude Code through the local mitmproxy
# so the monitor can capture real rate-limit headers from the API.
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
export NODE_EXTRA_CA_CERTS="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
export HTTPS_PROXY="http://localhost:8081"
export HTTP_PROXY="http://localhost:8081"
exec claude "$@"
