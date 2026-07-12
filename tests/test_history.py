from claude_dongle.history import burn_rate, forecast, MIN_RATE_PPH


def test_burn_rate_linear():
    now = 100_000
    # 10 pp/h: one point every 600s climbing ~1.67pp
    pts = [(now - 3600 + i * 600, 50 + i * (10 / 6)) for i in range(7)]
    rate = burn_rate(pts, now=now)
    assert rate is not None
    assert abs(rate - 10.0) < 0.01


def test_burn_rate_needs_points_and_span():
    now = 100_000
    assert burn_rate([(now - 100, 50.0), (now - 50, 51.0)], now=now) is None
    # Enough points but span shorter than min_span_s
    pts = [(now - 300 + i * 50, 50.0 + i) for i in range(5)]
    assert burn_rate(pts, now=now) is None


def test_forecast_overflow_before_reset():
    now = 100_000
    fc = forecast(90.0, now, rate_pph=10.0, seconds_until_reset=7200, now=now)
    # 10pp left at 10pp/h → ~1h ETA, reset in 2h → overflows first
    assert fc["overflow_before_reset"] is True
    assert 3500 <= fc["eta_seconds"] <= 3700


def test_forecast_flat_pace_no_alarm():
    now = 100_000
    fc = forecast(99.0, now, rate_pph=MIN_RATE_PPH, seconds_until_reset=60, now=now)
    assert fc["eta_seconds"] is None
    assert fc["overflow_before_reset"] is None
