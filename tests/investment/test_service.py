from datetime import date, datetime, timedelta

import pytest

from nanobot.investment import data as investment_data
from nanobot.investment.market import Bar
from nanobot.investment.models import InvestmentState, WatchlistEntry
from nanobot.investment.service import InvestmentAssistantService
from nanobot.investment.store import InvestmentStore


class _FakeBus:
    def __init__(self) -> None:
        self.published = []

    async def publish_outbound(self, msg) -> None:
        self.published.append(msg)


class _FakeSessions:
    def __init__(self, sessions: list[dict[str, str]] | None = None) -> None:
        self._sessions = sessions or [
            {"key": "telegram:chat-top", "updated_at": "2026-04-27T10:40:00"},
            {"key": "weixin:chat-new", "updated_at": "2026-04-27T10:35:00"},
            {"key": "weixin:chat-old", "updated_at": "2026-04-27T10:15:00"},
        ]

    def list_sessions(self) -> list[dict[str, str]]:
        return list(self._sessions)


class _SequenceMarketData:
    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.calls = []

    def fetch_completed_bars(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        response = self._responses[index]
        if isinstance(response, Exception):
            raise response
        return list(response)


class _PerSymbolSequenceMarketData:
    def __init__(self, responses_by_symbol) -> None:
        self._responses_by_symbol = {
            symbol: list(responses) for symbol, responses in responses_by_symbol.items()
        }
        self._call_count_by_symbol: dict[str, int] = {}
        self.calls = []

    def fetch_completed_bars(self, **kwargs):
        self.calls.append(kwargs)
        symbol = kwargs["symbol"]
        responses = self._responses_by_symbol[symbol]
        call_count = self._call_count_by_symbol.get(symbol, 0)
        index = min(call_count, len(responses) - 1)
        self._call_count_by_symbol[symbol] = call_count + 1
        response = responses[index]
        if isinstance(response, Exception):
            raise response
        return list(response)


def _make_bars(*, start: datetime | None = None) -> list[Bar]:
    period_start = start or datetime(2026, 4, 27, 0, 30)
    closes = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.7, 11.1]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    bars: list[Bar] = []

    for index, (close, volume) in enumerate(zip(closes, volumes)):
        bars.append(
            Bar(
                symbol="510300",
                kind="etf",
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


def _seed_state(tmp_path) -> None:
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    InvestmentStore(tmp_path).save(state)


def _seed_multi_symbol_state(tmp_path) -> None:
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    state.watchlist["600519"] = WatchlistEntry(symbol="600519", kind="stock")
    InvestmentStore(tmp_path).save(state)


def test_service_prefers_most_recent_weixin_session(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        enabled_channels={"telegram", "weixin"},
    )

    assert service._pick_target() == ("weixin", "chat-new")


def test_service_falls_back_to_most_recent_non_system_session(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(
            [
                {"key": "system:daemon", "updated_at": "2026-04-27T10:45:00"},
                {"key": "telegram:chat-top", "updated_at": "2026-04-27T10:40:00"},
                {"key": "cli:local", "updated_at": "2026-04-27T10:35:00"},
            ]
        ),
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        enabled_channels={"telegram"},
    )

    assert service._pick_target() == ("telegram", "chat-top")


def test_service_ignores_sessions_for_disabled_channels(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(
            [
                {"key": "weixin:chat-new", "updated_at": "2026-04-27T10:45:00"},
                {"key": "telegram:chat-top", "updated_at": "2026-04-27T10:40:00"},
            ]
        ),
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        enabled_channels={"telegram"},
    )

    assert service._pick_target() == ("telegram", "chat-top")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 4, 27, 9, 29), False),
        (datetime(2026, 4, 27, 9, 30), True),
        (datetime(2026, 4, 27, 11, 30), True),
        (datetime(2026, 4, 27, 11, 31), False),
        (datetime(2026, 4, 27, 13, 0), True),
        (datetime(2026, 4, 27, 15, 0), True),
        (datetime(2026, 4, 27, 15, 1), False),
    ],
)
def test_service_checks_trading_time_windows(tmp_path, moment: datetime, expected: bool) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        is_open_day=lambda day: day == date(2026, 4, 27),
    )

    assert service._is_trading_time(moment) is expected


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 4, 28, 9, 30),
        datetime(2026, 4, 28, 10, 45),
        datetime(2026, 4, 28, 13, 0),
        datetime(2026, 4, 28, 14, 30),
    ],
)
def test_service_rejects_trading_windows_on_closed_day(tmp_path, moment: datetime) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        is_open_day=lambda _day: False,
    )

    assert service._is_trading_time(moment) is False


