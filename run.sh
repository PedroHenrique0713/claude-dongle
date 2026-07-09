#!/usr/bin/env bash
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec python3 "$HERE/main.py" "$@"
