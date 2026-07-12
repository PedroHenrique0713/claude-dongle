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
