import sqlite3
import time
from datetime import datetime

from claude_dongle import history


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DB_PATH", tmp_path / "h.db")
    monkeypatch.setattr(history, "_local", type("L", (), {})())
    monkeypatch.setattr(history.config, "CONFIG_DIR", tmp_path)
    return history._conn()


def _at(day, hour, minute=0):
    return int(datetime(2026, 9, day, hour, minute).timestamp())


def test_hourly_profile_credits_the_burn_to_the_hour(tmp_path, monkeypatch):
    c = _db(tmp_path, monkeypatch)
    rows = [
        # one window: 10% at 14h, 30% at 15h, 35% at 16h
        ("5h", 5000, _at(1, 14), 10.0, "", "api"),
        ("5h", 5000, _at(1, 15), 30.0, "", "api"),
        ("5h", 5000, _at(1, 16), 35.0, "", "api"),
    ]
    c.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    prof = history.hourly_profile(days=30, now=_at(2, 0))
    assert prof["days"] == 1
    assert prof["hours"][15] == 20.0   # the jump landed at 15h
    assert prof["hours"][16] == 5.0
    assert prof["hours"][14] == 0.0    # first sample of a chain has no delta
    assert prof["peak"] == 15


def test_hourly_profile_does_not_chain_across_a_window_reset(tmp_path, monkeypatch):
    c = _db(tmp_path, monkeypatch)
    c.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", [
        ("5h", 5000, _at(1, 20), 90.0, "", "api"),
        ("5h", 6000, _at(1, 21), 5.0, "", "api"),   # new window: back near zero
        ("5h", 6000, _at(1, 22), 12.0, "", "api"),
    ])
    c.commit()
    prof = history.hourly_profile(days=30, now=_at(2, 0))
    assert prof["hours"][21] == 0.0    # the drop is not burn, and not negative
    assert prof["hours"][22] == 7.0


def test_hourly_profile_averages_over_observed_days_only(tmp_path, monkeypatch):
    c = _db(tmp_path, monkeypatch)
    c.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", [
        ("5h", 5000, _at(1, 10), 0.0, "", "api"),
        ("5h", 5000, _at(1, 11), 10.0, "", "api"),
        ("5h", 7000, _at(2, 10), 0.0, "", "api"),
        ("5h", 7000, _at(2, 11), 20.0, "", "api"),
    ])
    c.commit()
    prof = history.hourly_profile(days=30, now=_at(3, 0))
    assert prof["days"] == 2
    assert prof["hours"][11] == 15.0   # (10 + 20) / 2 days, not / 30


def test_hourly_profile_survives_an_empty_database(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    prof = history.hourly_profile(days=14)
    assert prof == {"hours": [0.0] * 24, "days": 0, "peak": None}
