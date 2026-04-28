from datetime import datetime

from nanobot.investment.market import Bar, completed_bars_only


def test_completed_bars_only_drops_unfinished_tail() -> None:
    bars = [
        Bar(
            symbol="510300",
            kind="etf",
            ends_at=datetime(2026, 4, 26, 10, 30),
            open=1,
            high=2,
            low=1,
            close=2,
            volume=10,
            complete=True,
        ),
        Bar(
            symbol="510300",
            kind="etf",
            ends_at=datetime(2026, 4, 26, 11, 30),
            open=2,
            high=3,
            low=2,
            close=3,
            volume=12,
            complete=False,
        ),
    ]

    result = completed_bars_only(bars)

    assert len(result) == 1
    assert result[0].close == 2
