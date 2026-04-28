import pytest

from nanobot.investment.decisions import decide_recommendation
from nanobot.investment.models import PositionRecord
from nanobot.investment.signals import TechnicalSignal


def _position(
    *,
    tranche_state: str = "entry",
    latest_buy_date: str = "2026-04-25",
) -> PositionRecord:
    return PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1788.0,
        tranche_state=tranche_state,
        latest_buy_date=latest_buy_date,
        shares=100,
    )


def _signal(state: str) -> TechnicalSignal:
    return TechnicalSignal(
        state=state,
        reason=f"{state} reason",
        invalidation=f"{state} invalidation",
        risk_note=f"{state} risk",
    )


def test_entry_signal_without_position_becomes_buy() -> None:
    rec = decide_recommendation(
        symbol="510300",
        kind="etf",
        signal=_signal("entry"),
        position=None,
        as_of_date="2026-04-26",
    )

    assert rec.symbol == "510300"
    assert rec.action == "buy"
    assert rec.current_tranche == "flat"
    assert rec.target_tranche == "entry"
    assert rec.executable is True


def test_entry_signal_with_flat_position_becomes_buy() -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("entry"),
        position=_position(tranche_state="flat"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "buy"
    assert rec.current_tranche == "flat"
    assert rec.target_tranche == "entry"
    assert rec.executable is True


@pytest.mark.parametrize("state", ["watch", "hold", "reduce", "exit"])
def test_non_entry_signal_with_flat_position_becomes_watch(state: str) -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal(state),
        position=_position(tranche_state="flat"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "watch"
    assert rec.current_tranche == "flat"
    assert rec.target_tranche == "flat"
    assert rec.executable is True


@pytest.mark.parametrize("state", ["watch", "hold", "reduce", "exit"])
def test_non_entry_signal_without_position_becomes_watch(state: str) -> None:
    rec = decide_recommendation(
        symbol="510300",
        kind="etf",
        signal=_signal(state),
        position=None,
        as_of_date="2026-04-26",
    )

    assert rec.action == "watch"
    assert rec.current_tranche == "flat"
    assert rec.target_tranche == "flat"
    assert rec.executable is True


def test_exit_signal_with_position_becomes_sell_to_flat() -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("exit"),
        position=_position(tranche_state="entry"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "sell"
    assert rec.current_tranche == "entry"
    assert rec.target_tranche == "flat"
    assert rec.executable is True


def test_reduce_signal_with_full_position_reduces_one_tranche() -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("reduce"),
        position=_position(tranche_state="full"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "reduce"
    assert rec.current_tranche == "full"
    assert rec.target_tranche == "add1"
    assert rec.executable is True


def test_reduce_signal_with_add1_position_reduces_to_entry() -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("reduce"),
        position=_position(tranche_state="add1"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "reduce"
    assert rec.current_tranche == "add1"
    assert rec.target_tranche == "entry"
    assert rec.executable is True


def test_reduce_signal_at_entry_tranche_becomes_sell_to_avoid_noop_reduce() -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("reduce"),
        position=_position(tranche_state="entry"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "sell"
    assert rec.current_tranche == "entry"
    assert rec.target_tranche == "flat"
    assert rec.executable is True


@pytest.mark.parametrize("state, action", [("reduce", "reduce"), ("exit", "sell")])
def test_same_day_sell_side_signal_is_marked_not_executable_under_t1(
    state: str,
    action: str,
) -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal(state),
        position=_position(tranche_state="add1", latest_buy_date="2026-04-26"),
        as_of_date="2026-04-26",
    )

    assert rec.action == action
    assert rec.executable is False


@pytest.mark.parametrize("as_of_date", ["2026-04-26", "2026-04-26 14:30", "2026-04-26T14:30:00"])
def test_same_day_t1_check_compares_natural_date(as_of_date: str) -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("exit"),
        position=_position(tranche_state="add1", latest_buy_date="2026-04-26 09:45:00"),
        as_of_date=as_of_date,
    )

    assert rec.action == "sell"
    assert rec.executable is False


@pytest.mark.parametrize(
    "current_tranche, target_tranche",
    [("entry", "add1"), ("add1", "full")],
)
def test_entry_signal_with_position_becomes_next_add(
    current_tranche: str,
    target_tranche: str,
) -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal("entry"),
        position=_position(tranche_state=current_tranche),
        as_of_date="2026-04-26",
    )

    assert rec.action == "add"
    assert rec.current_tranche == current_tranche
    assert rec.target_tranche == target_tranche
    assert rec.executable is True


@pytest.mark.parametrize("state", ["watch", "hold", "entry"])
def test_hold_like_signal_with_position_keeps_current_tranche(state: str) -> None:
    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=_signal(state),
        position=_position(tranche_state="full"),
        as_of_date="2026-04-26",
    )

    assert rec.action == "hold"
    assert rec.current_tranche == "full"
    assert rec.target_tranche == "full"
    assert rec.executable is True
    assert rec.reason == f"{state} reason"
