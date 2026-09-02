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
    st = _state(notify_cooldown_minutes=0)
    notifier.check_thresholds(_usage(pct=60.0, w_epoch=1000), st, sent)
    assert len(calls) == 1
    # New weekly window (fresh reset epoch) → old keys dropped, fires again
    notifier.check_thresholds(_usage(pct=60.0, w_epoch=9999), st, sent)
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


def test_one_notification_per_reading_even_with_several_buckets(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(notifier, "send",
                        lambda t, m, urgency="normal": calls.append((t, m)))
    sent = str(tmp_path / "sent.json")
    # session and week cross a threshold in the same reading
    notifier.check_thresholds(_usage(pct=72.0, pct_5h=88.0), _state(), sent)
    assert len(calls) == 1
    assert "5h session" in calls[0][1] and "Overall week" in calls[0][1]


def test_cooldown_paces_routine_alerts_but_not_critical(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    st = _state(notify_cooldown_minutes=60)
    notifier.check_thresholds(_usage(pct=55.0), st, sent)
    assert len(calls) == 1
    # another routine threshold right after → held back by the cooldown
    notifier.check_thresholds(_usage(pct=72.0), st, sent)
    assert len(calls) == 1
    # hitting the limit is critical → goes out despite the cooldown
    notifier.check_thresholds(_usage(pct=100.0), st, sent)
    assert any("100%" in c for c in calls)


def test_repeated_100_percent_notifies_once_per_window(tmp_path, monkeypatch):
    """The Fable case: staying at 100% must not re-alert on every poll."""
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    for _ in range(20):
        notifier.check_thresholds(_usage(pct=100.0), _state(), sent)
    assert len([c for c in calls if "100%" in c]) == 1


def test_mute_silences_and_expires(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    notifier.mute(sent, 30)
    assert notifier.muted_until(sent) > 0
    notifier.check_thresholds(_usage(pct=100.0), _state(), sent)
    assert calls == []
    notifier.mute(sent, 0)
    assert notifier.muted_until(sent) == 0


def test_legacy_list_state_is_read_and_upgraded(tmp_path, monkeypatch):
    import json
    calls = _capture(monkeypatch)
    sent = tmp_path / "sent.json"
    # pre-cooldown format: a bare list of keys already sent
    sent.write_text(json.dumps(["w1000:all:50"]))
    notifier.check_thresholds(_usage(pct=55.0), _state(), str(sent))
    assert calls == []  # the 50 key was honoured, nothing new crossed
    assert isinstance(json.loads(sent.read_text()), dict)


def test_upgrade_does_not_realert_when_the_epoch_was_off_by_a_second(tmp_path, monkeypatch):
    """Pre-rounding state used the truncated epoch (X-1); adopt it instead of
    treating the window as new."""
    import json
    calls = _capture(monkeypatch)
    sent = tmp_path / "sent.json"
    sent.write_text(json.dumps(["w999:all:50", "w999:all:limit"]))
    notifier.check_thresholds(_usage(pct=100.0, w_epoch=1000), _state(), str(sent))
    assert calls == []
    assert "w1000:all:limit" in json.loads(sent.read_text())["keys"]


def test_notifications_follow_the_configured_language(tmp_path, monkeypatch):
    from claude_dongle import i18n
    calls = []
    monkeypatch.setattr(notifier, "send",
                        lambda t, m, urgency="normal": calls.append((t, m)))
    sent = str(tmp_path / "sent.json")
    try:
        i18n.set_language("pt-BR")
        notifier.check_thresholds(_usage(pct=100.0), _state(), sent)
        title, body = calls[0]
        assert "Semana geral · 100%" == title
        assert body.startswith("Limite estourado · reseta em")
    finally:
        i18n.set_language("en")
    # back in English the same reading reads in English
    calls.clear()
    notifier.check_thresholds(_usage(pct=100.0, w_epoch=2000),
                              _state(), str(tmp_path / "sent2.json"))
    assert calls[0][0] == "Overall week · 100%"


def _weekly(pct_all, scoped=None, reset=1000):
    out = [{"kind": "weekly_all", "pct": pct_all, "reset": reset}]
    for model, pct in (scoped or {}).items():
        out.append({"kind": "weekly_scoped", "model": model, "pct": pct,
                    "reset": reset})
    return out


def test_notifies_once_when_a_spent_limit_comes_back(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    st = _state(notify_cooldown_minutes=0)
    spent = _usage(pct=100.0, w_epoch=1000)
    spent["weekly_breakdown"] = _weekly(40.0, {"Fable": 100.0}, reset=1000)
    notifier.check_thresholds(spent, st, sent)
    assert any("100%" in c for c in calls)
    calls.clear()
    # same window, still spent → nothing new
    notifier.check_thresholds(spent, st, sent)
    assert calls == []
    # the week rolled over and Fable is under the limit again
    back = _usage(pct=12.0, w_epoch=9999)
    back["weekly_breakdown"] = _weekly(12.0, {"Fable": 5.0}, reset=9999)
    notifier.check_thresholds(back, st, sent)
    assert any("is back" in c for c in calls)
    calls.clear()
    notifier.check_thresholds(back, st, sent)
    assert not any("is back" in c for c in calls)  # said once


def test_limit_back_can_be_turned_off(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    sent = str(tmp_path / "sent.json")
    st = _state(notify_cooldown_minutes=0, notify_on_reset=False)
    u = _usage(pct=100.0, w_epoch=1000)
    u["weekly_breakdown"] = _weekly(100.0, reset=1000)
    notifier.check_thresholds(u, st, sent)
    calls.clear()
    back = _usage(pct=10.0, w_epoch=9999)
    back["weekly_breakdown"] = _weekly(10.0, reset=9999)
    notifier.check_thresholds(back, st, sent)
    assert not any("is back" in c for c in calls)


def test_send_uses_the_right_native_channel_per_platform(monkeypatch):
    """The three notification paths only ever run on their own OS, so the one
    thing CI can check is that each builds a sane command."""
    seen = {}
    monkeypatch.setattr(notifier.subprocess, "run",
                        lambda cmd, **k: seen.setdefault("cmd", cmd))
    monkeypatch.setattr(notifier.subprocess, "Popen",
                        lambda cmd, **k: seen.setdefault("cmd", cmd))

    monkeypatch.setattr(notifier.sys, "platform", "linux")
    notifier.send("Title", "Body", "critical")
    assert seen["cmd"][:2] == ["notify-send", "-a"]
    assert seen["cmd"][-2:] == ["Title", "Body"]
    assert "critical" in seen["cmd"]

    seen.clear()
    monkeypatch.setattr(notifier.sys, "platform", "darwin")
    notifier.send('say "hi"', "Body")
    assert seen["cmd"][0] == "osascript"
    # quotes are escaped, or the AppleScript would end early and fail
    assert '\\"hi\\"' in seen["cmd"][-1]

    seen.clear()
    monkeypatch.setattr(notifier.sys, "platform", "win32")
    notifier.send("Title", "Body")
    assert seen["cmd"][0] == "powershell"


def test_send_never_raises_when_the_channel_is_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("notify-send not installed")

    monkeypatch.setattr(notifier.subprocess, "run", boom)
    monkeypatch.setattr(notifier.sys, "platform", "linux")
    notifier.send("Title", "Body")  # must not propagate
