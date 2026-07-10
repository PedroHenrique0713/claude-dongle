# claude-monitor

Dongle flutuante com os percentuais de rate limit do Claude Code: janela de sessão (5h) e janela semanal, lidos direto da API OAuth oficial da Anthropic usando o token local do próprio Claude Code (`~/.claude/.credentials.json`). Zero configuração: sem proxy, sem wrapper.

## Arquitetura

- `usage_api.py` consulta `https://api.anthropic.com/api/oauth/usage` e normaliza os percentuais (5h, semanal, resets, breakdown por modelo).
- `monitor.py` (`calc_usage`) monta o estado a partir da API; sem fonte real (API indisponível e sem cache), mostra `--` em vez de inventar número.
- O dongle e o dashboard (PyQt6) exibem o estado; `notifier.py` notifica nos thresholds; `history.py` guarda a série temporal (burn rate + previsão de estouro).

## Como rodar

```bash
./run.sh tray     # dongle flutuante (entrypoint do serviço)
./run.sh status   # estado atual em JSON
./run.sh notify   # checa thresholds uma vez e notifica (usado pelo timer)
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
| `api_poll_interval` | `300` | intervalo mínimo (s) entre chamadas à API OAuth (o endpoint rate-limita polling agressivo) |
| `dongle_opacity` | `0.85` | opacidade do dongle (0 a 1) |
| `show_mode` | `"dev"` | quando mostrar o dongle: `always`, `claude`, `dev` ou `custom` (usa `show_processes`) |
| `notify_on_threshold` | `true` | liga as notificações ao cruzar um threshold |
| `notify_on_limit` | `true` | liga a notificação ao atingir 100% |
| `forecast_notify` | `true` | liga a notificação de previsão de estouro antes do reset |
