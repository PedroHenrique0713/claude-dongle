#!/usr/bin/env bash
# Roda o pacote direto do repo (sem instalar). Para uso normal, prefira
# `pipx install .` e o comando `claude-monitor`.
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec env PYTHONPATH="$HERE" python3 -m claude_dongle "$@"
