from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.investment import register_investment_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.investment.data import OptionalDependencyMissingError
from nanobot.investment.market import Bar
from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry
from nanobot.investment.store import InvestmentStore


def _build_context(raw: str, store: InvestmentStore, market_data=None) -> CommandContext:
    msg = InboundMessage(
        channel="test",
        sender_id="user-1",
        chat_id="chat-1",
        content=raw,
    )
    loop = SimpleNamespace(investment_store=store)
    if market_data is not None:
        loop.investment_market_data = market_data
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


class _FakeMarketData:
    def __init__(self, bars_by_symbol: dict[str, list[Bar]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.calls = []

    def fetch_completed_bars(self, **kwargs):
        self.calls.append(kwargs)
        response = self.bars_by_symbol[kwargs["symbol"]]
        if isinstance(response, Exception):
            raise response
        return list(response)


class _LockAwareMarketData(_FakeMarketData):
    def __init__(self, bars_by_symbol: dict[str, list[Bar]], lock: _TrackingLock) -> None:
        super().__init__(bars_by_symbol)
        self.lock = lock
        self.fetch_entered_lock_counts = []

    def fetch_completed_bars(self, **kwargs):
        self.fetch_entered_lock_counts.append(self.lock.entered - self.lock.exited)
        return super().fetch_completed_bars(**kwargs)


def _make_bars(symbol: str = "510300", kind: str = "etf") -> list[Bar]:
    period_start = datetime(2026, 4, 27, 0, 30)
    closes = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.7, 11.1]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    bars: list[Bar] = []

    for index, (close, volume) in enumerate(zip(closes, volumes)):
        bars.append(
            Bar(
                symbol=symbol,
                kind=kind,
                ends_at=period_start + timedelta(hours=index),
                open=close - 0.1,
                high=close + 0.1,
                low=close - 0.15,
                close=close,
                volume=volume,
                complete=True,
            )
        )

    return bars


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
    router: CommandRouter,
    tmp_path,
    cost_basis: str,
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
    router: CommandRouter,
    tmp_path,
    shares: str,
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
    router: CommandRouter,
    tmp_path,
    minutes: str,
) -> None:
    store = InvestmentStore(tmp_path)

    response = await router.dispatch(_build_context(f"/invest interval {minutes}", store))

    assert response is not None
    assert "Invalid interval" in response.content
    assert store.load().scan_period_minutes == 60


