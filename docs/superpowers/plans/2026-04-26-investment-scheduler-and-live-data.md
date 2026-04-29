# Investment Scheduler And Live Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 A 股 / 场内 ETF 的完整周期行情，并在 gateway 运行时于交易时段内按配置周期执行扫描与微信播报。

**Architecture:** 新增 `AkshareMarketDataProvider` 负责把外部分钟线标准化为 `Bar`；新增 `InvestmentAssistantService` 组合现有 `InvestmentStore`、信号引擎、决策层和播报层，在后台轮询并只对“新的已收盘周期”发送一次播报。gateway 继续维持 `cron / heartbeat / channels` 的现有编排方式，投资服务以并列后台服务接入，而不是复用 `HeartbeatService`。这一版先通过可注入的 `is_open_day` 谓词保留交易日接口，默认实现只覆盖工作日与交易时段，不在本计划中引入法定休市日数据源。

**Tech Stack:** Python 3.11, AkShare optional extra, asyncio, existing MessageBus / SessionManager, pytest

**Status:** 已完成并通过本轮评审。当前实现已补齐中国市场时区固定语义，以及同一周期内晚到数据的再次播报逻辑；相关测试验证已通过。

---

### Task 1: AkShare 行情适配器

**Files:**
- Modify: `pyproject.toml`
- Create: `nanobot/investment/data.py`
- Test: `tests/investment/test_data_provider.py`

- [x] **Step 1: Write the failing test**

```python
from datetime import datetime

import pytest

from nanobot.investment.data import AkshareMarketDataProvider


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return list(self._rows)


def test_provider_normalizes_a_share_rows(monkeypatch):
    fake_rows = [
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.9,
            "收盘": 10.4,
            "成交量": 123456,
        }
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    monkeypatch.setattr("nanobot.investment.data._load_akshare", lambda: _FakeAkshare)

    provider = AkshareMarketDataProvider()
    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=1,
    )

    assert len(bars) == 1
    assert bars[0].symbol == "600519"
    assert bars[0].ends_at == datetime(2026, 4, 26, 10, 30)
    assert bars[0].close == 10.4
    assert bars[0].complete is True


def test_provider_raises_clear_error_when_optional_dependency_is_missing(monkeypatch):
    def _raise_import_error():
        raise ImportError("akshare not installed")

    monkeypatch.setattr("nanobot.investment.data._load_akshare", _raise_import_error)

    provider = AkshareMarketDataProvider()

    with pytest.raises(RuntimeError, match="pip install -e \".\\[investment\\]\""):
        provider.fetch_completed_bars(
            symbol="510300",
            kind="etf",
            period_minutes=60,
            limit=1,
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_data_provider.py -v`
Expected: FAIL with `ImportError: cannot import name 'AkshareMarketDataProvider'`

- [x] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project.optional-dependencies]
investment = [
    "akshare>=1.16.72,<2.0.0",
]
```

```python
# nanobot/investment/data.py
from __future__ import annotations

from datetime import datetime

from nanobot.investment.market import Bar


def _load_akshare():
    import akshare as ak

    return ak


class AkshareMarketDataProvider:
    def fetch_completed_bars(
        self,
        *,
        symbol: str,
        kind: str,
        period_minutes: int,
        limit: int,
    ) -> list[Bar]:
        try:
            ak = _load_akshare()
        except ImportError as exc:
            raise RuntimeError(
                "AkShare is not installed. Run `pip install -e \".[investment]\"`."
            ) from exc

        period = str(period_minutes)
        if kind == "stock":
            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="")
        elif kind == "etf":
            frame = ak.fund_etf_hist_min_em(symbol=symbol, period=period, adjust="")
        else:
            raise ValueError(f"unsupported asset kind: {kind}")

        rows = frame.to_dict(orient="records")[-limit:]
        return [
            Bar(
                symbol=symbol,
                kind=kind,
                ends_at=datetime.fromisoformat(row["时间"]),
                open=float(row["开盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                close=float(row["收盘"]),
                volume=float(row["成交量"]),
                complete=True,
            )
            for row in rows
        ]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_data_provider.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add pyproject.toml nanobot/investment/data.py tests/investment/test_data_provider.py
git commit -m "feat: add akshare investment data provider"
```

### Task 2: 投资扫描后台服务

**Files:**
- Create: `nanobot/investment/service.py`
- Test: `tests/investment/test_service.py`

- [x] **Step 1: Write the failing test**

```python
from datetime import date, datetime, timedelta

import pytest

from nanobot.investment.market import Bar
from nanobot.investment.models import InvestmentState, WatchlistEntry
from nanobot.investment.service import InvestmentAssistantService
from nanobot.investment.store import InvestmentStore


class _FakeBus:
    def __init__(self):
        self.published = []

    async def publish_outbound(self, msg):
        self.published.append(msg)


class _FakeSessions:
    def list_sessions(self):
        return [
            {"key": "weixin:chat-new", "updated_at": "2026-04-27T10:35:00"},
            {"key": "telegram:chat-old", "updated_at": "2026-04-27T10:00:00"},
        ]


class _FakeMarketData:
    def __init__(self, bars):
        self._bars = bars

    def fetch_completed_bars(self, **_kwargs):
        return list(self._bars)


def _make_bars():
    start = datetime(2026, 4, 27, 0, 30)
    closes = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.7, 11.1]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    bars = []
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
    return bars


def _seed_state(tmp_path):
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    InvestmentStore(tmp_path).save(state)


def test_service_prefers_most_recent_weixin_session(tmp_path):
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=_FakeBus(),
        market_data=_FakeMarketData(_make_bars()),
    )

    assert service._pick_target() == ("weixin", "chat-new")


