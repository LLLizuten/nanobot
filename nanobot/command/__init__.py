"""Slash command routing and built-in handlers."""

from nanobot.command.builtin import register_builtin_commands
from nanobot.command.investment import register_investment_commands
from nanobot.command.router import CommandContext, CommandRouter

__all__ = [
    "CommandContext",
    "CommandRouter",
    "register_builtin_commands",
    "register_investment_commands",
]
