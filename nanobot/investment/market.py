"""Normalized market bar models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AssetKind = Literal["stock", "etf"]


@dataclass
class Bar:
    symbol: str
    kind: AssetKind
    ends_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool = True


def completed_bars_only(bars: list[Bar]) -> list[Bar]:
    return [bar for bar in bars if bar.complete]
