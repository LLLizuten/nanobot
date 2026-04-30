"""Investment slash command handlers."""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.investment.analysis import AnalysisResult, analyze_symbol
from nanobot.investment.data import OptionalDependencyMissingError
from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry
from nanobot.investment.reporting import format_positions_status_report, format_status_report

_VALID_KINDS = {"stock", "etf"}
_VALID_MODES = {"conservative", "balanced", "aggressive"}
_VALID_TRANCHE_STATES = {"flat", "entry", "add1", "full"}
_DEPENDENCY_MISSING_MESSAGE = (
    "Investment market data dependency is missing. Please install the investment extra."
)


@dataclass(frozen=True)
class _StatusAnalysisFailure:
    symbol: str
    recoverable: bool
    message: str


def register_investment_commands(router: CommandRouter) -> None:
    """Register investment slash commands."""
    router.exact("/invest", cmd_invest_help)
    router.prefix("/invest ", cmd_invest)


async def cmd_invest_help(ctx: CommandContext) -> OutboundMessage:
    """Return available investment commands."""
    return _reply(
        ctx,
        "\n".join(
            [
                "Investment commands:",
                "/invest watch add <symbol> <stock|etf>",
                "/invest watch remove <symbol>",
                "/invest position set <symbol> <stock|etf> <cost_basis> <tranche_state> <latest_buy_date> <shares>",
                "/invest position clear <symbol>",
                "/invest mode <conservative|balanced|aggressive>",
                "/invest interval <minutes>",
                "/invest show",
                "/invest status <symbol>",
                "/invest status positions",
            ]
        ),
    )


async def cmd_invest(ctx: CommandContext) -> OutboundMessage:
    """Handle investment workspace commands."""
    parts = ctx.args.strip().split()
    if not parts:
        return await cmd_invest_help(ctx)

    if parts[:1] == ["status"]:
        state = _load_state_for_command(ctx)
        if isinstance(state, OutboundMessage):
            return state
        return _handle_status_command(ctx, state, parts)

    async with _investment_lock(ctx):
        return await _handle_invest_command(ctx, parts)


async def _handle_invest_command(ctx: CommandContext, parts: list[str]) -> OutboundMessage:
    """Run the load-mutate-save investment command flow."""
    state = _load_state_for_command(ctx)
    if isinstance(state, OutboundMessage):
        return state
    store = ctx.loop.investment_store

    if parts[:2] == ["watch", "add"] and len(parts) == 4:
        symbol = _normalize_symbol(parts[2])
        kind = _parse_kind(parts[3])
        if kind is None:
            return _reply(ctx, "Invalid asset kind. Use `stock` or `etf`.")
        state.watchlist[symbol] = WatchlistEntry(symbol=symbol, kind=kind)
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Added `{symbol}` to watchlist as {kind}.")

    if parts[:2] == ["watch", "remove"] and len(parts) == 3:
        symbol = _normalize_symbol(parts[2])
        removed = state.watchlist.pop(symbol, None)
        if removed is None:
            return _reply(ctx, f"`{symbol}` is not in the watchlist.")
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Removed `{symbol}` from watchlist.")

    if parts[:2] == ["position", "set"] and len(parts) == 8:
        symbol = _normalize_symbol(parts[2])
        kind = _parse_kind(parts[3])
        if kind is None:
            return _reply(ctx, "Invalid asset kind. Use `stock` or `etf`.")

        try:
            cost_basis = float(parts[4])
        except ValueError:
            return _reply(ctx, "Invalid cost basis. Use a number like `505.2`.")
        if not math.isfinite(cost_basis) or cost_basis <= 0:
            return _reply(ctx, "Invalid cost basis. Use a positive finite number.")

        tranche_state = parts[5].lower()
        if tranche_state not in _VALID_TRANCHE_STATES:
            return _reply(ctx, "Invalid tranche state. Use `flat`, `entry`, `add1`, or `full`.")

        latest_buy_date = parts[6]
        try:
            date.fromisoformat(latest_buy_date)
        except ValueError:
            return _reply(ctx, "Invalid latest buy date. Use ISO format like `2026-04-25`.")

        try:
            shares = int(parts[7])
        except ValueError:
            return _reply(ctx, "Invalid shares. Use an integer.")
        if shares <= 0:
            return _reply(ctx, "Invalid shares. Use a positive integer.")

        state.positions[symbol] = PositionRecord(
            symbol=symbol,
            kind=kind,
            cost_basis=cost_basis,
            tranche_state=tranche_state,
            latest_buy_date=latest_buy_date,
            shares=shares,
        )
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Saved position for `{symbol}`.")

    if parts[:2] == ["position", "clear"] and len(parts) == 3:
        symbol = _normalize_symbol(parts[2])
        removed = state.positions.pop(symbol, None)
        if removed is None:
            return _reply(ctx, f"No saved position for `{symbol}`.")
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Cleared position for `{symbol}`.")

    if parts[0] == "mode" and len(parts) == 2:
        mode = parts[1].lower()
        if mode not in _VALID_MODES:
            return _reply(
                ctx,
                "Invalid mode. Use `conservative`, `balanced`, or `aggressive`.",
            )
        state.mode = mode
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Set investment mode to `{mode}`.")

    if parts[0] == "interval" and len(parts) == 2:
        try:
            minutes = int(parts[1])
        except ValueError:
            return _reply(ctx, "Invalid interval. Use an integer number of minutes.")
        if minutes <= 0:
            return _reply(ctx, "Invalid interval. Minutes must be greater than zero.")
        state.scan_period_minutes = minutes
        if error := _save_state(ctx, store, state):
            return error
        return _reply(ctx, f"Set scan interval to `{minutes}` minutes.")

    if parts == ["show"]:
        return _reply(ctx, _format_state(state))

    return await cmd_invest_help(ctx)


