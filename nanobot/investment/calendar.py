"""China market trading calendar helpers for investment scans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from nanobot.investment.data import _load_akshare


class CalendarStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TradingCalendarCheck:
    status: CalendarStatus
    reason: str


class AkshareTradingCalendar:
    def __init__(self, loader: Callable[[], Any] = _load_akshare) -> None:
        self._loader = loader
        self._trading_days: set[date] | None = None
        self._range: tuple[date, date] | None = None
        self._permanent_load_error: str | None = None
        self._last_load_error: str | None = None

    def check_day(self, day: date) -> TradingCalendarCheck:
        if not self._ensure_loaded():
            return TradingCalendarCheck(
                status=CalendarStatus.UNKNOWN,
                reason=self._last_load_error or "trading calendar unavailable",
            )

        if self._range is None or self._trading_days is None:
            return TradingCalendarCheck(
                status=CalendarStatus.UNKNOWN,
                reason="trading calendar unavailable",
            )

        first_day, last_day = self._range
        if day < first_day or day > last_day:
            return TradingCalendarCheck(
                status=CalendarStatus.UNKNOWN,
                reason="outside loaded trading calendar range",
            )

        if day in self._trading_days:
            return TradingCalendarCheck(status=CalendarStatus.OPEN, reason="listed trading day")

        return TradingCalendarCheck(status=CalendarStatus.CLOSED, reason="not listed as trading day")

    def _ensure_loaded(self) -> bool:
        if self._trading_days is not None:
            return True
        if self._permanent_load_error is not None:
            self._last_load_error = self._permanent_load_error
            return False

        try:
            ak = self._loader()
        except ImportError:
            self._permanent_load_error = 'AkShare is not installed. Run `pip install -e ".[investment]"`.'
            self._last_load_error = self._permanent_load_error
            return False

        try:
            frame = ak.tool_trade_date_hist_sina()
            rows = frame.to_dict(orient="records")
            trading_days = {_parse_trade_date(row["trade_date"]) for row in rows}
        except Exception as exc:
            self._last_load_error = f"trading calendar unavailable: {exc}"
            return False

        if not trading_days:
            self._last_load_error = "trading calendar unavailable: no trading dates returned"
            return False

        self._trading_days = trading_days
        self._range = (min(trading_days), max(trading_days))
        self._last_load_error = None
        return True


def _parse_trade_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