@pytest.mark.asyncio
async def test_scan_once_publishes_only_once_per_completed_cycle(tmp_path) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=_SequenceMarketData([_make_bars(), _make_bars()]),
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 10, 40))

    assert first is True
    assert second is False
    assert len(bus.published) == 1
    assert bus.published[0].channel == "weixin"
    assert bus.published[0].chat_id == "chat-new"
    assert "正式信号" in bus.published[0].content


@pytest.mark.asyncio
async def test_scan_once_publishes_new_cycle_with_snapshot_diff(tmp_path) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=_SequenceMarketData(
            [
                _make_bars(start=datetime(2026, 4, 27, 0, 30)),
                _make_bars(start=datetime(2026, 4, 27, 1, 30)),
            ]
        ),
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 11, 5))

    assert first is True
    assert second is True
    assert len(bus.published) == 2
    assert "本轮新增正式信号: 1 条" in bus.published[0].content
    assert "【正式信号】" in bus.published[0].content
    assert "本轮新增正式信号: 0 条" in bus.published[1].content
    assert "【正式信号】" not in bus.published[1].content


@pytest.mark.asyncio
async def test_scan_once_disables_future_scans_after_dependency_error(tmp_path) -> None:
    _seed_state(tmp_path)
    missing_dependency_error = getattr(
        investment_data,
        "OptionalDependencyMissingError",
        RuntimeError,
    )
    market_data = _SequenceMarketData([missing_dependency_error("install investment extra")])
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=_FakeBus(),
        market_data=market_data,
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 10, 40))

    assert first is False
    assert second is False
    assert market_data.calls == [
        {
            "symbol": "510300",
            "kind": "etf",
            "period_minutes": 60,
            "limit": 120,
        }
    ]


@pytest.mark.asyncio
async def test_scan_once_does_not_disable_future_scans_after_transient_runtime_error(
    tmp_path,
) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    market_data = _SequenceMarketData([RuntimeError("temporary upstream failure"), _make_bars()])
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=market_data,
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 10, 40))

    assert first is False
    assert second is True
    assert len(bus.published) == 1
    assert len(market_data.calls) == 2


@pytest.mark.asyncio
async def test_scan_once_skips_publish_when_no_enabled_external_channel(tmp_path) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(
            [
                {"key": "weixin:chat-new", "updated_at": "2026-04-27T10:45:00"},
                {"key": "cli:local", "updated_at": "2026-04-27T10:40:00"},
            ]
        ),
        bus=bus,
        market_data=_SequenceMarketData([_make_bars()]),
        enabled_channels={"discord"},
    )

    published = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))

    assert published is False
    assert bus.published == []
    assert service._last_published_bar_markers == {}


@pytest.mark.asyncio
async def test_scan_once_uses_configured_timezone_for_default_current_time(
    tmp_path, monkeypatch
) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=_SequenceMarketData([_make_bars()]),
        timezone="Asia/Shanghai",
        enabled_channels={"telegram", "weixin"},
        is_open_day=lambda day: day == date(2026, 4, 27),
    )

    class _FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return datetime(2026, 4, 27, 1, 45)
            return datetime(2026, 4, 27, 9, 45, tzinfo=tz)

    monkeypatch.setattr("nanobot.investment.service.datetime", _FakeDateTime)

    published = await service.scan_once()

    assert published is True
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_scan_once_defaults_to_china_market_timezone_for_default_current_time(
    tmp_path, monkeypatch
) -> None:
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=_SequenceMarketData([_make_bars()]),
        enabled_channels={"telegram", "weixin"},
        is_open_day=lambda day: day == date(2026, 4, 27),
    )

    class _FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return datetime(2026, 4, 27, 1, 45)
            return datetime(2026, 4, 27, 9, 45, tzinfo=tz)

    monkeypatch.setattr("nanobot.investment.service.datetime", _FakeDateTime)

    published = await service.scan_once()

    assert published is True
    assert len(bus.published) == 1


