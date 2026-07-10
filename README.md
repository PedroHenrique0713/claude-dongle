# claude-monitor

Dongle flutuante + painel com os limites de uso do Claude Code em tempo real:
janela de sessão (5h) e semanal (por modelo), lidos direto da API OAuth oficial
da Anthropic usando o token local do próprio Claude Code
(`~/.claude/.credentials.json`). Sem proxy, sem login extra.

Recursos: burn rate e previsão de estouro, uso por projeto/modelo (a partir dos
logs locais), notificações por limite, e um dongle que avisa de relance quando
você está prestes a estourar.

Funciona em **Linux, macOS e Windows**.

## Instalação

Requer Python 3.9+ e o Claude Code instalado e logado na máquina.

Com [pipx](https://pipx.pypa.io) (recomendado — isola num ambiente próprio):

```bash
pipx install git+https://github.com/PedroHenrique0713/claude-monitor
```

Ou com pip:

```bash
pip install --user git+https://github.com/PedroHenrique0713/claude-monitor
```

Depois:

```bash
claude-monitor tray      # abre o dongle flutuante
claude-monitor setup     # (opcional) sobe sozinho no login deste SO
```

`setup` configura o autostart do jeito de cada sistema: **systemd user** (Linux),
**LaunchAgent** (macOS) ou **pasta Iniciar** (Windows). `claude-monitor uninstall`
remove.

## Comandos

```bash
claude-monitor tray       # dongle flutuante (uso normal)
claude-monitor status     # estado atual em JSON
claude-monitor notify     # checa os limites uma vez e notifica
claude-monitor config     # abre só o painel de configuração
claude-monitor setup      # configura o autostart no login (este SO)
claude-monitor uninstall  # remove o autostart
```

Sem instalar, do próprio repositório: `./run.sh tray` (Linux/macOS) ou
`python -m claude_monitor tray`.

## Como funciona

- `usage_api` consulta `https://api.anthropic.com/api/oauth/usage` e normaliza os
  percentuais (5h, semanal, resets, breakdown por modelo).
- `monitor.calc_usage` monta o estado a partir da API; sem fonte real (API fora e
  sem cache) mostra `--` em vez de inventar número.
- O dongle e o painel (PyQt6) exibem o estado; `notifier` avisa nos limites;
  `history` guarda a série temporal (burn rate + previsão de estouro);
  `projects` agrega o uso por projeto/modelo dos JSONL de `~/.claude/projects`.
- O dongle usa `show_mode` para aparecer só quando faz sentido (ex. `dev` = só com
  editor/terminal aberto); escondido, não consome a API.

## Configuração

Arquivo: `~/.config/claude-monitor/config.json`. Principais chaves:

| Chave | Default | O que faz |
|---|---|---|
| `thresholds` | `[50, 70, 85, 95]` | percentuais que disparam notificação (semanal e 5h) |
| `poll_interval` | `5` | segundos entre atualizações do dongle |
| `api_poll_interval` | `300` | intervalo mínimo (s) entre chamadas à API (o endpoint rate-limita polling agressivo) |
| `dongle_opacity` | `0.85` | opacidade do dongle (0 a 1) |
| `show_mode` | `"dev"` | quando mostrar o dongle: `always`, `claude`, `dev` ou `custom` (usa `show_processes`) |
| `notify_on_threshold` | `true` | liga as notificações ao cruzar um threshold |
| `notify_on_limit` | `true` | liga a notificação ao atingir 100% |
| `forecast_notify` | `true` | liga a notificação de previsão de estouro antes do reset |
