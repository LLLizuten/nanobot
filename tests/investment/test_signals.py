from datetime import datetime, timedelta

import pytest

from nanobot.investment.market import Bar
from nanobot.investment.signals import evaluate_trend_breakout


def _make_bars(
    *,
    complete_tail: bool = True,
    last_close: float | None = None,
    last_volume: float | None = None,
) -> list[Bar]:
    start = datetime(2026, 4, 26, 9, 30)
    closes = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.7, 11.1]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    bars: list[Bar] = []

    if last_close is not None:
        closes[-1] = last_close
    if last_volume is not None:
        volumes[-1] = last_volume

    for idx, (close, volume) in enumerate(zip(closes, volumes)):
        bars.append(
            Bar(
                symbol="510300",
                kind="etf",
                ends_at=start + timedelta(hours=idx),
                open=close - 0.1,
                high=close + 0.1,
                low=close - 0.15,
                close=close,
                volume=volume,
                complete=True,
            )
        )

    if not complete_tail:
        bars[-1].complete = False

    return bars


def test_returns_watch_when_completed_bars_are_insufficient() -> None:
    signal = evaluate_trend_breakout(_make_bars(complete_tail=False), mode="balanced")

    assert signal.state == "watch"
    assert "completed bars" in signal.reason.lower()


def test_balanced_mode_emits_entry_signal_on_breakout() -> None:
    signal = evaluate_trend_breakout(_make_bars(), mode="balanced")

    assert signal.state == "entry"
    assert "breakout" in signal.reason.lower()


def test_conservative_mode_requires_stronger_confirmation() -> None:
    bars = _make_bars(last_close=10.82, last_volume=200)
    balanced_signal = evaluate_trend_breakout(bars, mode="balanced")
    conservative_signal = evaluate_trend_breakout(bars, mode="conservative")

    assert balanced_signal.state == "entry"
    assert conservative_signal.state == "watch"


def test_aggressive_mode_accepts_softer_breakout_and_volume_confirmation() -> None:
    bars = _make_bars(last_close=10.79, last_volume=120)
    balanced_signal = evaluate_trend_breakout(bars, mode="balanced")
    aggressive_signal = evaluate_trend_breakout(bars, mode="aggressive")

    assert balanced_signal.state == "watch"
    assert aggressive_signal.state == "entry"


def test_returns_watch_when_breakout_conditions_are_incomplete() -> None:
    signal = evaluate_trend_breakout(_make_bars(last_close=10.79, last_volume=200), mode="balanced")

    assert signal.state == "watch"
    assert "incomplete" in signal.reason.lower()


def test_returns_watch_when_volume_confirmation_fails() -> None:
    signal = evaluate_trend_breakout(_make_bars(last_volume=130), mode="balanced")

    assert signal.state == "watch"
    assert "incomplete" in signal.reason.lower()


def test_returns_watch_when_trend_confirmation_fails() -> None:
    start = datetime(2026, 4, 26, 9, 30)
    closes = [11.0, 11.0, 11.0, 11.0, 11.0, 10.0, 10.0, 10.0, 10.0, 10.0, 11.2]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    bars = [
        Bar(
            symbol="510300",
            kind="etf",
            ends_at=start + timedelta(hours=idx),
            open=close - 0.1,
            high=close + 0.1,
            low=close - 0.15,
            close=close,
            volume=volume,
            complete=True,
        )
        for idx, (close, volume) in enumerate(zip(closes, volumes))
    ]

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "watch"
    assert "incomplete" in signal.reason.lower()


def test_invalid_mode_raises_clear_value_error() -> None:
    with pytest.raises(ValueError, match="invalid risk mode"):
        evaluate_trend_breakout(_make_bars(), mode="intraday")