def _handle_status_command(
    ctx: CommandContext,
    state: InvestmentState,
    parts: list[str],
) -> OutboundMessage:
    market_data = _get_market_data(ctx)
    if market_data is None:
        return _reply(ctx, "Investment market data is unavailable. Please enable investment data.")

    if parts == ["status", "positions"]:
        if not state.positions:
            return _reply(ctx, "当前没有持仓，无法查询持仓动态状态。")
        results = []
        failed_symbols = []
        for symbol, position in state.positions.items():
            result = _analyze_status_symbol(
                ctx=ctx,
                market_data=market_data,
                state=state,
                symbol=symbol,
                kind=position.kind,
                position=position,
            )
            if isinstance(result, _StatusAnalysisFailure):
                if not result.recoverable:
                    return _reply(ctx, result.message)
                failed_symbols.append(symbol)
                continue
            if result is not None:
                results.append(result)
        if not results:
            if failed_symbols:
                return _reply(
                    ctx,
                    f"持仓标的动态状态查询失败: {', '.join(failed_symbols)}。请稍后重试。",
                )
            return _reply(ctx, "持仓标的暂无最新完整周期行情。")
        return _reply(ctx, format_positions_status_report(results, failed_symbols=failed_symbols))

    if len(parts) == 2:
        symbol = _normalize_symbol(parts[1])
        kind = _lookup_symbol_kind(state, symbol)
        if kind is None:
            return _reply(ctx, f"`{symbol}` 不在自选池或持仓中，请先添加后再查询动态状态。")
        result = _analyze_status_symbol(
            ctx=ctx,
            market_data=market_data,
            state=state,
            symbol=symbol,
            kind=kind,
            position=state.positions.get(symbol),
        )
        if isinstance(result, _StatusAnalysisFailure):
            return _reply(ctx, result.message)
        if result is None:
            return _reply(ctx, f"`{symbol}` 暂无最新完整周期行情。")
        return _reply(ctx, format_status_report(result))

    return _reply(ctx, "用法: `/invest status <symbol>` 或 `/invest status positions`。")


def _lookup_symbol_kind(state: InvestmentState, symbol: str) -> str | None:
    if symbol in state.watchlist:
        return state.watchlist[symbol].kind
    if symbol in state.positions:
        return state.positions[symbol].kind
    return None


def _get_market_data(ctx: CommandContext):
    return getattr(ctx.loop, "investment_market_data", None) or getattr(
        ctx.loop, "market_data", None
    )


def _load_state_for_command(ctx: CommandContext) -> InvestmentState | OutboundMessage:
    store = ctx.loop.investment_store
    try:
        return store.load()
    except (OSError, ValueError):
        return _reply(
            ctx,
            "Investment state file is unreadable. Please fix or delete "
            "`investment/state.json` and try again.",
        )


def _analyze_status_symbol(
    *,
    ctx: CommandContext,
    market_data,
    state: InvestmentState,
    symbol: str,
    kind: str,
    position: PositionRecord | None,
) -> AnalysisResult | _StatusAnalysisFailure | None:
    try:
        return analyze_symbol(
            market_data=market_data,
            symbol=symbol,
            kind=kind,
            period_minutes=state.scan_period_minutes,
            mode=state.mode,
            position=position,
        )
    except OptionalDependencyMissingError:
        return _StatusAnalysisFailure(
            symbol=symbol,
            recoverable=False,
            message=_DEPENDENCY_MISSING_MESSAGE,
        )
    except RuntimeError as exc:
        return _StatusAnalysisFailure(
            symbol=symbol,
            recoverable=True,
            message=f"动态状态查询失败: {exc}",
        )


@asynccontextmanager
async def _investment_lock(ctx: CommandContext):
    lock = getattr(ctx.loop, "investment_lock", None)
    if lock is None:
        yield
        return

    async with lock:
        yield


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _parse_kind(kind: str) -> str | None:
    value = kind.lower()
    if value not in _VALID_KINDS:
        return None
    return value


def _format_state(state: InvestmentState) -> str:
    watchlist = (
        ", ".join(f"{entry.symbol} ({entry.kind})" for entry in state.watchlist.values())
        or "(empty)"
    )
    positions = (
        ", ".join(
            (
                f"{record.symbol} ({record.kind}) cost={record.cost_basis:g} "
                f"tranche={record.tranche_state} date={record.latest_buy_date} "
                f"shares={record.shares if record.shares is not None else '-'}"
            )
            for record in state.positions.values()
        )
        or "(empty)"
    )
    return "\n".join(
        [
            "Investment state:",
            f"Mode: {state.mode}",
            f"Interval: {state.scan_period_minutes} minutes",
            f"Watchlist: {watchlist}",
            f"Positions: {positions}",
        ]
    )


def _save_state(
    ctx: CommandContext,
    store,
    state: InvestmentState,
) -> OutboundMessage | None:
    try:
        store.save(state)
    except OSError:
        return _reply(
            ctx,
            "Investment state could not be saved. Please check workspace write access "
            "and try again.",
        )
    return None


def _reply(ctx: CommandContext, content: str) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )
