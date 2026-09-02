from claude_dongle.usage_api import _normalize, _parse_iso


def test_parse_iso():
    assert _parse_iso(None) is None
    assert _parse_iso("not a date") is None
    assert isinstance(_parse_iso("2026-07-12T18:00:00+00:00"), int)


def test_normalize_basic_windows():
    body = {
        "five_hour": {"utilization": 42.5, "resets_at": "2026-07-12T20:00:00+00:00"},
        "seven_day": {"utilization": 61.0, "resets_at": "2026-07-16T18:00:00+00:00"},
    }
    out = _normalize(body)
    assert out["source"] == "api"
    assert out["pct_5h"] == 42.5
    assert out["pct_7d"] == 61.0
    assert out["reset_5h"] and out["reset_7d"]
    assert out["overage_enabled"] is False


def test_normalize_limits_override_and_breakdown():
    body = {
        "seven_day": {"utilization": 10.0, "resets_at": "2026-07-16T18:00:00+00:00"},
        "limits": [
            {"kind": "session", "percent": 77,
             "resets_at": "2026-07-12T20:00:00+00:00"},
            {"kind": "weekly_all", "group": "weekly", "percent": 55,
             "resets_at": "2026-07-16T18:00:00+00:00"},
            {"kind": "weekly_scoped", "group": "weekly", "percent": 80,
             "scope": {"model": {"display_name": "Fable"}},
             "resets_at": "2026-07-16T18:00:00+00:00"},
        ],
        "extra_usage": {"is_enabled": True},
    }
    out = _normalize(body)
    # limits[] wins over the plain windows; effective weekly = whichever bites first
    assert out["pct_5h"] == 77.0
    assert out["pct_7d"] == 80.0
    assert out["pct_7d_scope"] == "Fable"
    kinds = {w["kind"] for w in out["weekly_breakdown"]}
    assert kinds == {"weekly_all", "weekly_scoped"}
    assert out["overage_enabled"] is True


def test_normalize_empty_body():
    out = _normalize({})
    assert out["pct_5h"] is None
    assert out["pct_7d"] is None
    assert "weekly_breakdown" not in out


def test_normalize_marks_the_active_limit_and_locked_reason():
    body = {
        "five_hour": {"utilization": 3.0, "resets_at": "2026-09-03T01:30:00+00:00"},
        "seven_day": {"utilization": 71.0, "resets_at": "2026-09-04T21:00:00+00:00",
                      "locked_reason": "plan_paused"},
        "limits": [
            {"kind": "session", "group": "session", "percent": 3,
             "resets_at": "2026-09-03T01:30:00+00:00", "is_active": False},
            {"kind": "weekly_all", "group": "weekly", "percent": 71,
             "resets_at": "2026-09-04T21:00:00+00:00", "is_active": False},
            {"kind": "weekly_scoped", "group": "weekly", "percent": 100,
             "severity": "critical", "is_active": True,
             "scope": {"model": {"display_name": "Fable"}},
             "resets_at": "2026-09-04T21:00:00+00:00"},
        ],
    }
    out = _normalize(body)
    assert out["active_limit"] == "7d:Fable"
    assert [w["active"] for w in out["weekly_breakdown"]] == [False, True]
    assert out["locked"] == [{"label": "Week", "reason": "plan_paused"}]


def test_normalize_falls_back_to_top_level_weekly_keys():
    body = {
        "seven_day": {"utilization": 40.0, "resets_at": "2026-09-04T21:00:00+00:00"},
        "seven_day_opus": {"utilization": 88.0, "resets_at": None},
        "seven_day_sonnet": None,
        "limits": [
            {"kind": "weekly_all", "group": "weekly", "percent": 40,
             "resets_at": "2026-09-04T21:00:00+00:00"},
        ],
    }
    out = _normalize(body)
    models = {w["model"] for w in out["weekly_breakdown"]}
    assert models == {None, "Opus"}
    assert out["pct_7d"] == 88.0 and out["pct_7d_scope"] == "Opus"
    # no resets_at of its own → inherits the overall weekly reset
    opus = [w for w in out["weekly_breakdown"] if w["model"] == "Opus"][0]
    assert opus["reset"] == out["reset_7d"]


def test_normalize_top_level_key_does_not_duplicate_a_scoped_limit():
    body = {
        "seven_day_opus": {"utilization": 88.0},
        "limits": [
            {"kind": "weekly_scoped", "group": "weekly", "percent": 90,
             "scope": {"model": {"display_name": "Opus"}}},
        ],
    }
    out = _normalize(body)
    assert len(out["weekly_breakdown"]) == 1
    assert out["weekly_breakdown"][0]["pct"] == 90.0


def test_normalize_extra_usage_keeps_percentage_not_money():
    body = {
        "seven_day": {"utilization": 10.0},
        "extra_usage": {"is_enabled": True, "utilization": 34.0,
                        "used_credits": 1250, "currency": "USD",
                        "spend_limit_reached": False},
    }
    out = _normalize(body)
    assert out["extra"] == {"enabled": True, "pct": 34.0,
                            "limit_reached": False, "disabled_reason": None}
    assert "used_credits" not in out["extra"]


def test_normalize_without_extra_usage_omits_the_block():
    out = _normalize({"seven_day": {"utilization": 10.0}})
    assert "extra" not in out
    assert out["overage_enabled"] is False
