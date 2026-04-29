"""Market data providers for investment workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nanobot.investment.market import Bar

CHINA_MARKET_TIMEZONE = "Asia/Shanghai"


class OptionalDependencyMissingError(RuntimeError):
    """Raised when an optional market data dependency is unavailable."""


def _load_akshare() -> Any:
    import akshare as ak

    return ak


def resolve_market_timezone(timezone: str | None) -> str:
    if timezone in {None, "", "UTC"}:
        return CHINA_MARKET_TIMEZONE
    return timezone


class AkshareMarketDataProvider:
    def __init__(
        self,
        loader: Callable[[], Any] = _load_akshare,
        now_provider: Callable[[], datetime] | None = None,
        timezone: str | None = None,
    ) -> None:
        self._loader = loader
        self.timezone = resolve_market_timezone(timezone)
        self._now_provider = now_provider or self._current_time

    def fetch_completed_bars(
        self,
        *,
        symbol: str,
        kind: str,
        period_minutes: int,
        limit: int,
    ) -> list[Bar]:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        if kind not in {"stock", "etf"}:
            raise ValueError(f"unsupported asset kind: {kind}")

        try:
            ak = self._loader()
        except ImportError as exc:
            raise OptionalDependencyMissingError(
                'AkShare is not installed. Run `pip install -e ".[investment]"`.'
            ) from exc

        period = str(period_minutes)
        if kind == "stock":
            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust="")
        else:
            frame = ak.fund_etf_hist_min_em(symbol=symbol, period=period, adjust="")

        rows = frame.to_dict(orient="records")
        now = self._normalize_now(self._now_provider())
        bars: list[Bar] = []

        for index, row in enumerate(rows):
            ends_at = datetime.fromisoformat(row["时间"])
            is_tail = index == len(rows) - 1
            is_complete = not is_tail or self._is_tail_bar_complete(
                ends_at=ends_at,
                period_minutes=period_minutes,
                now=now,
            )
            if not is_complete:
                continue

            bars.append(
                Bar(
                    symbol=symbol,
                    kind=kind,
                    ends_at=ends_at,
                    open=float(row["开盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    close=float(row["收盘"]),
                    volume=float(row["成交量"]),
                    complete=True,
                )
            )

        return bars[-limit:]

    @staticmethod
    def _is_tail_bar_complete(
        *,
        ends_at: datetime,
        period_minutes: int,
        now: datetime,
    ) -> bool:
        if period_minutes != 1:
            return now >= ends_at
        return now >= ends_at + timedelta(minutes=period_minutes)

    def _current_time(self) -> datetime:
        try:
            return datetime.now(tz=ZoneInfo(self.timezone)).replace(tzinfo=None)
        except Exception:
            return datetime.now().astimezone().replace(tzinfo=None)

    def _normalize_now(self, now: datetime) -> datetime:
        if now.tzinfo is None:
            return now

        try:
            return now.astimezone(ZoneInfo(self.timezone)).replace(tzinfo=None)
        except Exception:
            return now.astimezone().replace(tzinfo=None)
