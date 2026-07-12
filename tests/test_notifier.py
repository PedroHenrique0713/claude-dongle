import claude_dongle.notifier as notifier


def _usage(pct=60.0, pct_5h=None, w_epoch=1000, s_epoch=2000, forecast=None):
    return {
        "pct": pct, "pct_5h": pct_5h,
        "reset_7d_epoch": w_epoch, "reset_5h_epoch": s_epoch,
        "seconds_until_reset": 3600, "seconds_until_reset_5h": 600,
        "forecast": forecast or {},
    }


def _state(**over):
    st = {"thresholds": [50, 70, 85, 95], "notify_on_threshold": True,
          "notify_on_limit": True, "forecast_notify": True}
    st.update(over)
    return st


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(notifier, "send",
                        lambda title, msg, urgency="normal": calls.append(title))
    return calls


def test_multiple_thresholds_fire_once(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    # First read of the window crosses 50 and 70 at once → ONE notification
    assert notifier.check_thresholds(_usage(pct=72.0), _state(), sent) is True
    assert len(calls) == 1
    assert "72%" in calls[0]
    # Same state again → dedup, nothing new
    assert notifier.check_thresholds(_usage(pct=72.0), _state(), sent) is False
    assert len(calls) == 1


def test_limit_notification_at_100(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    notifier.check_thresholds(_usage(pct=100.0), _state(), sent)
    assert any("100%" in c for c in calls)
    n = len(calls)
    notifier.check_thresholds(_usage(pct=100.0), _state(), sent)
    assert len(calls) == n  # deduped


def test_new_window_resets_dedup(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    notifier.check_thresholds(_usage(pct=60.0, w_epoch=1000), _state(), sent)
    assert len(calls) == 1
    # New weekly window (fresh reset epoch) → old keys dropped, fires again
    notifier.check_thresholds(_usage(pct=60.0, w_epoch=9999), _state(), sent)
    assert len(calls) == 2


def test_forecast_notification_respects_floor(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    fc = {"7d": {"overflow_before_reset": True, "rate_pph": 5.0,
                 "eta_seconds": 1800}}
    # Below the 30% floor for weekly → no forecast alarm
    notifier.check_thresholds(_usage(pct=10.0, forecast=fc), _state(), sent)
    assert not any("overflow" in c for c in calls)
    # Above the floor → fires once
    notifier.check_thresholds(_usage(pct=45.0, forecast=fc), _state(), sent)
    assert any("overflow" in c for c in calls)


def test_none_pct_is_noop(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    assert notifier.check_thresholds(_usage(pct=None), _state(), sent) is False
    assert calls == []
