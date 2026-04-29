from datetime import datetime

import pytest

from nanobot.investment.data import AkshareMarketDataProvider


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return list(self._rows)


def test_provider_normalizes_a_share_rows() -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 09:30:00",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.9,
            "收盘": 10.4,
            "成交量": 123456,
        },
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        now_provider=lambda: datetime(2026, 4, 26, 11, 30),
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=1,
    )

    assert len(bars) == 1
    assert bars[0].symbol == "600519"
    assert bars[0].ends_at == datetime(2026, 4, 26, 10, 30)
    assert bars[0].close == 10.6
    assert bars[0].complete is True


def test_provider_uses_etf_endpoint() -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 3.95,
            "最高": 4.01,
            "最低": 3.94,
            "收盘": 4.0,
            "成交量": 456789,
        }
    ]

    class _FakeAkshare:
        @staticmethod
        def fund_etf_hist_min_em(symbol, period, adjust):
            assert symbol == "510300"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        now_provider=lambda: datetime(2026, 4, 26, 11, 30),
    )

    bars = provider.fetch_completed_bars(
        symbol="510300",
        kind="etf",
        period_minutes=60,
        limit=1,
    )

    assert len(bars) == 1
    assert bars[0].kind == "etf"
    assert bars[0].close == 4.0


def test_provider_raises_clear_error_when_optional_dependency_is_missing() -> None:
    def _raise_import_error():
        raise ImportError("akshare not installed")

    provider = AkshareMarketDataProvider(loader=_raise_import_error)

    with pytest.raises(RuntimeError, match=r'pip install -e "\.\[investment\]"'):
        provider.fetch_completed_bars(
            symbol="510300",
            kind="etf",
            period_minutes=60,
            limit=1,
        )


def test_provider_rejects_unsupported_kind() -> None:
    class _FakeAkshare:
        pass

    provider = AkshareMarketDataProvider(loader=lambda: _FakeAkshare)

    with pytest.raises(ValueError, match="unsupported asset kind: crypto"):
        provider.fetch_completed_bars(
            symbol="BTCUSDT",
            kind="crypto",
            period_minutes=60,
            limit=1,
        )


def test_provider_drops_unfinished_tail_bar() -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 09:30:00",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.9,
            "收盘": 10.4,
            "成交量": 123456,
        },
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        now_provider=lambda: datetime(2026, 4, 26, 10, 29),
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=2,
    )

    assert len(bars) == 1
    assert bars[0].ends_at == datetime(2026, 4, 26, 9, 30)
    assert bars[0].complete is True


def test_provider_treats_non_one_minute_tail_timestamp_as_bar_end_time() -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 09:30:00",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.9,
            "收盘": 10.4,
            "成交量": 123456,
        },
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        now_provider=lambda: datetime(2026, 4, 26, 10, 30),
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=2,
    )

    assert len(bars) == 2
    assert bars[-1].ends_at == datetime(2026, 4, 26, 10, 30)
    assert bars[-1].complete is True


def test_provider_treats_one_minute_tail_timestamp_as_next_minute_completion() -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 09:30:00",
            "开盘": 10.0,
            "最高": 10.5,
            "最低": 9.9,
            "收盘": 10.4,
            "成交量": 123456,
        },
        {
            "时间": "2026-04-26 09:31:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "1"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        now_provider=lambda: datetime(2026, 4, 26, 9, 32),
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=1,
        limit=2,
    )

    assert len(bars) == 2
    assert bars[-1].ends_at == datetime(2026, 4, 26, 9, 31)
    assert bars[-1].complete is True


def test_provider_uses_configured_timezone_for_default_current_time(monkeypatch) -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    class _FakeDateTime:
        @staticmethod
        def fromisoformat(value: str) -> datetime:
            return datetime.fromisoformat(value)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return datetime(2026, 4, 26, 2, 30)
            return datetime(2026, 4, 26, 10, 30, tzinfo=tz)

    monkeypatch.setattr("nanobot.investment.data.datetime", _FakeDateTime)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
        timezone="Asia/Shanghai",
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=1,
    )

    assert len(bars) == 1
    assert bars[0].ends_at == datetime(2026, 4, 26, 10, 30)
    assert bars[0].complete is True


def test_provider_defaults_to_china_market_timezone_for_default_current_time(monkeypatch) -> None:
    fake_rows = [
        {
            "时间": "2026-04-26 10:30:00",
            "开盘": 10.4,
            "最高": 10.8,
            "最低": 10.2,
            "收盘": 10.6,
            "成交量": 234567,
        },
    ]

    class _FakeAkshare:
        @staticmethod
        def stock_zh_a_hist_min_em(symbol, period, adjust):
            assert symbol == "600519"
            assert period == "60"
            assert adjust == ""
            return _FakeFrame(fake_rows)

    class _FakeDateTime:
        @staticmethod
        def fromisoformat(value: str) -> datetime:
            return datetime.fromisoformat(value)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return datetime(2026, 4, 26, 2, 30)
            return datetime(2026, 4, 26, 10, 30, tzinfo=tz)

    monkeypatch.setattr("nanobot.investment.data.datetime", _FakeDateTime)

    provider = AkshareMarketDataProvider(
        loader=lambda: _FakeAkshare,
    )

    bars = provider.fetch_completed_bars(
        symbol="600519",
        kind="stock",
        period_minutes=60,
        limit=1,
    )

    assert len(bars) == 1
    assert bars[0].ends_at == datetime(2026, 4, 26, 10, 30)
    assert bars[0].complete is True


def test_provider_rejects_non_positive_limit() -> None:
    def _unexpected_loader():
        raise AssertionError("loader should not be called")

    provider = AkshareMarketDataProvider(loader=_unexpected_loader)

    with pytest.raises(ValueError, match="limit must be greater than 0"):
        provider.fetch_completed_bars(
            symbol="510300",
            kind="etf",
            period_minutes=60,
            limit=0,
        )
