"""Investment slash command handlers."""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from datetime import date

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry

_VALID_KINDS = {"stock", "etf"}
_VALID_MODES = {"conservative", "balanced", "aggressive"}
_VALID_TRANCHE_STATES = {"flat", "entry", "add1", "full"}


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
            ]
        ),
    )


async def cmd_invest(ctx: CommandContext) -> OutboundMessage:
    """Handle investment workspace commands."""
    parts = ctx.args.strip().split()
    if not parts:
        return await cmd_invest_help(ctx)

    async with _investment_lock(ctx):
        return await _handle_invest_command(ctx, parts)


async def _handle_invest_command(ctx: CommandContext, parts: list[str]) -> OutboundMessage:
    """Run the load-mutate-save investment command flow."""
    store = ctx.loop.investment_store
    try:
        state = store.load()
    except (OSError, ValueError):
        return _reply(
            ctx,
            "Investment state file is unreadable. Please fix or delete "
            "`investment/state.json` and try again.",
        )

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
    watchlist = ", ".join(
        f"{entry.symbol} ({entry.kind})" for entry in state.watchlist.values()
    ) or "(empty)"
    positions = ", ".join(
        (
            f"{record.symbol} ({record.kind}) cost={record.cost_basis:g} "
            f"tranche={record.tranche_state} date={record.latest_buy_date} "
            f"shares={record.shares if record.shares is not None else '-'}"
        )
        for record in state.positions.values()
    ) or "(empty)"
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
    ctx: CommandContext, store, state: InvestmentState,
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
