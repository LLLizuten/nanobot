from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.investment import register_investment_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.investment.models import InvestmentState
from nanobot.investment.store import InvestmentStore


def _build_context(raw: str, store: InvestmentStore) -> CommandContext:
    msg = InboundMessage(
        channel="test",
        sender_id="user-1",
        chat_id="chat-1",
        content=raw,
    )
    loop = SimpleNamespace(investment_store=store)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=loop)


class _TrackingLock:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self._on_enter: Callable[[], Awaitable[None]] | None = None

    def set_on_enter(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._on_enter = callback

    async def __aenter__(self) -> "_TrackingLock":
        self.entered += 1
        if self._on_enter is not None:
            await self._on_enter()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


@pytest.fixture()
def router() -> CommandRouter:
    command_router = CommandRouter()
    register_investment_commands(command_router)
    return command_router


@pytest.mark.asyncio
async def test_watch_add_updates_workspace_state(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(_build_context("/invest watch add nvda stock", store))

    assert response is not None
    assert "NVDA" in response.content
    state = store.load()
    assert state.watchlist["NVDA"].symbol == "NVDA"
    assert state.watchlist["NVDA"].kind == "stock"


@pytest.mark.asyncio
async def test_mode_updates_risk_profile(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(_build_context("/invest mode aggressive", store))

    assert response is not None
    assert "aggressive" in response.content
    assert store.load().mode == "aggressive"


@pytest.mark.asyncio
async def test_position_set_and_interval_persist(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)

    position_response = await router.dispatch(
        _build_context(
            "/invest position set spy etf 505.2 entry 2026-04-25 12",
            store,
        )
    )
    interval_response = await router.dispatch(_build_context("/invest interval 30", store))

    assert position_response is not None
    assert interval_response is not None

    state = store.load()
    assert state.positions["SPY"].symbol == "SPY"
    assert state.positions["SPY"].kind == "etf"
    assert state.positions["SPY"].cost_basis == 505.2
    assert state.positions["SPY"].tranche_state == "entry"
    assert state.positions["SPY"].latest_buy_date == "2026-04-25"
    assert state.positions["SPY"].shares == 12
    assert state.scan_period_minutes == 30


@pytest.mark.asyncio
async def test_position_set_rejects_unknown_tranche_state(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(
        _build_context(
            "/invest position set spy etf 505.2 laddering 2026-04-25 12",
            store,
        )
    )

    assert response is not None
    assert "Invalid tranche state" in response.content
    assert store.load().positions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("cost_basis", ["0", "-1", "nan", "inf"])
async def test_position_set_rejects_non_positive_or_non_finite_cost_basis(
    router: CommandRouter, tmp_path, cost_basis: str,
) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(
        _build_context(
            f"/invest position set spy etf {cost_basis} entry 2026-04-25 12",
            store,
        )
    )

    assert response is not None
    assert "Invalid cost basis" in response.content
    assert store.load().positions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("shares", ["0", "-3"])
async def test_position_set_rejects_non_positive_shares(
    router: CommandRouter, tmp_path, shares: str,
) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(
        _build_context(
            f"/invest position set spy etf 505.2 entry 2026-04-25 {shares}",
            store,
        )
    )

    assert response is not None
    assert "Invalid shares" in response.content
    assert store.load().positions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", ["0", "-15"])
async def test_interval_rejects_non_positive_minutes(
    router: CommandRouter, tmp_path, minutes: str,
) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(_build_context(f"/invest interval {minutes}", store))

    assert response is not None
    assert "Invalid interval" in response.content
    assert store.load().scan_period_minutes == 60


@pytest.mark.asyncio
async def test_mode_returns_friendly_message_when_state_save_fails(
    router: CommandRouter, tmp_path, monkeypatch,
) -> None:
    store = InvestmentStore(tmp_path)

    def fail_save(_state: InvestmentState) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", fail_save)

    response = await router.dispatch(_build_context("/invest mode aggressive", store))

    assert response is not None
    assert "could not be saved" in response.content
    assert "write access" in response.content


@pytest.mark.asyncio
async def test_watch_add_uses_investment_lock_when_available(
    router: CommandRouter, tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    lock = _TrackingLock()
    ctx = _build_context("/invest watch add nvda stock", store)
    ctx.loop.investment_lock = lock

    response = await router.dispatch(ctx)

    assert response is not None
    assert lock.entered == 1
    assert lock.exited == 1
    assert store.load().watchlist["NVDA"].symbol == "NVDA"
