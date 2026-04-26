# Investment Scheduler And Live Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 A 股 / 场内 ETF 的准实时完整周期行情，并在交易时段内按配置周期执行扫描与微信播报。

**Architecture:** 用可替换的行情适配器隔离外部数据源；用独立 `InvestmentAssistantService` 负责交易时段判断、调度循环和消息投递；在网关启动流程中注册该服务，但不让 `HeartbeatService` 承担投资业务。AkShare 作为首个数据适配器，通过懒加载保持主程序在未安装投资依赖时仍可运行。

**Tech Stack:** Python 3.11, httpx/pandas via AkShare optional extra, asyncio, existing MessageBus / SessionManager, pytest

---

### Task 1: AkShare 行情适配器

**Files:**
- Modify: `pyproject.toml`
- Create: `nanobot/investment/data.py`
- Test: `tests/investment/test_data_provider.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime

from nanobot.investment.data import AkshareMarketDataProvider


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return list(self._rows)


def test_provider_normalizes_a_share_rows(monkeypatch):
    fake_rows = [
        {"时间": "2026-04-26 10:30:00", "开盘": 10.0, "最高": 10.5, "最低": 9.9, "收盘": 10.4, "成交量": 123456}
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            return _FakeFrame(fake_rows)

    monkeypatch.setattr("nanobot.investment.data._load_akshare", lambda: _FakeAkshare)

    provider = AkshareMarketDataProvider()
    bars = provider.fetch_completed_bars(symbol="600519", kind="stock", period_minutes=60, limit=1)

    assert len(bars) == 1
    assert bars[0].symbol == "600519"
    assert bars[0].close == 10.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_data_provider.py -v`
Expected: FAIL with `ImportError: cannot import name 'AkshareMarketDataProvider'`

- [ ] **Step 3: Write minimal implementation**

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
    def fetch_completed_bars(self, *, symbol: str, kind: str, period_minutes: int, limit: int) -> list[Bar]:
        ak = _load_akshare()
        period = str(period_minutes)
        if kind == "stock":
            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="")
        else:
            frame = ak.fund_etf_hist_min_em(symbol=symbol, period=period, adjust="")
        rows = frame.to_dict(orient="records")[-limit:]
        out: list[Bar] = []
        for row in rows:
            out.append(
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
            )
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_data_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml nanobot/investment/data.py tests/investment/test_data_provider.py
git commit -m "feat: add akshare investment data provider"
```

### Task 2: 交易时段调度与微信播报集成

**Files:**
- Create: `nanobot/investment/service.py`
- Modify: `nanobot/cli/commands.py`
- Test: `tests/investment/test_service.py`
- Test: `tests/cli/test_commands.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from nanobot.investment.service import InvestmentAssistantService


def test_service_runs_only_inside_cn_sessions(tmp_path):
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=None,
        market_data=None,
    )

    assert service._is_trading_time("2026-04-27 10:30") is True
    assert service._is_trading_time("2026-04-27 12:00") is False
    assert service._is_trading_time("2026-04-27 15:30") is False


def test_service_prefers_recent_weixin_target(tmp_path):
    class _FakeSessions:
        def list_sessions(self):
            return [
                {"key": "telegram:chat-2"},
                {"key": "weixin:chat-1"},
            ]

    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=_FakeSessions(),
        bus=None,
        market_data=None,
    )

    assert service._pick_target() == ("weixin", "chat-1")


@pytest.mark.asyncio
async def test_service_formats_and_emits_outbound_message(tmp_path):
    published = []

    class _FakeBus:
        async def publish_outbound(self, msg):
            published.append(msg)

    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=None,
    )

    await service._publish_report("weixin", "chat-1", "测试播报")

    assert len(published) == 1
    assert published[0].channel == "weixin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'InvestmentAssistantService'`

- [ ] **Step 3: Write minimal implementation**

```python
# nanobot/investment/service.py
from __future__ import annotations

from datetime import datetime, time

from nanobot.bus.events import OutboundMessage
from nanobot.investment.store import InvestmentStore


class InvestmentAssistantService:
    def __init__(self, *, workspace, session_manager, bus, market_data):
        self.workspace = workspace
        self.session_manager = session_manager
        self.bus = bus
        self.market_data = market_data
        self.store = InvestmentStore(workspace)

    def _is_trading_time(self, now_text: str) -> bool:
        now = datetime.fromisoformat(now_text)
        if now.weekday() >= 5:
            return False
        current = now.time()
        morning = time(9, 30) <= current <= time(11, 30)
        afternoon = time(13, 0) <= current <= time(15, 0)
        return morning or afternoon

    def _pick_target(self) -> tuple[str, str]:
        if self.session_manager is None:
            return ("weixin", "direct")
        sessions = list(self.session_manager.list_sessions())
        for item in reversed(sessions):
            key = item.get("key", "")
            if key.startswith("weixin:"):
                return ("weixin", key.split(":", 1)[1])
        for item in reversed(sessions):
            key = item.get("key", "")
            if ":" in key:
                channel, chat_id = key.split(":", 1)
                if channel not in {"cli", "system"}:
                    return (channel, chat_id)
        return ("weixin", "direct")

    async def _publish_report(self, channel: str, chat_id: str, content: str) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=content)
        )

    async def scan_once(self, report_text: str) -> None:
        channel, chat_id = self._pick_target()
        await self._publish_report(channel, chat_id, report_text)
```

```python
# nanobot/cli/commands.py
from nanobot.investment.data import AkshareMarketDataProvider
from nanobot.investment.service import InvestmentAssistantService

investment_service = InvestmentAssistantService(
    workspace=config.workspace_path,
    session_manager=session_manager,
    bus=bus,
    market_data=AkshareMarketDataProvider(),
)
```

```python
# tests/cli/test_commands.py
from types import SimpleNamespace

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config


def test_gateway_constructs_investment_service(monkeypatch, tmp_path):
    created = {}
    runner = CliRunner()
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")

    class _FakeInvestmentService:
        def __init__(self, **kwargs):
            created.update(kwargs)

    _patch_cli_command_runtime(
        monkeypatch,
        config,
        message_bus=lambda: object(),
        session_manager=lambda _workspace: object(),
    )
    monkeypatch.setattr("nanobot.investment.service.InvestmentAssistantService", _FakeInvestmentService)
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _store: object())
    monkeypatch.setattr("nanobot.heartbeat.service.HeartbeatService", lambda **kwargs: object())
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", lambda *_args, **_kwargs: SimpleNamespace(enabled_channels=[], start_all=lambda: None, stop_all=lambda: None))
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", lambda **kwargs: SimpleNamespace(model="test-model", bus=SimpleNamespace(publish_outbound=lambda *_a, **_k: None), sessions=SimpleNamespace(get_or_create=lambda *_a, **_k: SimpleNamespace(retain_recent_legal_suffix=lambda *_a, **_k: None), save=lambda *_a, **_k: None), dream=SimpleNamespace(run=lambda: None), tools={}, process_direct=lambda *_a, **_k: None, _connect_mcp=lambda: None, close_mcp=lambda: None))
    monkeypatch.setattr("asyncio.start_server", lambda *args, **kwargs: None)

    result = runner.invoke(app, ["gateway", "--config", str(tmp_path / "config.json")])

    assert result.exit_code == 0
    assert created["workspace"] == config.workspace_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_service.py -v`
Expected: PASS

Run: `pytest tests/cli/test_commands.py -k investment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/investment/service.py nanobot/cli/commands.py tests/investment/test_service.py tests/cli/test_commands.py
git commit -m "feat: add investment scheduler service"
```
