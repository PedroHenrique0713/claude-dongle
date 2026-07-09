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

Como serviço systemd de usuário: unit `claude-monitor.service` (versionada no repo, instalada em `~/.config/systemd/user/`).

```bash
systemctl --user status claude-monitor.service
```

## Ciclo de vida (ativação sob demanda)

O serviço **não** sobe no boot (autostart desabilitado de propósito). O ciclo é:

1. **Sobe**: hook no `~/.bashrc` dá `systemctl --user start --no-block` em todo shell
   interativo — abrir um terminal (ou o VS Code, que sonda o ambiente com shell
   interativo) ergue o serviço na hora. Idempotente: já rodando, é no-op.
2. **Mostra/esconde**: com `show_mode: dev`, o dongle só aparece enquanto houver
   dev tools abertos (match por prefixo do comm: code, cursor, ptyxis, kgx…).
   Escondido, o poll não consome API.
3. **Morre**: escondido por `idle_quit_minutes` (padrão 10), o processo se encerra
   sozinho. O próximo terminal aberto ressuscita via hook.

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