@pytest.mark.asyncio
async def test_scan_once_preserves_formal_snapshot_when_other_symbol_temporarily_has_no_bars(
    tmp_path,
) -> None:
    _seed_multi_symbol_state(tmp_path)
    bus = _FakeBus()
    market_data = _PerSymbolSequenceMarketData(
        {
            "510300": [
                _make_bars(start=datetime(2026, 4, 27, 0, 30)),
                _make_bars(start=datetime(2026, 4, 27, 1, 30)),
                _make_bars(start=datetime(2026, 4, 27, 2, 30)),
            ],
            "600519": [
                _make_bars(start=datetime(2026, 4, 27, 0, 30)),
                [],
                _make_bars(start=datetime(2026, 4, 27, 2, 30)),
            ],
        }
    )
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=market_data,
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 11, 30))
    third = await service.scan_once(now=datetime(2026, 4, 27, 14, 5))

    assert first is True
    assert second is True
    assert third is True
    assert len(bus.published) == 3
    assert "本轮新增正式信号: 2 条" in bus.published[0].content
    assert "本轮新增正式信号: 0 条" in bus.published[1].content
    assert "本轮新增正式信号: 0 条" in bus.published[2].content


@pytest.mark.asyncio
async def test_scan_once_republishes_when_same_cycle_data_arrives_for_late_symbol(
    tmp_path,
) -> None:
    _seed_multi_symbol_state(tmp_path)
    bus = _FakeBus()
    market_data = _PerSymbolSequenceMarketData(
        {
            "510300": [
                _make_bars(start=datetime(2026, 4, 27, 1, 30)),
                _make_bars(start=datetime(2026, 4, 27, 1, 30)),
            ],
            "600519": [
                _make_bars(start=datetime(2026, 4, 27, 0, 30)),
                _make_bars(start=datetime(2026, 4, 27, 1, 30)),
            ],
        }
    )
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=market_data,
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 11, 30))
    second = await service.scan_once(now=datetime(2026, 4, 27, 13, 5))

    assert first is True
    assert second is True
    assert len(bus.published) == 2
    assert service._last_published_bar_markers == {
        "510300": datetime(2026, 4, 27, 11, 30).isoformat(),
        "600519": datetime(2026, 4, 27, 11, 30).isoformat(),
    }


@pytest.mark.asyncio
async def test_scan_once_republishes_when_symbol_late_arrives_in_same_cycle(tmp_path) -> None:
    _seed_multi_symbol_state(tmp_path)
    bus = _FakeBus()
    latest_cycle_bars = _make_bars(start=datetime(2026, 4, 27, 0, 30))
    market_data = _PerSymbolSequenceMarketData(
        {
            "510300": [latest_cycle_bars, latest_cycle_bars],
            "600519": [latest_cycle_bars[:-1], latest_cycle_bars],
        }
    )
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=market_data,
        enabled_channels={"telegram", "weixin"},
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 10, 40))

    assert first is True
    assert second is True
    assert len(bus.published) == 2
    assert "本轮新增正式信号: 1 条" in bus.published[0].content
    assert "标的: 510300" in bus.published[0].content
    assert "标的: 600519" not in bus.published[0].content
    assert "本轮新增正式信号: 1 条" in bus.published[1].content
    assert "标的: 600519" in bus.published[1].content


@pytest.mark.asyncio
async def test_start_and_stop_manage_background_task_lifecycle(tmp_path, monkeypatch) -> None:
    created = []

    class _FakeTask:
        def __init__(self, coro) -> None:
            self._coro = coro
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True
            self._coro.close()

    def _create_task(coro):
        task = _FakeTask(coro)
        created.append(task)
        return task

    monkeypatch.setattr("nanobot.investment.service.asyncio.create_task", _create_task)

    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
    )

    await service.start()
    await service.start()

    assert service._running is True
    assert len(created) == 1

    service.stop()

    assert service._running is False
    assert service._task is None
    assert created[0].cancelled is True
