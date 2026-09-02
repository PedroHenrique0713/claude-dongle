"""UI and notification strings, in English and Brazilian Portuguese.

One dict per language, keyed by a short semantic id. t() falls back to English
whenever a key is missing from a translation, so a half-finished language
degrades into English instead of showing raw keys on screen.
"""
import locale
import os

DEFAULT = "en"
# (label shown in the picker, code stored in the config)
LANGUAGES = [("EN", "en"), ("PT-BR", "pt-BR")]

EN = {
    "app.title": "Claude Dongle",

    # availability
    "avail.spent_scope": "{model} is spent · back in {time} · the other models keep working",
    "avail.spent_all": "{label} is spent · back in {time} · nothing runs until then",
    "avail.spent_all_notime": "{label} is spent · nothing runs until it resets",
    "avail.ring_spent": "{time}  ·  spent",

    # cards / sections
    "card.usage": "Usage",
    "card.dongle": "Dongle",
    "card.visibility": "Visibility",
    "card.notifications": "Notifications",
    "card.language": "Language",
    "sec.forecast": "FORECAST",
    "sec.projects": "BY PROJECT",
    "sec.settings": "SETTINGS",
    "sec.hours": "BY HOUR",
    "hours.hint": "Average burn per hour of the day · {days} days observed",
    "hours.peak": "your peak is around {hour}h",
    "hours.empty": "not enough history yet — come back in a couple of days",

    # account
    "acc.switched": "Account switched",
    "acc.reopen": "reopen Claude Code to sync the name",

    # usage rings + meta line
    "usage.session": "5h session",
    "usage.week": "Week",
    "pace.high": "high",
    "pace.low": "low",
    "pace.on": "on pace",
    "src.api": "official API",
    "src.none": "no data",
    "meta.stale": "stale data",
    "meta.stale_age": "stale data · {age} ago",
    "meta.session_one": "1 active session",
    "meta.sessions": "{n} active sessions",
    "meta.extra_on": "extra usage on",

    # forecast
    "fc.session": "Session (5h)",
    "fc.week": "Week",
    "fc.week_model": "Week · {model}",
    "fc.rate": "{rate:+.1f} pp/h",
    "fc.collecting": "collecting data…",
    "fc.steady": "steady pace · no ceiling in sight",
    "fc.budget_before": "~{eta} of work left · the reset only comes in {reset}",
    "fc.budget_reset_first": "enough to reach the reset in {reset} at this pace",
    "fc.budget_plain": "~{eta} of work left at this pace",
    "fc.overflow_before": "at current pace overflows in {eta} · before reset ({reset})",
    "fc.overflow_low": "at recent pace would overflow in {eta} · usage still low",
    "fc.reset_first": "overflows in {eta} · reset arrives first ({reset})",
    "fc.overflow_plain": "at current pace overflows in {eta}",

    # by project
    "pj.hint": "Output tokens · last 7 days · local count",
    "pj.projects": "Projects",
    "pj.models": "Models",
    "pj.last14": "Last 14 days",
    "pj.collecting": "collecting local data…",
    "pj.heatmap_tip": "rightmost = most recent · shade = usage",

    # settings
    "set.opacity": "Opacity",
    "vis.always": "Always visible",
    "vis.claude": "Only with Claude Code",
    "vis.dev": "Only with VS Code / terminal",
    "vis.custom": "Specific processes",
    "notif.thresholds_hint": "Alert me when a limit crosses",
    "notif.threshold_crossed": "Threshold crossed",
    "notif.limit_reached": "Limit reached (100%)",
    "notif.overflow_forecast": "Overflow forecast",
    "notif.limit_freed": "Limit came back",
    "notif.telemetry_lost": "Data source lost",
    "notif.gap_hint": "Minimum gap between routine alerts — a limit reached always goes through",
    "notif.off": "Off",
    "notif.snooze_all": "Snooze all",
    "notif.until_reset": "Until reset",
    "notif.muted": "Muted · {time} left",
    "notif.resume": "Resume",
    "btn.close": "Close",
    "btn.quit": "Quit monitor",

    # notifications
    "n.session": "5h session",
    "n.week_all": "Overall week",
    "n.week_model": "Week {model}",
    "n.pct_title": "{label} · {pct}%",
    "n.resets_in": "Resets in {time}",
    "n.limit_title": "{label} · 100%",
    "n.limit_body": "Limit reached · resets in {time}",
    "n.forecast_title": "{label} · overflow forecast",
    "n.forecast_body": "{pct}% now · +{rate} pp/h · overflows in {eta}, "
                       "before the reset in {reset}",
    "n.freed_title": "{label} is back",
    "n.freed_body": "the limit reset · you can work again",
    "n.multi_title": "Usage limits",
    "n.telemetry_title": "No usage telemetry",
    "n.telemetry_body": "No fresh data for {time} — the token may have expired "
                        "or the API is unavailable.",
    "n.account_title": "Account: {account}",
    "n.account_body": "Plan: {plan}",

    # dongle tooltip
    "tip.source": "Source: {src}",
    "tip.stale": " · stale data",
    "tip.session": "5h session: {pct}% · resets in {time}",
    "tip.week": "Overall week: {pct}% · resets in {time}",
    "tip.week_model": "{model} week: {pct}%",
    "tip.budget": "at this pace: ~{eta} of work left",
    "tip.overflow": "⚠ at current pace, overflows before reset",
    "tip.actions": "click: open dashboard · middle: refresh now",

    # time
    "time.now": "now",
}

