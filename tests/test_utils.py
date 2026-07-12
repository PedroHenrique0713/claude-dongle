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
