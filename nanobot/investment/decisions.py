"""Position-aware recommendation decisions for investment scans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from nanobot.investment.models import PositionRecord, TrancheState
from nanobot.investment.signals import TechnicalSignal

Action = Literal["buy", "add", "reduce", "sell", "hold", "watch"]

SELL_SIDE_SIGNAL_STATES = {"reduce", "exit"}
REDUCE_TARGETS: dict[TrancheState, TrancheState] = {
    "full": "add1",
    "add1": "entry",
}


@dataclass(frozen=True)
class Recommendation:
    symbol: str
    action: Action
    current_tranche: TrancheState
    target_tranche: TrancheState
    executable: bool
    reason: str
    invalidation: str
    risk_note: str


def decide_recommendation(
    *,
    symbol: str,
    kind: str,
    signal: TechnicalSignal,
    position: PositionRecord | None,
    as_of_date: str,
) -> Recommendation:
    del kind

    if position is None:
        if signal.state == "entry":
            return _build_recommendation(
                symbol=symbol,
                signal=signal,
                action="buy",
                current_tranche="flat",
                target_tranche="entry",
                executable=True,
            )
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="watch",
            current_tranche="flat",
            target_tranche="flat",
            executable=True,
        )

    executable = not (
        _is_same_natural_date(position.latest_buy_date, as_of_date)
        and signal.state in SELL_SIDE_SIGNAL_STATES
    )
    current_tranche = position.tranche_state

    if current_tranche == "flat":
        if signal.state == "entry":
            return _build_recommendation(
                symbol=symbol,
                signal=signal,
                action="buy",
                current_tranche=current_tranche,
                target_tranche="entry",
                executable=True,
            )
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="watch",
            current_tranche=current_tranche,
            target_tranche="flat",
            executable=True,
        )
    if signal.state == "exit":
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="sell",
            current_tranche=current_tranche,
            target_tranche="flat",
            executable=executable,
        )
    if signal.state == "reduce":
        target_tranche = REDUCE_TARGETS.get(current_tranche)
        if target_tranche is None:
            return _build_recommendation(
                symbol=symbol,
                signal=signal,
                action="sell",
                current_tranche=current_tranche,
                target_tranche="flat",
                executable=executable,
            )
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="reduce",
            current_tranche=current_tranche,
            target_tranche=target_tranche,
            executable=executable,
        )
    if signal.state == "entry" and current_tranche == "entry":
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="add",
            current_tranche=current_tranche,
            target_tranche="add1",
            executable=True,
        )
    if signal.state == "entry" and current_tranche == "add1":
        return _build_recommendation(
            symbol=symbol,
            signal=signal,
            action="add",
            current_tranche=current_tranche,
            target_tranche="full",
            executable=True,
        )

    return _build_recommendation(
        symbol=symbol,
        signal=signal,
        action="hold",
        current_tranche=current_tranche,
        target_tranche=current_tranche,
        executable=True,
    )


def _build_recommendation(
    *,
    symbol: str,
    signal: TechnicalSignal,
    action: Action,
    current_tranche: TrancheState,
    target_tranche: TrancheState,
    executable: bool,
) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        action=action,
        current_tranche=current_tranche,
        target_tranche=target_tranche,
        executable=executable,
        reason=signal.reason,
        invalidation=signal.invalidation,
        risk_note=signal.risk_note,
    )


def _is_same_natural_date(left: str, right: str) -> bool:
    left_date = _parse_natural_date(left)
    right_date = _parse_natural_date(right)
    return left_date is not None and left_date == right_date


def _parse_natural_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
