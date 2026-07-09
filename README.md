# claude-monitor

Dongle flutuante com os percentuais de rate limit do Claude Code: janela de sessão (5h) e janela semanal, lidos direto da API OAuth oficial da Anthropic usando o token local do próprio Claude Code (`~/.claude/.credentials.json`). Zero configuração: sem proxy, sem wrapper.

## Arquitetura

- `usage_api.py` consulta `https://api.anthropic.com/api/oauth/usage` e normaliza os percentuais (5h, semanal, resets, breakdown por modelo).
- `monitor.py` (`calc_usage`) monta o estado com hierarquia de fontes: **api** → **proxy** → **estimativa por jobs**.
- O dongle e o dashboard (PyQt6) exibem o estado; `notifier.py` notifica nos thresholds.
- Proxy mitmproxy (`proxy.py` + `mitm_addon.py`) é fallback **opcional**, ligado por `proxy_enabled`.
- Estimativa por jobs (tokens de background jobs contra `weekly_limit`) é o último recurso.

## Como rodar

```bash
./run.sh tray     # dongle + tray
./run.sh status   # estado atual em JSON
./run.sh config   # janela de configuração
```

Como serviço systemd de usuário: unit `claude-monitor.service` em `~/.config/systemd/user/`.

```bash
systemctl --user status claude-monitor.service
```

## Configuração

Arquivo: `~/.config/claude-monitor/config.json`. Principais chaves:

| Chave | Default | O que faz |
|---|---|---|
| `thresholds` | `[50, 70, 85, 95]` | percentuais que disparam notificação (semanal e 5h) |
| `poll_interval` | `5` | segundos entre atualizações do dongle |
| `api_poll_interval` | `60` | intervalo mínimo (s) entre chamadas à API OAuth |
| `dongle_opacity` | `0.85` | opacidade do dongle (0 a 1) |
| `show_mode` | `"always"` | quando mostrar o dongle: `always`, `claude`, `dev` ou `custom` (usa `show_processes`) |
| `proxy_enabled` | `false` | liga o fallback via mitmproxy (legado; exige `claude-wrapper.sh` ou as env vars de `./run.sh wrapper`) |