def test_service_respects_injected_open_day_predicate(tmp_path):
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_FakeMarketData(_make_bars()),
        is_open_day=lambda _day: False,
    )

    assert service._is_trading_time(datetime(2026, 4, 27, 10, 30)) is False


@pytest.mark.asyncio
async def test_scan_once_publishes_only_once_per_completed_cycle(tmp_path):
    _seed_state(tmp_path)
    bus = _FakeBus()
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=bus,
        market_data=_FakeMarketData(_make_bars()),
    )

    first = await service.scan_once(now=datetime(2026, 4, 27, 10, 35))
    second = await service.scan_once(now=datetime(2026, 4, 27, 10, 40))

    assert first is True
    assert second is False
    assert len(bus.published) == 1
    assert bus.published[0].channel == "weixin"
    assert "正式信号" in bus.published[0].content
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'InvestmentAssistantService'`

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/investment/service.py
from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from typing import Callable

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.investment.decisions import Recommendation, decide_recommendation
from nanobot.investment.reporting import FORMAL_ACTIONS, format_cycle_report
from nanobot.investment.signals import evaluate_trend_breakout
from nanobot.investment.store import InvestmentStore


class InvestmentAssistantService:
    def __init__(
        self,
        *,
        workspace,
        session_manager,
        bus,
        market_data,
        timezone: str | None = None,
        enabled_channels: set[str] | None = None,
        poll_interval_s: int = 30,
        is_open_day: Callable[[date], bool] | None = None,
    ):
        self.workspace = workspace
        self.session_manager = session_manager
        self.bus = bus
        self.market_data = market_data
        self.timezone = resolve_market_timezone(timezone)
        self.enabled_channels = set(enabled_channels or ())
        self.poll_interval_s = poll_interval_s
        self.is_open_day = is_open_day or (lambda day: day.weekday() < 5)
        self.store = InvestmentStore(workspace)
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_published_bar_markers: dict[str, str] = {}
        self._last_formal_snapshot: dict[str, tuple[str, str, str, bool]] = {}
        self._dependency_disabled = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _is_trading_time(self, now: datetime) -> bool:
        if not self.is_open_day(now.date()):
            return False
        current = now.time()
        return (
            time(9, 30) <= current <= time(11, 30)
            or time(13, 0) <= current <= time(15, 0)
        )

    def _pick_target(self) -> tuple[str, str] | None:
        if self.session_manager is None:
            return None

        sessions = list(self.session_manager.list_sessions())
        for item in sessions:
            key = item.get("key", "")
            if key.startswith("weixin:"):
                chat_id = key.split(":", 1)[1]
                if "weixin" in self.enabled_channels and chat_id:
                    return ("weixin", chat_id)
        for item in sessions:
            key = item.get("key", "")
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel not in {"cli", "system"} and chat_id:
                if channel not in self.enabled_channels:
                    continue
                return (channel, chat_id)
        return None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except Exception:
                logger.exception("Investment assistant scan failed")
            await asyncio.sleep(self.poll_interval_s)

    async def scan_once(self, now: datetime | None = None) -> bool:
        current_now = now or datetime.now()
        if self._dependency_disabled or not self._is_trading_time(current_now):
            return False

        state = self.store.load()
        if not state.watchlist:
            return False

        recommendations: list[Recommendation] = []
        bar_markers: dict[str, str] = {}

        for symbol, entry in state.watchlist.items():
            try:
                bars = self.market_data.fetch_completed_bars(
                    symbol=symbol,
                    kind=entry.kind,
                    period_minutes=state.scan_period_minutes,
                    limit=120,
                )
            except RuntimeError as exc:
                logger.warning("Investment service disabled: {}", exc)
                self._dependency_disabled = True
                return False

            if not bars:
                continue
            latest_bar = bars[-1]
            bar_markers[symbol] = latest_bar.ends_at.isoformat()
            signal = evaluate_trend_breakout(bars, mode=state.mode)
            recommendations.append(
                decide_recommendation(
                    symbol=symbol,
                    kind=entry.kind,
                    signal=signal,
                    position=state.positions.get(symbol),
                    as_of_date=latest_bar.ends_at.date().isoformat(),
                )
            )

        if not bar_markers:
            return False

        if not self._has_new_completed_bar(bar_markers):
            return False

        changed_symbols = self._diff_formal_symbols(recommendations)
        report = format_cycle_report(
            generated_at=current_now.strftime("%Y-%m-%d %H:%M"),
            summary={
                "watchlist": len(state.watchlist),
                "positions": len(state.positions),
            },
            recommendations=recommendations,
            changed_symbols=changed_symbols,
        )
        target = self._pick_target()
        if target is None:
            return False
        channel, chat_id = target
        await self.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=report)
        )
        self._last_published_bar_markers.update(bar_markers)
        self._last_formal_snapshot = self._merge_formal_snapshot(recommendations)
        return True

    def _formal_snapshot(
        self, recommendations: list[Recommendation],
    ) -> dict[str, tuple[str, str, str, bool]]:
        snapshot = {}
        for item in recommendations:
            if item.action in FORMAL_ACTIONS:
                snapshot[item.symbol] = (
                    item.action,
                    item.current_tranche,
                    item.target_tranche,
                    item.executable,
                )
        return snapshot

    def _diff_formal_symbols(self, recommendations: list[Recommendation]) -> set[str]:
        changed: set[str] = set()
        snapshot = self._formal_snapshot(recommendations)
        for symbol, payload in snapshot.items():
            if self._last_formal_snapshot.get(symbol) != payload:
                changed.add(symbol)
        return changed

    def _has_new_completed_bar(self, bar_markers: dict[str, str]) -> bool:
        for symbol, marker in bar_markers.items():
            if self._last_published_bar_markers.get(symbol) != marker:
                return True
        return False
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_service.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/investment/service.py tests/investment/test_service.py
git commit -m "feat: add investment assistant background service"
```

