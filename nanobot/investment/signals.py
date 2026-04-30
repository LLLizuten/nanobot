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
FAILED_BREAKOUT_LOOKBACK_BARS: Final[int] = 10


@dataclass(frozen=True)
class TechnicalSignal:
    state: SignalState
    reason: str
    invalidation: str
    risk_note: str


def _latest_breakout_reference(rows: list[Bar], breakout_buffer: float) -> float | None:
    first_candidate_idx = max(1, len(rows) - FAILED_BREAKOUT_LOOKBACK_BARS - 2)
    last_candidate_idx = len(rows) - 3

    for idx in range(last_candidate_idx, first_candidate_idx - 1, -1):
        reference_window = rows[max(0, idx - 10) : idx]
        reference = max(bar.high for bar in reference_window)
        if rows[idx].close >= reference * (1 + breakout_buffer):
            return reference

    return None


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
    previous = rows[-2]
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
    failed_breakout_reference = _latest_breakout_reference(rows, thresholds["breakout_buffer"])
    failed_breakout_confirmed = (
        failed_breakout_reference is not None
        and previous.close < failed_breakout_reference
        and latest.close < failed_breakout_reference
    )
    medium_trend_broken = latest.close < medium_ma and short_ma < medium_ma
    short_support_lost = latest.close < short_ma and latest.close >= medium_ma
    latest_range = latest.high - latest.low
    weak_range_close = latest_range > 0 and latest.close <= latest.low + latest_range * 0.4
    momentum_fading = latest.volume >= avg_volume * 1.2 and weak_range_close
    trend_healthy = latest.close >= short_ma >= medium_ma

    if latest.close >= breakout_level and volume_confirmed and trend_confirmed:
        return TechnicalSignal(
            state="entry",
            reason="breakout above recent range with volume and trend confirmation",
            invalidation="lose the breakout level on completed bars",
            risk_note="突破失败时通常会快速回落",
        )

    if failed_breakout_confirmed:
        return TechnicalSignal(
            state="exit",
            reason="two completed closes failed below the breakout reference",
            invalidation="reclaim the breakout reference on completed bars",
            risk_note="突破失败可能导致趋势快速转弱",
        )

    if medium_trend_broken:
        return TechnicalSignal(
            state="exit",
            reason="price and short moving average lost the medium moving average",
            invalidation="reclaim the medium moving average with improving short-term trend",
            risk_note="中期趋势失守时应优先控制回撤",
        )

    if short_support_lost:
        return TechnicalSignal(
            state="reduce",
            reason="latest close lost the short moving average while holding the medium moving average",
            invalidation="recover the short moving average on completed bars",
            risk_note="短线转弱但中期结构尚未完全破坏",
        )

    if momentum_fading:
        return TechnicalSignal(
            state="reduce",
            reason="high-volume weak close suggests momentum is fading",
            invalidation="recover with a strong close and normalized volume",
            risk_note="放量弱收可能意味着突破动能衰减",
        )

    if trend_healthy:
        return TechnicalSignal(
            state="hold",
            reason="trend remains healthy without a fresh breakout signal",
            invalidation="lose the short moving average or show failed breakout behavior",
            risk_note="趋势仍健康，但未出现新的加仓确认",
        )

    return TechnicalSignal(
        state="watch",
        reason="breakout conditions are incomplete",
        invalidation="n/a",
        risk_note="继续等待完整结构确认",
    )
