import json

import pytest

from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry
from nanobot.investment.store import InvestmentStore


def test_investment_store_save_and_load_round_trip(tmp_path):
    store = InvestmentStore(tmp_path)
    state = InvestmentState(
        mode="aggressive",
        scan_period_minutes=20,
        watchlist={
            "NVDA": WatchlistEntry(
                symbol="NVDA",
                kind="stock",
                note="ai leader",
            ),
        },
        positions={
            "SPY": PositionRecord(
                symbol="SPY",
                kind="etf",
                cost_basis=505.2,
                tranche_state="entry",
                latest_buy_date="2026-04-25",
                shares=12,
            ),
        },
    )

    store.save(state)

    assert store.path == tmp_path / "investment" / "state.json"
    assert store.path.exists()

    restored = store.load()

    assert restored == state


def test_investment_store_load_returns_default_state_when_missing(tmp_path):
    store = InvestmentStore(tmp_path)

    restored = store.load()

    assert restored == InvestmentState()
    assert store.path == tmp_path / "investment" / "state.json"


def test_investment_store_load_delegates_schema_parsing_to_state_model(tmp_path, monkeypatch):
    store = InvestmentStore(tmp_path)
    payload = {
        "mode": "conservative",
        "scanPeriodMinutes": 45,
        "watchlist": {},
        "positions": {},
    }
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    captured_payloads = []
    sentinel = InvestmentState(mode="conservative", scan_period_minutes=45)

    def fake_from_dict(raw_payload):
        captured_payloads.append(raw_payload)
        return sentinel

    monkeypatch.setattr(InvestmentState, "from_dict", fake_from_dict)

    restored = store.load()

    # This store intentionally delegates payload decoding to InvestmentState.
    assert restored is sentinel
    assert captured_payloads == [payload]


def test_investment_store_load_builds_state_from_camel_case_payload(tmp_path):
    store = InvestmentStore(tmp_path)
    payload = {
        "mode": "conservative",
        "scanPeriodMinutes": 45,
        "watchlist": {
            "VTI": {
                "symbol": "VTI",
                "kind": "etf",
                "note": "core index",
            }
        },
        "positions": {
            "AAPL": {
                "symbol": "AAPL",
                "kind": "stock",
                "cost_basis": 187.5,
                "tranche_state": "add1",
                "latest_buy_date": "2026-04-24",
                "shares": 6,
            }
        },
    }
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    restored = store.load()

    assert restored.mode == "conservative"
    assert restored.scan_period_minutes == 45
    assert restored.watchlist["VTI"].note == "core index"
    assert restored.positions["AAPL"].cost_basis == 187.5
    assert restored.positions["AAPL"].tranche_state == "add1"


def test_investment_store_load_raises_value_error_for_invalid_json(tmp_path):
    store = InvestmentStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid investment state file") as exc_info:
        store.load()

    assert exc_info.value.__cause__ is not None


def test_investment_store_save_replaces_state_file_from_temp_file(tmp_path, monkeypatch):
    store = InvestmentStore(tmp_path)
    state = InvestmentState(mode="balanced", scan_period_minutes=10)
    replace_calls = []

    def fake_replace(source, destination):
        replace_calls.append((source, destination))
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        source.unlink()
        return destination

    monkeypatch.setattr(type(store.path), "replace", fake_replace)

    store.save(state)

    assert len(replace_calls) == 1
    source, destination = replace_calls[0]
    assert destination == store.path
    assert json.loads(store.path.read_text(encoding="utf-8")) == state.to_dict()
    assert list(store.path.parent.glob("*.tmp")) == []
