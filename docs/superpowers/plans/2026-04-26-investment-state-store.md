# Investment State Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为投资助手建立工作区级结构化状态存储，保存自选池、持仓、风格模式和扫描周期。

**Architecture:** 新建 `nanobot/investment/` 领域包，把投资状态模型与持久化从聊天命令和调度逻辑中独立出来。所有状态统一落在 `workspace/investment/state.json`，并使用原子写入保证文件损坏时可恢复。

**Tech Stack:** Python 3.11, dataclasses, json, pathlib, pytest

---

### Task 1: 投资状态模型

**Files:**
- Create: `nanobot/investment/__init__.py`
- Create: `nanobot/investment/models.py`
- Test: `tests/investment/test_state_models.py`

- [x] **Step 1: Write the failing test**

```python
from nanobot.investment.models import InvestmentState, PositionRecord, WatchlistEntry


def test_state_defaults_are_stable() -> None:
    state = InvestmentState()

    assert state.mode == "balanced"
    assert state.scan_period_minutes == 60
    assert state.watchlist == {}
    assert state.positions == {}


def test_state_round_trip_preserves_nested_records() -> None:
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")
    state.positions["600519"] = PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1788.0,
        tranche_state="entry",
        latest_buy_date="2026-04-26",
        shares=100,
    )

    restored = InvestmentState.from_dict(state.to_dict())

    assert restored.watchlist["510300"].kind == "etf"
    assert restored.positions["600519"].tranche_state == "entry"
    assert restored.positions["600519"].shares == 100
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_state_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nanobot.investment'`

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/investment/models.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

RiskMode = Literal["conservative", "balanced", "aggressive"]
AssetKind = Literal["stock", "etf"]
TrancheState = Literal["flat", "entry", "add1", "full"]


@dataclass
class WatchlistEntry:
    symbol: str
    kind: AssetKind
    note: str = ""


@dataclass
class PositionRecord:
    symbol: str
    kind: AssetKind
    cost_basis: float
    tranche_state: TrancheState
    latest_buy_date: str
    shares: int | None = None


@dataclass
class InvestmentState:
    mode: RiskMode = "balanced"
    scan_period_minutes: int = 60
    watchlist: dict[str, WatchlistEntry] = field(default_factory=dict)
    positions: dict[str, PositionRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "scanPeriodMinutes": self.scan_period_minutes,
            "watchlist": {k: asdict(v) for k, v in self.watchlist.items()},
            "positions": {k: asdict(v) for k, v in self.positions.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "InvestmentState":
        raw = data or {}
        watchlist = {
            symbol: WatchlistEntry(**payload)
            for symbol, payload in dict(raw.get("watchlist", {})).items()
        }
        positions = {
            symbol: PositionRecord(**payload)
            for symbol, payload in dict(raw.get("positions", {})).items()
        }
        return cls(
            mode=raw.get("mode", "balanced"),
            scan_period_minutes=int(raw.get("scanPeriodMinutes", 60)),
            watchlist=watchlist,
            positions=positions,
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_state_models.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/investment/__init__.py nanobot/investment/models.py tests/investment/test_state_models.py
git commit -m "feat: add investment state models"
```

### Task 2: 工作区状态存储

**Files:**
- Create: `nanobot/investment/store.py`
- Test: `tests/investment/test_state_store.py`

- [x] **Step 1: Write the failing test**

```python
from nanobot.investment.models import InvestmentState, WatchlistEntry
from nanobot.investment.store import InvestmentStore


def test_store_round_trip_writes_workspace_state(tmp_path) -> None:
    store = InvestmentStore(tmp_path)
    state = InvestmentState()
    state.watchlist["510300"] = WatchlistEntry(symbol="510300", kind="etf")

    store.save(state)
    loaded = store.load()

    assert loaded.watchlist["510300"].kind == "etf"
    assert (tmp_path / "investment" / "state.json").exists()


def test_load_returns_default_state_when_file_missing(tmp_path) -> None:
    store = InvestmentStore(tmp_path)

    state = store.load()

    assert state.mode == "balanced"
    assert state.scan_period_minutes == 60
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_state_store.py -v`
Expected: FAIL with `ImportError: cannot import name 'InvestmentStore'`

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/investment/store.py
from __future__ import annotations

import json
from pathlib import Path

from nanobot.investment.models import InvestmentState
from nanobot.utils.helpers import ensure_dir


class InvestmentStore:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.state_dir = ensure_dir(self.workspace / "investment")
        self.path = self.state_dir / "state.json"

    def load(self) -> InvestmentState:
        if not self.path.exists():
            return InvestmentState()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return InvestmentState.from_dict(data)

    def save(self, state: InvestmentState) -> None:
        tmp_path = self.path.with_suffix(".json.tmp")
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_state_store.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/investment/store.py tests/investment/test_state_store.py
git commit -m "feat: add investment workspace store"
```
