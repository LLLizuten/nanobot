import pytest

from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry


def test_investment_state_defaults_are_stable():
    state = InvestmentState()

    assert state.mode == "balanced"
    assert state.scan_period_minutes == 60
    assert state.watchlist == {}
    assert state.positions == {}


def test_investment_state_round_trip_preserves_symbol_keyed_records():
    state = InvestmentState(
        mode="balanced",
        scan_period_minutes=15,
        watchlist={
            "SPY": WatchlistEntry(
                symbol="SPY",
                kind="etf",
                note="index core",
            ),
        },
        positions={
            "QQQ": PositionRecord(
                symbol="QQQ",
                kind="etf",
                cost_basis=512.4,
                tranche_state="add1",
                latest_buy_date="2026-04-20",
                shares=8,
            ),
        },
    )

    payload = state.to_dict()

    assert payload == {
        "mode": "balanced",
        "scanPeriodMinutes": 15,
        "watchlist": {
            "SPY": {
                "symbol": "SPY",
                "kind": "etf",
                "note": "index core",
            },
        },
        "positions": {
            "QQQ": {
                "symbol": "QQQ",
                "kind": "etf",
                "cost_basis": 512.4,
                "tranche_state": "add1",
                "latest_buy_date": "2026-04-20",
                "shares": 8,
            },
        },
    }

    restored = InvestmentState.from_dict(payload)

    assert restored == state
    assert restored.watchlist["SPY"].kind == "etf"
    assert restored.watchlist["SPY"].note == "index core"
    assert restored.positions["QQQ"].kind == "etf"
    assert restored.positions["QQQ"].cost_basis == 512.4
    assert restored.positions["QQQ"].tranche_state == "add1"
    assert restored.positions["QQQ"].latest_buy_date == "2026-04-20"
    assert restored.positions["QQQ"].shares == 8


def test_investment_state_from_dict_treats_none_mappings_as_empty_dicts():
    restored = InvestmentState.from_dict(
        {
            "mode": "balanced",
            "scanPeriodMinutes": 30,
            "watchlist": None,
            "positions": None,
        }
    )

    assert restored.watchlist == {}
    assert restored.positions == {}


def test_investment_state_from_dict_rejects_symbol_key_mismatches():
    with pytest.raises(ValueError, match="watchlist.*SPY.*QQQ"):
        InvestmentState.from_dict(
            {
                "watchlist": {
                    "SPY": {
                        "symbol": "QQQ",
                        "kind": "etf",
                        "note": "",
                    }
                }
            }
        )

    with pytest.raises(ValueError, match="positions.*QQQ.*SPY"):
        InvestmentState.from_dict(
            {
                "positions": {
                    "QQQ": {
                        "symbol": "SPY",
                        "kind": "stock",
                        "cost_basis": 100.0,
                        "tranche_state": "entry",
                        "latest_buy_date": "2026-04-20",
                        "shares": 1,
                    }
                }
            }
        )
