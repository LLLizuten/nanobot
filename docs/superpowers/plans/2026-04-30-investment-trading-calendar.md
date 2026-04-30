# Investment Trading Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the investment assistant use a real China A-share trading calendar so scheduled scans skip weekends, legal market holidays, and unconfirmed calendar states while still allowing make-up trading days.

**Architecture:** Add a focused trading calendar adapter under `nanobot/investment/` that loads AkShare trading dates once, caches them in memory, and returns a tri-state answer to distinguish open, closed, and unknown days. Keep `InvestmentAssistantService` responsible for time-window gating, but replace the default weekday fallback with the calendar adapter. CLI service construction wires the default AkShare calendar provider.

**Tech Stack:** Python 3.11+, pytest, existing optional `akshare` investment dependency, existing AkShare loader pattern.

---

## Files

- Create: `nanobot/investment/calendar.py`
- Create: `tests/investment/test_calendar.py`
- Modify: `nanobot/investment/service.py`
- Modify: `nanobot/cli/commands.py`
- Modify: `tests/investment/test_service.py`
- Modify: `tests/cli/test_commands.py`
- Modify: `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`

## Behavior Rules

- Use AkShare `tool_trade_date_hist_sina()` as the default trading date source.
- Treat dates included in the loaded AkShare `trade_date` column as open trading days.
- Treat dates within the loaded calendar range but absent from `trade_date` as closed days. This covers weekends, legal holidays, and non-trading weekdays.
- Treat dates outside the loaded calendar range as unknown, not as closed. The scheduler must skip scans on unknown dates.
- Treat optional dependency import failure and calendar runtime failures as unknown, not open.
- Cache loaded calendar dates for the provider instance so repeated scans do not repeatedly call AkShare.
- Preserve explicit test injection: existing tests that pass `is_open_day=lambda ...` must keep working.
- Do not add a new dependency beyond the existing `investment` extra.
- Do not add automatic trading, broad market scanning, or new user commands.
- Do not create git commits unless the user explicitly asks.

## External Reference

AkShare official docs list `tool_trade_date_hist_sina()` as the stock trading calendar interface and show the output column as `trade_date`: https://akshare.akfamily.xyz/data/tool/tool.html

## Task 1: Add Trading Calendar Provider Tests

**Files:**
- Create: `tests/investment/test_calendar.py`
- Create later production target: `nanobot/investment/calendar.py`

- [ ] **Step 1: Write tests for open, closed, make-up, and out-of-range days**

Create `tests/investment/test_calendar.py` with fake frames instead of importing pandas:

```python
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
```

- [ ] **Step 2: Write tests for optional dependency and runtime failures**

Append to `tests/investment/test_calendar.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_calendar.py -q
```

Expected: FAIL because `nanobot.investment.calendar` does not exist yet.

## Task 2: Implement Trading Calendar Provider

**Files:**
- Create: `nanobot/investment/calendar.py`
- Test: `tests/investment/test_calendar.py`

- [ ] **Step 1: Implement calendar models and provider**

Create `nanobot/investment/calendar.py`:

```python
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
        self._load_error: str | None = None

    def check_day(self, day: date) -> TradingCalendarCheck:
        if not self._ensure_loaded():
            return TradingCalendarCheck(
                status=CalendarStatus.UNKNOWN,
                reason=self._load_error or "trading calendar unavailable",
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
        if self._load_error is not None:
            return False

        try:
            ak = self._loader()
        except ImportError:
            self._load_error = 'AkShare is not installed. Run `pip install -e ".[investment]"`.'
            return False

        try:
            frame = ak.tool_trade_date_hist_sina()
            rows = frame.to_dict(orient="records")
            trading_days = {_parse_trade_date(row["trade_date"]) for row in rows}
        except Exception as exc:
            self._load_error = f"trading calendar unavailable: {exc}"
            return False

        if not trading_days:
            self._load_error = "trading calendar unavailable: no trading dates returned"
            return False

        self._trading_days = trading_days
        self._range = (min(trading_days), max(trading_days))
        return True


def _parse_trade_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
```

