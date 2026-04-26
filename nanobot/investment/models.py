"""Investment state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Literal

RiskMode = Literal["conservative", "balanced", "aggressive"]
AssetKind = Literal["stock", "etf"]
TrancheState = Literal["flat", "entry", "add1", "full"]


@dataclass
class WatchlistEntry:
    symbol: str
    kind: AssetKind
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | WatchlistEntry) -> WatchlistEntry:
        if isinstance(payload, cls):
            return payload
        return cls(**payload)


@dataclass
class PositionRecord:
    symbol: str
    kind: AssetKind
    cost_basis: float
    tranche_state: TrancheState
    latest_buy_date: str
    shares: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "cost_basis": self.cost_basis,
            "tranche_state": self.tranche_state,
            "latest_buy_date": self.latest_buy_date,
            "shares": self.shares,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | PositionRecord) -> PositionRecord:
        if isinstance(payload, cls):
            return payload
        return cls(**payload)


@dataclass
class InvestmentState:
    mode: RiskMode = "balanced"
    scan_period_minutes: int = 60
    watchlist: dict[str, WatchlistEntry] = field(default_factory=dict)
    positions: dict[str, PositionRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scanPeriodMinutes": self.scan_period_minutes,
            "watchlist": {
                symbol: entry.to_dict() for symbol, entry in self.watchlist.items()
            },
            "positions": {
                symbol: record.to_dict() for symbol, record in self.positions.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | InvestmentState) -> InvestmentState:
        if isinstance(payload, cls):
            return payload

        data = dict(payload)
        data["scan_period_minutes"] = data.pop("scanPeriodMinutes", data.get("scan_period_minutes", 60))
        data["watchlist"] = cls._load_symbol_map(
            raw_value=data.get("watchlist"),
            field_name="watchlist",
            record_type=WatchlistEntry,
        )
        data["positions"] = cls._load_symbol_map(
            raw_value=data.get("positions"),
            field_name="positions",
            record_type=PositionRecord,
        )
        return cls(**data)

    @staticmethod
    def _load_symbol_map(
        *,
        raw_value: Any,
        field_name: str,
        record_type: type[WatchlistEntry] | type[PositionRecord],
    ) -> dict[str, WatchlistEntry] | dict[str, PositionRecord]:
        if raw_value is None:
            return {}
        if not isinstance(raw_value, Mapping):
            raise ValueError(f"{field_name} must be a mapping keyed by symbol")

        records: dict[str, WatchlistEntry] | dict[str, PositionRecord] = {}
        for symbol, raw_record in raw_value.items():
            record = record_type.from_dict(raw_record)
            if record.symbol != symbol:
                raise ValueError(
                    f"{field_name} key '{symbol}' does not match nested symbol '{record.symbol}'"
                )
            records[str(symbol)] = record
        return records
