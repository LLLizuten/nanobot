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


def _bars_from_closes(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[Bar]:
    start = datetime(2026, 4, 26, 9, 30)
    if volumes is None:
        volumes = [100.0] * len(closes)
    if highs is None:
        highs = [close + 0.1 for close in closes]
    if lows is None:
        lows = [close - 0.1 for close in closes]

    return [
        Bar(
            symbol="510300",
            kind="etf",
            ends_at=start + timedelta(hours=idx),
            open=close,
            high=highs[idx],
            low=lows[idx],
            close=close,
            volume=volumes[idx],
            complete=True,
        )
        for idx, close in enumerate(closes)
    ]


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
    assert conservative_signal.state == "hold"


def test_aggressive_mode_accepts_softer_breakout_and_volume_confirmation() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.8, 10.79],
        highs=[10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.65, 10.7, 10.75, 10.8, 10.89],
        volumes=[100.0] * 10 + [120.0],
    )
    balanced_signal = evaluate_trend_breakout(bars, mode="balanced")
    aggressive_signal = evaluate_trend_breakout(bars, mode="aggressive")

    assert balanced_signal.state == "hold"
    assert aggressive_signal.state == "entry"


def test_returns_watch_when_breakout_conditions_are_incomplete() -> None:
    bars = _bars_from_closes(
        [10.0, 10.0, 10.0, 10.0, 10.0, 11.0, 11.0, 11.0, 11.0, 11.0, 10.2],
        highs=[10.1, 10.1, 10.1, 10.1, 10.1, 11.0, 11.0, 11.0, 11.0, 11.0, 10.3],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "watch"
    assert "incomplete" in signal.reason.lower()


def test_returns_hold_when_breakout_volume_confirmation_fails_but_trend_is_healthy() -> None:
    signal = evaluate_trend_breakout(_make_bars(last_volume=130), mode="balanced")

    assert signal.state == "hold"
    assert "trend remains healthy" in signal.reason.lower()


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


def test_returns_hold_when_trend_remains_healthy_without_new_breakout() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.95],
        highs=[10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.9, 11.0],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "hold"
    assert "trend remains healthy" in signal.reason.lower()


def test_returns_hold_when_healthy_trend_is_below_recent_high_without_prior_breakout() -> None:
    bars = _bars_from_closes(
        [10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.4, 11.6, 11.8, 12.0],
        highs=[10.1, 10.3, 10.5, 10.7, 10.9, 11.1, 11.3, 11.5, 12.5, 12.4, 12.3],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "hold"
    assert "trend remains healthy" in signal.reason.lower()


def test_returns_reduce_when_latest_close_loses_short_average_but_holds_medium_average() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 11.0, 11.0, 11.0, 11.0, 11.0, 10.8],
        volumes=[100.0] * 11,
        highs=[10.1, 10.2, 10.3, 10.4, 10.5, 11.0, 11.0, 11.0, 11.0, 11.0, 10.9],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "reduce"
    assert "short moving average" in signal.reason.lower()


def test_returns_reduce_when_high_volume_weak_close_shows_momentum_fading() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.85],
        volumes=[100.0] * 10 + [150.0],
        highs=[10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.9, 11.2],
        lows=[9.9, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.8],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "reduce"
    assert "momentum" in signal.reason.lower()


def test_returns_exit_when_price_and_short_average_lose_medium_average() -> None:
    bars = _bars_from_closes(
        [11.0, 11.0, 11.0, 11.0, 11.0, 9.0, 9.0, 9.0, 9.0, 11.0, 9.0],
        volumes=[100.0] * 11,
        highs=[11.0, 11.0, 11.0, 11.0, 11.0, 9.1, 9.1, 9.1, 9.1, 11.0, 9.1],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "exit"
    assert "medium moving average" in signal.reason.lower()


def test_returns_exit_when_two_completed_closes_fail_below_breakout_reference() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.95, 10.75, 10.65],
        volumes=[100.0] * 11,
        highs=[10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.1, 10.9, 10.8],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "exit"
    assert "breakout reference" in signal.reason.lower()


def test_ignores_stale_breakout_when_recent_bars_do_not_fail_it() -> None:
    bars = _bars_from_closes(
        [
            10.0,
            10.1,
            10.2,
            10.3,
            10.4,
            12.1,
            10.2,
            10.25,
            10.3,
            10.35,
            10.4,
            10.45,
            10.5,
            10.55,
            10.6,
            10.65,
            10.7,
            10.75,
        ],
        volumes=[100.0] * 18,
        highs=[
            10.1,
            10.2,
            10.3,
            10.4,
            12.0,
            12.2,
            10.3,
            10.35,
            10.4,
            10.45,
            10.5,
            10.55,
            10.6,
            10.65,
            10.7,
            10.75,
            10.8,
            10.85,
        ],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "hold"
    assert "trend remains healthy" in signal.reason.lower()


def test_invalid_mode_raises_clear_value_error() -> None:
    with pytest.raises(ValueError, match="invalid risk mode"):
        evaluate_trend_breakout(_make_bars(), mode="intraday")