PT = {
    "avail.spent_scope": "{model} esgotado · volta em {time} · os outros modelos seguem",
    "avail.spent_all": "{label} esgotada · volta em {time} · nada roda até lá",
    "avail.spent_all_notime": "{label} esgotada · nada roda até o reset",
    "avail.ring_spent": "{time}  ·  esgotado",

    "card.usage": "Uso",
    "card.dongle": "Dongle",
    "card.visibility": "Visibilidade",
    "card.notifications": "Notificações",
    "card.language": "Idioma",
    "sec.forecast": "PREVISÃO",
    "sec.projects": "POR PROJETO",
    "sec.settings": "CONFIGURAÇÕES",
    "sec.hours": "POR HORA",
    "hours.hint": "Queima média por hora do dia · {days} dias observados",
    "hours.peak": "seu pico é por volta das {hour}h",
    "hours.empty": "histórico ainda insuficiente — volte em alguns dias",

    "acc.switched": "Conta trocada",
    "acc.reopen": "reabra o Claude Code para sincronizar o nome",

    "usage.session": "Sessão 5h",
    "usage.week": "Semana",
    "pace.high": "acelerado",
    "pace.low": "folgado",
    "pace.on": "no ritmo",
    "src.api": "API oficial",
    "src.none": "sem dado",
    "meta.stale": "dado velho",
    "meta.stale_age": "dado velho · há {age}",
    "meta.session_one": "1 sessão ativa",
    "meta.sessions": "{n} sessões ativas",
    "meta.extra_on": "uso extra ligado",

    "fc.session": "Sessão (5h)",
    "fc.week": "Semana",
    "fc.week_model": "Semana · {model}",
    "fc.rate": "{rate:+.1f} pp/h",
    "fc.collecting": "coletando dados…",
    "fc.steady": "ritmo estável · sem teto à vista",
    "fc.budget_before": "~{eta} de trabalho até o teto · o reset só vem em {reset}",
    "fc.budget_reset_first": "dá para chegar ao reset ({reset}) neste ritmo",
    "fc.budget_plain": "~{eta} de trabalho neste ritmo",
    "fc.overflow_before": "no ritmo atual estoura em {eta} · antes do reset ({reset})",
    "fc.overflow_low": "no ritmo recente estouraria em {eta} · uso ainda baixo",
    "fc.reset_first": "estoura em {eta} · o reset chega antes ({reset})",
    "fc.overflow_plain": "no ritmo atual estoura em {eta}",

    "pj.hint": "Tokens de saída · últimos 7 dias · contagem local",
    "pj.projects": "Projetos",
    "pj.models": "Modelos",
    "pj.last14": "Últimos 14 dias",
    "pj.collecting": "coletando dados locais…",
    "pj.heatmap_tip": "à direita = mais recente · tom = uso",

    "set.opacity": "Opacidade",
    "vis.always": "Sempre visível",
    "vis.claude": "Só com o Claude Code",
    "vis.dev": "Só com VS Code / terminal",
    "vis.custom": "Processos específicos",
    "notif.thresholds_hint": "Me avise quando um limite passar de",
    "notif.threshold_crossed": "Limite parcial atingido",
    "notif.limit_reached": "Limite estourado (100%)",
    "notif.overflow_forecast": "Previsão de estouro",
    "notif.limit_freed": "Limite liberado",
    "notif.telemetry_lost": "Perda da fonte de dados",
    "notif.gap_hint": "Intervalo mínimo entre avisos de rotina — limite estourado sempre passa",
    "notif.off": "Nunca",
    "notif.snooze_all": "Silenciar tudo",
    "notif.until_reset": "Até o reset",
    "notif.muted": "Silenciado · faltam {time}",
    "notif.resume": "Voltar",
    "btn.close": "Fechar",
    "btn.quit": "Encerrar o monitor",

    "n.session": "Sessão 5h",
    "n.week_all": "Semana geral",
    "n.week_model": "Semana {model}",
    "n.pct_title": "{label} · {pct}%",
    "n.resets_in": "Reseta em {time}",
    "n.limit_title": "{label} · 100%",
    "n.limit_body": "Limite estourado · reseta em {time}",
    "n.forecast_title": "{label} · previsão de estouro",
    "n.forecast_body": "{pct}% agora · +{rate} pp/h · estoura em {eta}, "
                       "antes do reset em {reset}",
    "n.freed_title": "{label} liberada",
    "n.freed_body": "o limite resetou · dá para voltar a trabalhar",
    "n.multi_title": "Limites de uso",
    "n.telemetry_title": "Sem telemetria de uso",
    "n.telemetry_body": "Nenhum dado novo há {time} — o token pode ter expirado "
                        "ou a API está indisponível.",
    "n.account_title": "Conta: {account}",
    "n.account_body": "Plano: {plan}",

    "tip.source": "Fonte: {src}",
    "tip.stale": " · dado velho",
    "tip.session": "Sessão 5h: {pct}% · reseta em {time}",
    "tip.week": "Semana geral: {pct}% · reseta em {time}",
    "tip.week_model": "Semana {model}: {pct}%",
    "tip.budget": "neste ritmo: ~{eta} de trabalho até o teto",
    "tip.overflow": "⚠ no ritmo atual, estoura antes do reset",
    "tip.actions": "clique: abre o painel · botão do meio: atualiza agora",

    "time.now": "agora",
}

_STRINGS = {"en": EN, "pt-BR": PT}
_current = DEFAULT


def resolve(setting):
    """Language code for a config value. 'auto' (the default) follows the
    system when we speak it, and falls back to English when we don't."""
    if setting and setting != "auto":
        return setting if setting in _STRINGS else DEFAULT
    tag = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    if not tag:
        try:
            tag = locale.getdefaultlocale()[0] or ""
        except (ValueError, TypeError):
            tag = ""
    return "pt-BR" if tag.lower().startswith("pt") else DEFAULT


def set_language(setting):
    global _current
    _current = resolve(setting)
    return _current


def language():
    return _current


def t(key, **kw):
    s = _STRINGS.get(_current, EN).get(key) or EN.get(key, key)
    return s.format(**kw) if kw else s
