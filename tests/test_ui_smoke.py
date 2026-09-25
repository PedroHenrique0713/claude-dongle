"""Builds the real UI offscreen and checks behaviour, not pixels.

Runs on every OS in the ui-smoke job. Screenshots can't be compared across
platforms — the Windows runner has no fonts at all, so everything rasterises
as tofu there — but geometry, visibility and text content are the same
everywhere, and that is where a platform regression would show up.
"""
import os
import time

import pytest

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from claude_dongle import config, history, i18n, monitor, notifier, projects  # noqa: E402
from claude_dongle.utils import availability  # noqa: E402

NOW = time.time()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """No network, no notifications, no writing to the real config."""
    monkeypatch.setattr(notifier, "send", lambda *a, **k: None)
    monkeypatch.setattr(notifier, "check_thresholds", lambda *a, **k: False)
    monkeypatch.setattr(notifier, "check_telemetry", lambda *a, **k: False)
    monkeypatch.setattr(config, "save", lambda *a, **k: None)
    monkeypatch.setattr(config, "sync_live", lambda cfg: False)  # never the real file
    monkeypatch.setattr(history, "record", lambda *a, **k: None)
    monkeypatch.setattr(history, "attach_forecasts", lambda *a, **k: None)
    monkeypatch.setattr(history, "series", lambda *a, **k: [])
    monkeypatch.setattr(history, "hourly_profile",
                        lambda *a, **k: {"hours": [1.0] * 24, "days": 7, "peak": 15})
    monkeypatch.setattr(projects, "refresh", lambda *a, **k: 0)
    monkeypatch.setattr(projects, "summary",
                        lambda **k: {"models": [{"name": "claude-opus-5",
                                                 "output": 10, "total": 20}],
                                     "days": 7})
    monkeypatch.setattr(projects, "daily",
                        lambda days=14, **k: [("2026-09-01", 5)] * days)
    monkeypatch.setattr(monitor, "calc_usage", lambda cfg: _usage())
    yield
    i18n.set_language("en")


def _usage(pct_5h=8.0, week=72.0, fable=100.0):
    weekly = [{"kind": "weekly_all", "pct": week, "reset": NOW + 3600},
              {"kind": "weekly_scoped", "model": "Fable", "pct": fable,
               "reset": NOW + 3600}]
    return {
        "pct": max(week, fable), "pct_7d": max(week, fable), "pct_5h": pct_5h,
        "source": "api", "stale": False, "account": "Tester", "plan": "max",
        "email": "t@example.com", "account_changed": False, "identity_stale": False,
        "active_sessions": 1, "idle_sessions": 0,
        "seconds_until_reset": 3600, "seconds_until_reset_5h": 900,
        "reset_7d_epoch": NOW + 3600, "reset_5h_epoch": NOW + 900,
        "weekly_breakdown": weekly, "forecast": {},
        "availability": availability(pct_5h, weekly),
    }


def _cfg(**over):
    c = dict(config.DEFAULTS)
    c.update(language="en", dongle_pos=None, **over)
    return c


def test_dongle_builds_and_keeps_its_size(app):
    from claude_dongle.dongle import DongleWidget, DONGLE_W, DONGLE_H
    d = DongleWidget(_cfg(show_mode="always"))
    assert (d.width(), d.height()) == (DONGLE_W, DONGLE_H)
    tip = d.toolTip()
    assert "5h session" in tip and "Fable" in tip
    assert "spent" in tip          # the scoped limit is out, and the tip says so
    assert d._critical is False    # ...but the work isn't blocked
    d.close()


