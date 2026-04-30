from datetime import date

from nanobot.investment.calendar import (
    AkshareTradingCalendar,
    CalendarStatus,
    TradingCalendarCheck,
)


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient: str):
        assert orient == "records"
        return list(self._rows)


class _FakeAkshare:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def tool_trade_date_hist_sina(self):
        self.calls += 1
        return _FakeFrame(self.rows)


def test_akshare_calendar_identifies_open_closed_makeup_and_unknown_days() -> None:
    fake = _FakeAkshare(
        [
            {"trade_date": "2026-05-04"},
            {"trade_date": "2026-05-09"},
            {"trade_date": date(2026, 5, 11)},
        ]
    )
    calendar = AkshareTradingCalendar(loader=lambda: fake)

    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.OPEN,
        reason="listed trading day",
    )
    assert calendar.check_day(date(2026, 5, 5)) == TradingCalendarCheck(
        status=CalendarStatus.CLOSED,
        reason="not listed as trading day",
    )
    assert calendar.check_day(date(2026, 5, 9)).status is CalendarStatus.OPEN
    assert calendar.check_day(date(2027, 1, 4)) == TradingCalendarCheck(
        status=CalendarStatus.UNKNOWN,
        reason="outside loaded trading calendar range",
    )
    assert fake.calls == 1


def test_akshare_calendar_returns_unknown_when_dependency_is_missing() -> None:
    def _missing_loader():
        raise ImportError("no akshare")

    calendar = AkshareTradingCalendar(loader=_missing_loader)

    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.UNKNOWN,
        reason='AkShare is not installed. Run `pip install -e ".[investment]"`.',
    )


def test_akshare_calendar_returns_unknown_when_source_fails() -> None:
    def _broken_loader():
        class _BrokenAkshare:
            def tool_trade_date_hist_sina(self):
                raise RuntimeError("upstream unavailable")

        return _BrokenAkshare()

    calendar = AkshareTradingCalendar(loader=_broken_loader)

    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.UNKNOWN,
        reason="trading calendar unavailable: upstream unavailable",
    )


def test_akshare_calendar_returns_unknown_when_source_returns_no_dates() -> None:
    fake = _FakeAkshare([])
    calendar = AkshareTradingCalendar(loader=lambda: fake)

    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.UNKNOWN,
        reason="trading calendar unavailable: no trading dates returned",
    )


def test_akshare_calendar_retries_after_runtime_source_failure() -> None:
    calls = 0

    def _loader():
        nonlocal calls
        calls += 1
        if calls == 1:
            return _BrokenAkshare()
        return _FakeAkshare([{"trade_date": "2026-05-04"}])

    class _BrokenAkshare:
        def tool_trade_date_hist_sina(self):
            raise RuntimeError("upstream unavailable")

    calendar = AkshareTradingCalendar(loader=_loader)

    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.UNKNOWN,
        reason="trading calendar unavailable: upstream unavailable",
    )
    assert calendar.check_day(date(2026, 5, 4)) == TradingCalendarCheck(
        status=CalendarStatus.OPEN,
        reason="listed trading day",
    )
    assert calls == 2
