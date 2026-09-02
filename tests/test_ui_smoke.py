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
    monkeypatch.setattr(projects, "daily", lambda days=14: [("2026-09-01", 5)] * days)
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
    assert w.height() <= w.maximumHeight()
    screen = w.screen()
    if screen is not None:
        assert w.height() <= screen.availableGeometry().height()
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