def test_dashboard_fits_the_screen_and_shows_what_is_spent(app):
    from claude_dongle.dashboard_ui import DashboardWidget
    w = DashboardWidget(_cfg(forecast_expanded=True, projects_expanded=True,
                             hours_expanded=True, settings_expanded=True))
    w.show()
    app.processEvents()
    assert w.width() == 440
    screen = w.screen()
    assert screen is not None, "no screen: the height cap can't be verified"
    avail = screen.availableGeometry().height()
    # The cap must actually be in place — comparing against the default
    # maximum (16777215) would pass no matter what the code did.
    assert w.maximumHeight() < 16777215
    assert w.maximumHeight() <= avail
    assert w.height() <= avail
    # ...and with every section open the content really is taller than the cap,
    # so this window IS the scrolling case, not a small panel that happens to fit
    assert w.scroll.widget().sizeHint().height() > w.height()
    assert w.scroll.verticalScrollBar().maximum() > 0
    assert w.avail.isVisible() and "Fable" in w.avail.text()
    assert w.meta.text().startswith("official API")
    w.close()


def test_language_switch_rebuilds_the_panel(app):
    from claude_dongle.dashboard_ui import DashboardWidget
    w = DashboardWidget(_cfg(settings_expanded=True))
    w.show()
    app.processEvents()
    assert "SETTINGS" in w.set_header.text()
    w._on_language("pt-BR")
    app.processEvents()
    assert "CONFIGURAÇÕES" in w.set_header.text()
    assert "esgotado" in w.avail.text()
    w.close()


def test_nothing_is_spent_hides_the_availability_line(app, monkeypatch):
    from claude_dongle.dashboard_ui import DashboardWidget
    monkeypatch.setattr(monitor, "calc_usage", lambda cfg: _usage(week=30.0, fable=20.0))
    w = DashboardWidget(_cfg())
    w.show()
    app.processEvents()
    assert not w.avail.isVisible()
    w.close()


def _codex(pct_5h=49.0, week=27.0):
    return {"pct_5h": pct_5h, "pct_7d": week, "reset_5h_epoch": NOW + 3000,
            "reset_7d_epoch": NOW + 500_000, "plan": "plus", "age_seconds": 60,
            "window_5h_min": 300, "window_7d_min": 10080}


def test_split_dongle_keeps_the_size_and_reports_both(app, monkeypatch):
    from claude_dongle import codex
    from claude_dongle.dongle import DongleWidget, DONGLE_W, DONGLE_H
    monkeypatch.setattr(codex, "read", lambda d: _codex())
    d = DongleWidget(_cfg(show_mode="always", sources="both"))
    assert (d.width(), d.height()) == (DONGLE_W, DONGLE_H)
    tip = d.toolTip()
    assert "Claude" in tip and "Codex · Plus" in tip and "Week: 27%" in tip
    assert d._countdown_secs() is None  # no room for one: it's in the tooltip
    assert d._critical is False
    d.grab()  # paints without raising
    # Codex out of session budget stops the Codex work: the border says so
    monkeypatch.setattr(codex, "read", lambda d: _codex(pct_5h=100.0))
    d.poll()
    assert d._critical is True
    d.close()


def test_codex_only_never_touches_the_claude_api(app, monkeypatch):
    from claude_dongle import codex
    from claude_dongle.dongle import DongleWidget
    monkeypatch.setattr(codex, "read", lambda d: _codex())

    def boom(cfg):
        raise AssertionError("Claude polled in codex-only mode")
    monkeypatch.setattr(monitor, "calc_usage", boom)
    d = DongleWidget(_cfg(show_mode="always", sources="codex"))
    assert "Codex · Plus" in d.toolTip() and "Claude ·" not in d.toolTip()
    assert d._countdown_secs() is not None  # single source: countdown is back
    d.grab()
    d.close()


def test_dashboard_codex_card_follows_the_source(app, monkeypatch):
    from claude_dongle import codex
    from claude_dongle.dashboard_ui import DashboardWidget
    monkeypatch.setattr(codex, "read", lambda d: _codex())
    w = DashboardWidget(_cfg())
    w.show()
    app.processEvents()
    assert not w.cx_card.isVisible()
    w._on_sources("both")
    app.processEvents()
    assert w.cx_card.isVisible()
    assert w.cx_5h._target_pct == 49.0 and w.cx_7d._target_pct == 27.0
    w.close()
