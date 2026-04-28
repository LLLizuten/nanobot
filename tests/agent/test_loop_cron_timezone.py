import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.investment.store import InvestmentStore


def test_agent_loop_registers_cron_tool_with_configured_timezone(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=CronService(tmp_path / "cron" / "jobs.json"),
        timezone="Asia/Shanghai",
    )

    cron_tool = loop.tools.get("cron")

    assert isinstance(cron_tool, CronTool)
    assert cron_tool._default_timezone == "Asia/Shanghai"


def test_agent_loop_initializes_investment_store_and_registers_commands(tmp_path: Path) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    assert isinstance(loop.investment_store, InvestmentStore)
    assert isinstance(loop.investment_lock, asyncio.Lock)
    assert loop.investment_store.workspace == tmp_path
    assert loop.commands.is_dispatchable_command("/invest")
    assert loop.commands.is_dispatchable_command("/invest show")


@pytest.mark.asyncio
async def test_agent_loop_process_message_returns_friendly_investment_state_error(
    tmp_path: Path,
) -> None:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.investment_store.path.parent.mkdir(parents=True, exist_ok=True)
    loop.investment_store.path.write_text("{not-json", encoding="utf-8")

    response = await loop._process_message(
        InboundMessage(
            channel="cli",
            sender_id="user-1",
            chat_id="direct",
            content="/invest show",
        )
    )

    assert response is not None
    assert "Investment state file" in response.content
    assert "fix or delete" in response.content
    assert "investment/state.json" in response.content
    assert response.metadata == {"render_as": "text"}
