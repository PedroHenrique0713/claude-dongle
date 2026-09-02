from claude_dongle.utils import color, fmt_time


def test_fmt_time():
    assert fmt_time(None) == "--"
    assert fmt_time(0) == "now"
    assert fmt_time(120) == "2m"
    assert fmt_time(3600) == "1h"
    assert fmt_time(3720) == "1h02"
    assert fmt_time(86400) == "1d"
    assert fmt_time(90000) == "1d 1h"


def test_color_ramp():
    assert color(10) != color(60) != color(85) != color(99)
    assert color(95) == color(100)


def test_limits_blocking_ignores_a_scoped_model():
    from claude_dongle.utils import limits_blocking
    # Fable exhausted while the session and the overall week still have room:
    # the other models keep working → not blocking
    assert limits_blocking(8.0, 72.0) is False
    # the overall week gone → nothing runs
    assert limits_blocking(8.0, 100.0) is True
    # the 5h session gone → nothing runs either
    assert limits_blocking(100.0, 30.0) is True
    # 95% is high but still usable: red is reserved for a full stop
    assert limits_blocking(96.0, 99.0) is False
    assert limits_blocking(None, None) is False


def test_availability_separates_a_scoped_limit_from_a_total_stop():
    from claude_dongle.utils import availability
    weekly = [{"kind": "weekly_all", "pct": 72.0, "reset": 111},
              {"kind": "weekly_scoped", "model": "Fable", "pct": 100.0, "reset": 111}]
    a = availability(8.0, weekly)
    assert a["everything_blocked"] is False
    assert [b["scope"] for b in a["blocked"]] == ["Fable"]
    # the overall week gone: nothing runs
    a = availability(8.0, [{"kind": "weekly_all", "pct": 100.0, "reset": 111}])
    assert a["everything_blocked"] is True
    # the session gone blocks everything too
    assert availability(100.0, weekly)["everything_blocked"] is True
    # nothing spent
    assert availability(10.0, [{"kind": "weekly_all", "pct": 20.0}]) == {
        "blocked": [], "everything_blocked": False}