@pytest.mark.asyncio
async def test_mode_returns_friendly_message_when_state_save_fails(
    router: CommandRouter,
    tmp_path,
    monkeypatch,
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
    router: CommandRouter,
    tmp_path,
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


@pytest.mark.asyncio
async def test_help_includes_status_commands(router: CommandRouter, tmp_path) -> None:
    response = await router.dispatch(_build_context("/invest", InvestmentStore(tmp_path)))

    assert response is not None
    assert "/invest status <symbol>" in response.content
    assert "/invest status positions" in response.content


@pytest.mark.asyncio
async def test_status_symbol_returns_dynamic_watchlist_state(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    store.save(state)
    market_data = _FakeMarketData({"510300": _make_bars()})

    response = await router.dispatch(_build_context("/invest status 510300", store, market_data))

    assert response is not None
    assert "【动态状态】" in response.content
    assert "标的: 510300" in response.content
    assert "资产类型: etf" in response.content
    assert "最新已收盘周期: 2026-04-27T10:30:00" in response.content
    assert "建议动作: 买入" in response.content
    assert "当前可执行: 是" in response.content
    assert market_data.calls == [
        {
            "symbol": "510300",
            "kind": "etf",
            "period_minutes": 60,
            "limit": 120,
        }
    ]


@pytest.mark.asyncio
async def test_status_symbol_fetches_market_data_outside_investment_lock(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    store.save(state)
    lock = _TrackingLock()
    market_data = _LockAwareMarketData({"510300": _make_bars()}, lock)
    ctx = _build_context("/invest status 510300", store, market_data)
    ctx.loop.investment_lock = lock

    response = await router.dispatch(ctx)

    assert response is not None
    assert "标的: 510300" in response.content
    assert lock.entered == 0
    assert lock.exited == 0
    assert market_data.fetch_entered_lock_counts == [0]


@pytest.mark.asyncio
async def test_status_symbol_accepts_market_data_loop_alias(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    store.save(state)
    market_data = _FakeMarketData({"510300": _make_bars()})
    ctx = _build_context("/invest status 510300", store)
    ctx.loop.market_data = market_data

    response = await router.dispatch(ctx)

    assert response is not None
    assert "标的: 510300" in response.content
    assert market_data.calls[0]["symbol"] == "510300"


@pytest.mark.asyncio
async def test_status_symbol_allows_position_only_symbol(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["SPY"] = PositionRecord(
        symbol="SPY",
        kind="etf",
        cost_basis=505.2,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=12,
    )
    store.save(state)
    market_data = _FakeMarketData({"SPY": _make_bars(symbol="SPY", kind="etf")})

    response = await router.dispatch(_build_context("/invest status spy", store, market_data))

    assert response is not None
    assert "标的: SPY" in response.content
    assert "当前持仓状态: entry" in response.content
    assert "仓位档位: entry" in response.content
    assert market_data.calls[0]["kind"] == "etf"


@pytest.mark.asyncio
async def test_status_symbol_rejects_unknown_symbol(router: CommandRouter, tmp_path) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    store.save(state)

    response = await router.dispatch(
        _build_context("/invest status msft", store, _FakeMarketData({}))
    )

    assert response is not None
    assert "`MSFT` 不在自选池或持仓中" in response.content


@pytest.mark.asyncio
async def test_status_positions_returns_clear_message_when_empty(
    router: CommandRouter,
    tmp_path,
) -> None:
    response = await router.dispatch(
        _build_context("/invest status positions", InvestmentStore(tmp_path), _FakeMarketData({}))
    )

    assert response is not None
    assert "当前没有持仓" in response.content


@pytest.mark.asyncio
async def test_status_positions_returns_summary_for_multiple_positions(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["510300"] = PositionRecord(
        symbol="510300",
        kind="etf",
        cost_basis=4.5,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=100,
    )
    state.positions["600519"] = PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1500,
        tranche_state="add1",
        latest_buy_date="2026-04-25",
        shares=10,
    )
    store.save(state)
    market_data = _FakeMarketData(
        {
            "510300": _make_bars(symbol="510300", kind="etf"),
            "600519": _make_bars(symbol="600519", kind="stock"),
        }
    )

    response = await router.dispatch(_build_context("/invest status positions", store, market_data))

    assert response is not None
    assert "【持仓动态状态】" in response.content
    assert "510300(etf) entry->add1 加仓" in response.content
    assert "600519(stock) add1->full 加仓" in response.content
    assert [call["symbol"] for call in market_data.calls] == ["510300", "600519"]


@pytest.mark.asyncio
async def test_status_positions_includes_successes_and_failed_symbols(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["510300"] = PositionRecord(
        symbol="510300",
        kind="etf",
        cost_basis=4.5,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=100,
    )
    state.positions["600519"] = PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1500,
        tranche_state="add1",
        latest_buy_date="2026-04-25",
        shares=10,
    )
    state.positions["SPY"] = PositionRecord(
        symbol="SPY",
        kind="etf",
        cost_basis=505.2,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=12,
    )
    store.save(state)
    market_data = _FakeMarketData(
        {
            "510300": _make_bars(symbol="510300", kind="etf"),
            "600519": RuntimeError("temporary upstream failure"),
            "SPY": _make_bars(symbol="SPY", kind="etf"),
        }
    )

    response = await router.dispatch(_build_context("/invest status positions", store, market_data))

    assert response is not None
    assert "【持仓动态状态】" in response.content
    assert "510300(etf) entry->add1 加仓" in response.content
    assert "SPY(etf) entry->add1 加仓" in response.content
    assert "600519" in response.content
    assert "失败" in response.content
    assert [call["symbol"] for call in market_data.calls] == ["510300", "600519", "SPY"]


@pytest.mark.asyncio
async def test_status_positions_returns_dependency_missing_message(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["510300"] = PositionRecord(
        symbol="510300",
        kind="etf",
        cost_basis=4.5,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=100,
    )
    store.save(state)
    market_data = _FakeMarketData(
        {"510300": OptionalDependencyMissingError("akshare dependency is missing")}
    )

    response = await router.dispatch(_build_context("/invest status positions", store, market_data))

    assert response is not None
    assert "Investment market data dependency is missing" in response.content
    assert "install the investment extra" in response.content


@pytest.mark.asyncio
async def test_status_positions_lists_failed_symbols_when_all_runtime_queries_fail(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["510300"] = PositionRecord(
        symbol="510300",
        kind="etf",
        cost_basis=4.5,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=100,
    )
    state.positions["600519"] = PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1500,
        tranche_state="add1",
        latest_buy_date="2026-04-25",
        shares=10,
    )
    store.save(state)
    market_data = _FakeMarketData(
        {
            "510300": RuntimeError("temporary upstream failure"),
            "600519": RuntimeError("rate limited"),
        }
    )

    response = await router.dispatch(_build_context("/invest status positions", store, market_data))

    assert response is not None
    assert "持仓标的动态状态查询失败" in response.content
    assert "510300" in response.content
    assert "600519" in response.content
    assert "暂无最新完整周期行情" not in response.content


@pytest.mark.asyncio
async def test_status_positions_does_not_treat_runtime_dependency_text_as_missing_dependency(
    router: CommandRouter,
    tmp_path,
) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.positions["510300"] = PositionRecord(
        symbol="510300",
        kind="etf",
        cost_basis=4.5,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=100,
    )
    state.positions["SPY"] = PositionRecord(
        symbol="SPY",
        kind="etf",
        cost_basis=505.2,
        tranche_state="entry",
        latest_buy_date="2026-04-25",
        shares=12,
    )
    store.save(state)
    market_data = _FakeMarketData(
        {
            "510300": RuntimeError("remote dependency is missing but retryable"),
            "SPY": _make_bars(symbol="SPY", kind="etf"),
        }
    )

    response = await router.dispatch(_build_context("/invest status positions", store, market_data))

    assert response is not None
    assert "【持仓动态状态】" in response.content
    assert "SPY(etf) entry->add1 加仓" in response.content
    assert "查询失败: 510300" in response.content
    assert "Investment market data dependency is missing" not in response.content
