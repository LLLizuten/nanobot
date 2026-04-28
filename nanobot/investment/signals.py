"""Technical signal evaluators for investment scans."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Final, Literal

from .market import Bar, completed_bars_only

RiskMode = Literal["conservative", "balanced", "aggressive"]
SignalState = Literal["watch", "entry", "hold", "reduce", "exit"]

MODE_THRESHOLDS: Final[dict[RiskMode, dict[str, float]]] = {
    "conservative": {
        "volume_ratio": 1.5,
        "breakout_buffer": 0.003,
    },
    "balanced": {
        "volume_ratio": 1.2,
        "breakout_buffer": 0.0,
    },
    "aggressive": {
        "volume_ratio": 1.0,
        "breakout_buffer": -0.002,
    },
}


@dataclass(frozen=True)
class TechnicalSignal:
    state: SignalState
    reason: str
    invalidation: str
    risk_note: str


def evaluate_trend_breakout(bars: list[Bar], mode: RiskMode) -> TechnicalSignal:
    rows = completed_bars_only(bars)
    if len(rows) < 11:
        return TechnicalSignal(
            state="watch",
            reason="not enough completed bars for breakout evaluation",
            invalidation="n/a",
            risk_note="等待更多完整 K 线确认趋势",
        )

    latest = rows[-1]
    recent_window = rows[-11:-1]
    recent_high = max(bar.high for bar in recent_window)
    short_ma = mean(bar.close for bar in rows[-5:])
    medium_ma = mean(bar.close for bar in rows[-10:])
    avg_volume = mean(bar.volume for bar in rows[-6:-1])
    thresholds = MODE_THRESHOLDS.get(mode)
    if thresholds is None:
        raise ValueError(f"invalid risk mode: {mode}")

    breakout_level = recent_high * (1 + thresholds["breakout_buffer"])
    volume_confirmed = latest.volume >= avg_volume * thresholds["volume_ratio"]
    trend_confirmed = latest.close >= short_ma >= medium_ma

    if latest.close >= breakout_level and volume_confirmed and trend_confirmed:
        return TechnicalSignal(
            state="entry",
            reason="breakout above recent range with volume and trend confirmation",
            invalidation="lose the breakout level on completed bars",
            risk_note="突破失败时通常会快速回落",
        )

    return TechnicalSignal(
        state="watch",
        reason="breakout conditions are incomplete",
        invalidation="n/a",
        risk_note="继续等待完整结构确认",
    )
