# Investment Chat Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户通过聊天命令维护投资助手的一期状态，包括自选池、持仓、风险模式和扫描周期。

**Architecture:** 在 `nanobot.command` 下增加独立的投资命令模块，用单一前缀 `/invest` 承载子命令。命令处理层只负责解析、校验与格式化回复，真实读写统一委托给 `InvestmentStore`。

**Tech Stack:** Python 3.11, existing `CommandRouter`, pytest, workspace-backed JSON state

---

### Task 1: `/invest` 命令处理器

**Files:**
- Create: `nanobot/command/investment.py`
- Test: `tests/command/test_investment_commands.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from types import SimpleNamespace

from nanobot.bus.events import InboundMessage
from nanobot.command.investment import cmd_invest
from nanobot.command.router import CommandContext
from nanobot.investment.store import InvestmentStore


@pytest.mark.asyncio
async def test_invest_watch_add_updates_workspace_state(tmp_path):
    loop = SimpleNamespace(investment_store=InvestmentStore(tmp_path))
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="/invest watch add 510300 etf",
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/invest watch add 510300 etf", args="watch add 510300 etf", loop=loop)

    response = await cmd_invest(ctx)

    assert response is not None
    assert "510300" in response.content
    state = InvestmentStore(tmp_path).load()
    assert state.watchlist["510300"].kind == "etf"


@pytest.mark.asyncio
async def test_invest_mode_updates_risk_profile(tmp_path):
    loop = SimpleNamespace(investment_store=InvestmentStore(tmp_path))
    msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="/invest mode aggressive",
    )
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/invest mode aggressive", args="mode aggressive", loop=loop)

    response = await cmd_invest(ctx)

    assert response is not None
    assert "aggressive" in response.content
    assert InvestmentStore(tmp_path).load().mode == "aggressive"


@pytest.mark.asyncio
async def test_invest_position_and_interval_are_persisted(tmp_path):
    loop = SimpleNamespace(investment_store=InvestmentStore(tmp_path))

    position_msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="/invest position set 600519 stock 1788.0 entry 2026-04-26 100",
    )
    position_ctx = CommandContext(
        msg=position_msg,
        session=None,
        key=position_msg.session_key,
        raw=position_msg.content,
        args="position set 600519 stock 1788.0 entry 2026-04-26 100",
        loop=loop,
    )
    await cmd_invest(position_ctx)

    interval_msg = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="/invest interval 30",
    )
    interval_ctx = CommandContext(
        msg=interval_msg,
        session=None,
        key=interval_msg.session_key,
        raw=interval_msg.content,
        args="interval 30",
        loop=loop,
    )
    await cmd_invest(interval_ctx)

    state = InvestmentStore(tmp_path).load()
    assert state.positions["600519"].cost_basis == 1788.0
    assert state.scan_period_minutes == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/command/test_investment_commands.py -v`
Expected: FAIL because `/invest` is not registered and `loop.investment_store` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# nanobot/command/investment.py
from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.investment.models import PositionRecord, WatchlistEntry


def register_investment_commands(router: CommandRouter) -> None:
    router.exact("/invest", cmd_invest_help)
    router.prefix("/invest ", cmd_invest)


async def cmd_invest_help(ctx: CommandContext) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Usage: /invest watch|position|mode|interval|show",
        metadata={"render_as": "text"},
    )


async def cmd_invest(ctx: CommandContext) -> OutboundMessage:
    tokens = ctx.args.strip().split()
    state = ctx.loop.investment_store.load()

    if len(tokens) == 4 and tokens[:2] == ["watch", "add"]:
        symbol = tokens[2]
        kind = tokens[3]
        state.watchlist[symbol] = WatchlistEntry(symbol=symbol, kind=kind)
        content = f"Added {symbol} to watchlist as {kind}."
    elif len(tokens) == 3 and tokens[:2] == ["watch", "remove"]:
        symbol = tokens[2]
        state.watchlist.pop(symbol, None)
        content = f"Removed {symbol} from watchlist."
    elif len(tokens) == 8 and tokens[:2] == ["position", "set"]:
        symbol, kind, cost_basis, tranche_state, latest_buy_date, shares = tokens[2:]
        state.positions[symbol] = PositionRecord(
            symbol=symbol,
            kind=kind,
            cost_basis=float(cost_basis),
            tranche_state=tranche_state,
            latest_buy_date=latest_buy_date,
            shares=int(shares),
        )
        content = f"Recorded position for {symbol}."
    elif len(tokens) == 3 and tokens[:2] == ["position", "clear"]:
        symbol = tokens[2]
        state.positions.pop(symbol, None)
        content = f"Cleared position for {symbol}."
    elif len(tokens) == 2 and tokens[0] == "mode":
        mode = tokens[1]
        state.mode = mode
        content = f"Investment mode set to {mode}."
    elif len(tokens) == 2 and tokens[0] == "interval":
        state.scan_period_minutes = int(tokens[1])
        content = f"Investment scan period set to {tokens[1]} minutes."
    elif tokens == ["show"]:
        content = (
            f"Mode: {state.mode}\n"
            f"Scan Period: {state.scan_period_minutes}m\n"
            f"Watchlist: {', '.join(sorted(state.watchlist)) or '(empty)'}\n"
            f"Positions: {', '.join(sorted(state.positions)) or '(empty)'}"
        )
    else:
        content = "Unknown /invest command."
    ctx.loop.investment_store.save(state)
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/command/test_investment_commands.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/command/investment.py tests/command/test_investment_commands.py
git commit -m "feat: add investment slash commands"
```

### Task 2: 命令注册与帮助文本接入

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/command/__init__.py`
- Modify: `nanobot/command/builtin.py`
- Test: `tests/cli/test_restart_command.py`

- [ ] **Step 1: Write the failing test**

```python
from nanobot.command.builtin import build_help_text


def test_help_lists_investment_commands() -> None:
    help_text = build_help_text()
    assert "/invest" in help_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_restart_command.py::test_help_lists_investment_commands -v`
Expected: FAIL because help text does not mention `/invest`

- [ ] **Step 3: Write minimal implementation**

```python
# nanobot/command/__init__.py
from nanobot.command.builtin import register_builtin_commands
from nanobot.command.investment import register_investment_commands
from nanobot.command.router import CommandContext, CommandRouter

__all__ = [
    "CommandContext",
    "CommandRouter",
    "register_builtin_commands",
    "register_investment_commands",
]
```

```python
# nanobot/agent/loop.py
from nanobot.command import (
    CommandContext,
    CommandRouter,
    register_builtin_commands,
    register_investment_commands,
)
from nanobot.investment.store import InvestmentStore

self.investment_store = InvestmentStore(self.workspace)
self.commands = CommandRouter()
register_builtin_commands(self.commands)
register_investment_commands(self.commands)
```

```python
# nanobot/command/builtin.py
def build_help_text() -> str:
    lines = [
        "🐈 nanobot commands:",
        "",
        "/status — Show bot status",
        "/help — Show available commands",
        "/invest — Manage investment assistant state",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_restart_command.py::test_help_lists_investment_commands tests/command/test_investment_commands.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/loop.py nanobot/command/__init__.py nanobot/command/builtin.py tests/cli/test_restart_command.py
git commit -m "feat: register investment commands"
```