### Task 3: Gateway 集成与生命周期接线

**Files:**
- Modify: `nanobot/cli/commands.py`
- Test: `tests/cli/test_commands.py`

- [x] **Step 1: Write the failing test**

```python
from nanobot.cli.commands import _build_investment_service
from nanobot.config.schema import Config


def test_build_investment_service_uses_workspace_scoped_dependencies(tmp_path):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")

    bus = object()
    session_manager = object()
    enabled_channels = {"weixin", "telegram"}

    service = _build_investment_service(
        config=config,
        bus=bus,
        session_manager=session_manager,
        enabled_channels=enabled_channels,
    )

    assert service is not None
    assert service.workspace == config.workspace_path
    assert service.bus is bus
    assert service.session_manager is session_manager
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_commands.py -k investment_service -v`
Expected: FAIL with `ImportError` or `AttributeError` because `_build_investment_service` does not exist yet

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/cli/commands.py
from nanobot.investment.data import AkshareMarketDataProvider, CHINA_MARKET_TIMEZONE
from nanobot.investment.service import InvestmentAssistantService


def _build_investment_service(*, config, bus, session_manager, enabled_channels):
    return InvestmentAssistantService(
        workspace=config.workspace_path,
        session_manager=session_manager,
        bus=bus,
        market_data=AkshareMarketDataProvider(timezone=CHINA_MARKET_TIMEZONE),
        timezone=CHINA_MARKET_TIMEZONE,
        enabled_channels=enabled_channels,
    )
```

```python
# nanobot/cli/commands.py inside _run_gateway()
investment_service = _build_investment_service(
    config=config,
    bus=bus,
    session_manager=session_manager,
    enabled_channels=set(channels.enabled_channels),
)


async def run():
    try:
        await cron.start()
        await heartbeat.start()
        await investment_service.start()
        tasks = [
            agent.run(),
            channels.start_all(),
            _health_server(config.gateway.host, port),
        ]
        if open_browser_url:
            tasks.append(_open_browser_when_ready())
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        console.print("\nShutting down...")
    except Exception:
        import traceback

        console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
        console.print(traceback.format_exc())
    finally:
        await agent.close_mcp()
        investment_service.stop()
        heartbeat.stop()
        cron.stop()
        agent.stop()
        await channels.stop_all()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_commands.py -k investment_service -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/cli/commands.py tests/cli/test_commands.py
git commit -m "feat: wire investment service into gateway runtime"
```