- [ ] **Step 2: Run focused calendar tests**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_calendar.py -q
```

Expected: PASS.

## Task 3: Make Service Gating Conservative on Unknown Calendar Days

**Files:**
- Modify: `nanobot/investment/service.py`
- Modify: `tests/investment/test_service.py`

- [ ] **Step 1: Add service tests for tri-state calendar checks**

Append to `tests/investment/test_service.py`:

```python
from nanobot.investment.calendar import CalendarStatus, TradingCalendarCheck
```

Then add these tests near the existing trading-time tests:

```python
def test_service_accepts_open_calendar_check_inside_trading_window(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        trading_calendar=lambda _day: TradingCalendarCheck(
            status=CalendarStatus.OPEN,
            reason="listed trading day",
        ),
    )

    assert service._is_trading_time(datetime(2026, 5, 9, 10, 0)) is True


def test_service_rejects_closed_calendar_check_inside_trading_window(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        trading_calendar=lambda _day: TradingCalendarCheck(
            status=CalendarStatus.CLOSED,
            reason="not listed as trading day",
        ),
    )

    assert service._is_trading_time(datetime(2026, 5, 5, 10, 0)) is False


def test_service_rejects_unknown_calendar_check_inside_trading_window(tmp_path) -> None:
    service = InvestmentAssistantService(
        workspace=tmp_path,
        session_manager=None,
        bus=_FakeBus(),
        market_data=_SequenceMarketData([_make_bars()]),
        trading_calendar=lambda _day: TradingCalendarCheck(
            status=CalendarStatus.UNKNOWN,
            reason="outside loaded trading calendar range",
        ),
    )

    assert service._is_trading_time(datetime(2027, 1, 4, 10, 0)) is False
```

- [ ] **Step 2: Run service tests to verify RED**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_service.py::test_service_accepts_open_calendar_check_inside_trading_window tests/investment/test_service.py::test_service_rejects_closed_calendar_check_inside_trading_window tests/investment/test_service.py::test_service_rejects_unknown_calendar_check_inside_trading_window -q
```

Expected: FAIL because `InvestmentAssistantService.__init__` has no `trading_calendar` argument.

- [ ] **Step 3: Update service constructor and trading-time gating**

Modify `nanobot/investment/service.py` imports:

```python
from nanobot.investment.calendar import (
    AkshareTradingCalendar,
    CalendarStatus,
    TradingCalendarCheck,
)
```

Change constructor parameters:

```python
        is_open_day: Callable[[date], bool] | None = None,
        trading_calendar: Callable[[date], TradingCalendarCheck] | None = None,
```

Replace:

```python
        self.is_open_day = is_open_day or (lambda day: day.weekday() < 5)
```

with:

```python
        if trading_calendar is not None:
            self.trading_calendar = trading_calendar
        elif is_open_day is not None:
            self.trading_calendar = lambda day: TradingCalendarCheck(
                status=CalendarStatus.OPEN if is_open_day(day) else CalendarStatus.CLOSED,
                reason="legacy is_open_day override",
            )
        else:
            default_calendar = AkshareTradingCalendar()
            self.trading_calendar = default_calendar.check_day
```

Replace the opening of `_is_trading_time`:

```python
        if not self.is_open_day(now.date()):
            return False
```

with:

```python
        calendar_check = self.trading_calendar(now.date())
        if calendar_check.status is not CalendarStatus.OPEN:
            if calendar_check.status is CalendarStatus.UNKNOWN:
                logger.warning(
                    "Investment scan skipped because trading calendar could not confirm {}: {}",
                    now.date(),
                    calendar_check.reason,
                )
            return False
```

- [ ] **Step 4: Run service tests**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_service.py -q
```

Expected: PASS.

## Task 4: Wire and Verify the Default Calendar in CLI Service Construction

**Files:**
- Modify: `nanobot/cli/commands.py`
- Modify: `tests/cli/test_commands.py`

- [ ] **Step 1: Add CLI construction assertion for calendar provider**

In `tests/cli/test_commands.py`, update `test_build_investment_service_uses_workspace_scoped_dependencies` by adding:

```python
    assert service.trading_calendar.__self__.__class__.__name__ == "AkshareTradingCalendar"
```

- [ ] **Step 2: Run CLI test before explicit CLI wiring**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/cli/test_commands.py::test_build_investment_service_uses_workspace_scoped_dependencies -q
```

