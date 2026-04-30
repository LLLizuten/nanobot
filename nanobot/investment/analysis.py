"""Shared investment analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from nanobot.investment.decisions import Recommendation, decide_recommendation
from nanobot.investment.market import Bar
from nanobot.investment.models import PositionRecord, RiskMode
from nanobot.investment.signals import evaluate_trend_breakout


@dataclass(frozen=True)
class AnalysisResult:
    symbol: str
    kind: str
    latest_bar_ends_at: datetime
    recommendation: Recommendation


def analyze_symbol(
    *,
    market_data,
    symbol: str,
    kind: str,
    period_minutes: int,
    mode: RiskMode,
    position: PositionRecord | None,
    limit: int = 120,
) -> AnalysisResult | None:
    """Fetch completed bars and translate them into a position-aware recommendation."""
    bars = market_data.fetch_completed_bars(
        symbol=symbol,
        kind=kind,
        period_minutes=period_minutes,
        limit=limit,
    )
    if not bars:
        return None

    latest_bar = _latest_completed_bar(bars)
    if latest_bar is None:
        return None

    signal = evaluate_trend_breakout(bars, mode=mode)
    recommendation = decide_recommendation(
        symbol=symbol,
        kind=kind,
        signal=signal,
        position=position,
        as_of_date=latest_bar.ends_at.date().isoformat(),
    )
    return AnalysisResult(
        symbol=symbol,
        kind=kind,
        latest_bar_ends_at=latest_bar.ends_at,
        recommendation=recommendation,
    )


def _latest_completed_bar(bars: list[Bar]) -> Bar | None:
    for bar in reversed(bars):
        if bar.complete:
            return bar
    return None
