from claude_dongle import i18n


def test_resolve_auto_follows_the_system(monkeypatch):
    monkeypatch.setenv("LC_ALL", "pt_BR.UTF-8")
    assert i18n.resolve("auto") == "pt-BR"
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert i18n.resolve("auto") == "en"
    # a language we don't speak falls back to English, never to a raw code
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    assert i18n.resolve("auto") == "en"


def test_resolve_explicit_wins_over_the_system(monkeypatch):
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert i18n.resolve("pt-BR") == "pt-BR"
    assert i18n.resolve("nope") == "en"


def test_t_formats_and_falls_back_to_english():
    try:
        i18n.set_language("pt-BR")
        assert i18n.t("n.week_model", model="Fable") == "Semana Fable"
        # app.title has no translation on purpose (a product name)
        assert i18n.t("app.title") == "Claude Dongle"
        # an unknown key returns the key instead of raising
        assert i18n.t("does.not.exist") == "does.not.exist"
    finally:
        i18n.set_language("en")


def test_every_translated_key_exists_in_english():
    """A key only in a translation is dead weight — and usually a typo."""
    for code, table in i18n._STRINGS.items():
        extra = set(table) - set(i18n.EN)
        assert not extra, f"{code} has keys English doesn't: {sorted(extra)}"


def test_translations_use_the_same_placeholders():
    import re
    ph = lambda s: set(re.findall(r"{(\w+)", s))
    for code, table in i18n._STRINGS.items():
        for key, text in table.items():
            assert ph(text) == ph(i18n.EN[key]), f"{code}:{key} placeholders differ"