Expected: PASS or FAIL depending on whether Task 3 already made the service default visible through CLI construction. If it passes, continue with explicit CLI wiring anyway so dependency construction remains clear at the application boundary.

- [ ] **Step 3: Wire `AkshareTradingCalendar` in `_build_investment_service`**

Modify `nanobot/cli/commands.py`:

```python
    from nanobot.investment.calendar import AkshareTradingCalendar
    from nanobot.investment.data import CHINA_MARKET_TIMEZONE, AkshareMarketDataProvider
```

Then pass the calendar into `InvestmentAssistantService`:

```python
        trading_calendar=AkshareTradingCalendar().check_day,
```

The resulting service construction should include both market data and calendar dependencies:

```python
    return InvestmentAssistantService(
        workspace=config.workspace_path,
        session_manager=session_manager,
        bus=bus,
        market_data=AkshareMarketDataProvider(timezone=CHINA_MARKET_TIMEZONE),
        timezone=CHINA_MARKET_TIMEZONE,
        enabled_channels=enabled_channels,
        trading_calendar=AkshareTradingCalendar().check_day,
    )
```

- [ ] **Step 4: Run focused CLI tests**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/cli/test_commands.py::test_build_investment_service_uses_workspace_scoped_dependencies tests/cli/test_commands.py::test_build_investment_service_uses_china_market_timezone_when_global_timezone_is_non_china -q
```

Expected: PASS.

## Task 5: Verify Integration and Update Gap Status

**Files:**
- Modify: `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`
- Read-only verification: `tests/investment/test_calendar.py`, `tests/investment/test_service.py`, `tests/cli/test_commands.py`

- [ ] **Step 1: Run focused investment and CLI verification**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_calendar.py tests/investment/test_service.py tests/cli/test_commands.py::test_build_investment_service_uses_workspace_scoped_dependencies tests/cli/test_commands.py::test_build_investment_service_uses_china_market_timezone_when_global_timezone_is_non_china -q
```

Expected: PASS.

- [ ] **Step 2: Update implementation status in the gap spec**

In `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`, change:

```markdown
- `[待完成]` 真实交易日历补齐
  - 后台调度仍需接入中国市场真实交易日历，以覆盖法定休市日与调休交易日。
```

to:

```markdown
- `[已完成]` 真实交易日历补齐
  - 已新增基于 AkShare `tool_trade_date_hist_sina()` 的中国市场交易日历适配层。
  - 后台调度已从简单工作日判断切换为真实交易日历判断，支持法定休市日跳过与调休交易日播报。
  - 交易日历返回未知或数据源不可用时，调度层按“保守不播报”处理。
  - 已保留 `is_open_day` 测试注入能力，便于既有服务测试继续精确控制开市日。
  - 已通过 `uv run --python 3.12 --extra dev pytest tests/investment/test_calendar.py tests/investment/test_service.py tests/cli/test_commands.py::test_build_investment_service_uses_workspace_scoped_dependencies tests/cli/test_commands.py::test_build_investment_service_uses_china_market_timezone_when_global_timezone_is_non_china -q` 验证。
```

- [ ] **Step 3: Run final focused verification after docs update**

Run:

```bash
uv run --python 3.12 --extra dev pytest tests/investment/test_calendar.py tests/investment/test_service.py tests/cli/test_commands.py::test_build_investment_service_uses_workspace_scoped_dependencies tests/cli/test_commands.py::test_build_investment_service_uses_china_market_timezone_when_global_timezone_is_non_china -q
```

Expected: PASS.

- [ ] **Step 4: Inspect uncommitted changes**

Run:

```bash
git status --short
```

Expected: changed files are limited to the calendar provider, service wiring, tests, and gap spec. Do not commit.

## Self-Review Checklist

- Spec coverage: implements legal holiday skip, weekend skip, make-up trading day support, and conservative unknown handling.
- Scope control: does not add automatic trading, new commands, backtesting, UI, or broader strategy changes.
- Structure: keeps calendar fetching in `calendar.py`, time-window gating in `service.py`, and dependency wiring in CLI construction.
- Testability: tests use fake loaders and fake frames, so they do not require AkShare, pandas, or network access.
- Backward compatibility: existing `is_open_day` injection remains available for tests and callers that need explicit day control.
- Safety: no git commit is part of the plan because project instructions say not to commit unless explicitly requested.
