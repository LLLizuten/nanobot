"""Background investment scan service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.investment.analysis import analyze_symbol
from nanobot.investment.data import OptionalDependencyMissingError, resolve_market_timezone
from nanobot.investment.decisions import Recommendation
from nanobot.investment.reporting import FORMAL_ACTIONS, format_cycle_report
from nanobot.investment.store import InvestmentStore


class InvestmentAssistantService:
    def __init__(
        self,
        *,
        workspace: Path,
        session_manager: Any,
        bus: Any,
        market_data: Any,
        timezone: str | None = None,
        enabled_channels: set[str] | None = None,
        poll_interval_s: int = 30,
        is_open_day: Callable[[date], bool] | None = None,
    ) -> None:
        self.workspace = workspace
        self.session_manager = session_manager
        self.bus = bus
        self.market_data = market_data
        self.timezone = resolve_market_timezone(timezone)
        self.enabled_channels = set(enabled_channels or ())
        self.poll_interval_s = poll_interval_s
        self.is_open_day = is_open_day or (lambda day: day.weekday() < 5)
        self.store = InvestmentStore(workspace)
        self._task: asyncio.Task[Any] | None = None
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
        if self._task is None:
            return

        self._task.cancel()
        self._task = None

    async def scan_once(self, now: datetime | None = None) -> bool:
        current_now = now or self._current_time()
        if self._dependency_disabled or not self._is_trading_time(current_now):
            return False

        state = self.store.load()
        if not state.watchlist:
            return False

        recommendations: list[Recommendation] = []
        bar_markers: dict[str, str] = {}

        for symbol, entry in state.watchlist.items():
            try:
                result = analyze_symbol(
                    market_data=self.market_data,
                    symbol=symbol,
                    kind=entry.kind,
                    period_minutes=state.scan_period_minutes,
                    mode=state.mode,
                    position=state.positions.get(symbol),
                )
            except OptionalDependencyMissingError as exc:
                logger.warning("Investment service disabled after dependency error: {}", exc)
                self._dependency_disabled = True
                return False
            except RuntimeError as exc:
                logger.warning(
                    "Investment scan skipped after runtime error for {}: {}", symbol, exc
                )
                return False

            if result is None:
                continue

            bar_markers[symbol] = result.latest_bar_ends_at.isoformat()
            recommendations.append(result.recommendation)

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
            logger.warning(
                "Investment scan skipped publish because no enabled external channel is routable"
            )
            return False

        channel, chat_id = target
        await self.bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=report)
        )
        self._last_published_bar_markers.update(bar_markers)
        self._last_formal_snapshot = self._merge_formal_snapshot(recommendations)
        return True

    def _is_trading_time(self, now: datetime) -> bool:
        if not self.is_open_day(now.date()):
            return False

        current = now.timetz().replace(tzinfo=None)
        return time(9, 30) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)

    def _pick_target(self) -> tuple[str, str] | None:
        if self.session_manager is None:
            return None

        sessions = list(self.session_manager.list_sessions())

        for session in sessions:
            key = session.get("key", "")
            if key.startswith("weixin:"):
                chat_id = key.split(":", 1)[1]
                if "weixin" in self.enabled_channels and chat_id:
                    return ("weixin", chat_id)

        for session in sessions:
            key = session.get("key", "")
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel not in {"cli", "system"} and chat_id:
                if channel not in self.enabled_channels:
                    continue
                return (channel, chat_id)

        return None

    def _current_time(self) -> datetime:
        try:
            return datetime.now(tz=ZoneInfo(self.timezone))
        except Exception:
            logger.warning(
                "Invalid investment service timezone '{}', falling back to local time",
                self.timezone,
            )
            return datetime.now().astimezone()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Investment assistant scan failed")

            await asyncio.sleep(self.poll_interval_s)

    def _formal_snapshot(
        self,
        recommendations: list[Recommendation],
    ) -> dict[str, tuple[str, str, str, bool]]:
        snapshot: dict[str, tuple[str, str, str, bool]] = {}
        for item in recommendations:
            if item.action not in FORMAL_ACTIONS:
                continue
            snapshot[item.symbol] = (
                item.action,
                item.current_tranche,
                item.target_tranche,
                item.executable,
            )
        return snapshot

    def _has_new_completed_bar(self, bar_markers: dict[str, str]) -> bool:
        for symbol, marker in bar_markers.items():
            if self._last_published_bar_markers.get(symbol) != marker:
                return True
        return False

    def _diff_formal_symbols(self, recommendations: list[Recommendation]) -> set[str]:
        snapshot = self._formal_snapshot(recommendations)
        changed: set[str] = set()
        for symbol, payload in snapshot.items():
            if self._last_formal_snapshot.get(symbol) != payload:
                changed.add(symbol)
        return changed

    def _merge_formal_snapshot(
        self,
        recommendations: list[Recommendation],
    ) -> dict[str, tuple[str, str, str, bool]]:
        snapshot = dict(self._last_formal_snapshot)
        for item in recommendations:
            if item.action in FORMAL_ACTIONS:
                snapshot[item.symbol] = (
                    item.action,
                    item.current_tranche,
                    item.target_tranche,
                    item.executable,
                )
                continue
            snapshot.pop(item.symbol, None)
        return snapshot
