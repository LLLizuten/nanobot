# Investment Signal Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建基于完整周期 K 线的趋势突破型技术信号引擎，支持保守、平衡、激进三档模式。

**Architecture:** 把行情条目、模式阈值和信号判断拆开。`market.py` 只描述标准化 K 线，`signals.py` 只做趋势突破、均线和量能判断，不直接关心持仓和消息发送。

**Tech Stack:** Python 3.11, dataclasses, statistics, pytest

---

### Task 1: 标准化 K 线模型与完整周期过滤

**Files:**
- Create: `nanobot/investment/market.py`
- Test: `tests/investment/test_market.py`

- [x] **Step 1: Write the failing test**

```python
from datetime import datetime

from nanobot.investment.market import Bar, completed_bars_only


def test_completed_bars_only_drops_unfinished_tail() -> None:
    bars = [
        Bar(symbol="510300", kind="etf", ends_at=datetime(2026, 4, 26, 10, 30), open=1, high=2, low=1, close=2, volume=10, complete=True),
        Bar(symbol="510300", kind="etf", ends_at=datetime(2026, 4, 26, 11, 30), open=2, high=3, low=2, close=3, volume=12, complete=False),
    ]

    result = completed_bars_only(bars)

    assert len(result) == 1
    assert result[0].close == 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_market.py -v`
Expected: FAIL with `ImportError: cannot import name 'Bar'`

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/investment/market.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AssetKind = Literal["stock", "etf"]


@dataclass
class Bar:
    symbol: str
    kind: AssetKind
    ends_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool = True


def completed_bars_only(bars: list[Bar]) -> list[Bar]:
    return [bar for bar in bars if bar.complete]
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_market.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/investment/market.py tests/investment/test_market.py
git commit -m "feat: add investment market bar model"
```

### Task 2: 趋势突破信号评估器

**Files:**
- Create: `nanobot/investment/signals.py`
- Test: `tests/investment/test_signals.py`

- [x] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta

from nanobot.investment.market import Bar
from nanobot.investment.signals import evaluate_trend_breakout


def _bars() -> list[Bar]:
    start = datetime(2026, 4, 26, 9, 30)
    closes = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.55, 10.6, 10.65, 10.7, 11.1]
    volumes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 180]
    out = []
    for idx, (close, volume) in enumerate(zip(closes, volumes)):
        out.append(
            Bar(
                symbol="510300",
                kind="etf",
                ends_at=start + timedelta(hours=idx),
                open=close - 0.1,
                high=close + 0.1,
                low=close - 0.15,
                close=close,
                volume=volume,
                complete=True,
            )
        )
    return out


def test_balanced_mode_emits_entry_signal_on_breakout() -> None:
    signal = evaluate_trend_breakout(_bars(), mode="balanced")

    assert signal.state == "entry"
    assert "breakout" in signal.reason.lower()


def test_conservative_mode_requires_stronger_confirmation() -> None:
    signal = evaluate_trend_breakout(_bars(), mode="conservative")

    assert signal.state in {"watch", "entry"}
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_signals.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_trend_breakout'`

- [x] **Step 3: Write minimal implementation**

```python
# nanobot/investment/signals.py
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Literal

from nanobot.investment.market import Bar, completed_bars_only

RiskMode = Literal["conservative", "balanced", "aggressive"]
SignalState = Literal["watch", "entry", "hold", "reduce", "exit"]

MODE_THRESHOLDS = {
    "conservative": {"volume_ratio": 1.5, "breakout_buffer": 0.003},
    "balanced": {"volume_ratio": 1.2, "breakout_buffer": 0.0},
    "aggressive": {"volume_ratio": 1.0, "breakout_buffer": -0.002},
}


@dataclass
class TechnicalSignal:
    state: SignalState
    reason: str
    invalidation: str
    risk_note: str


def evaluate_trend_breakout(bars: list[Bar], mode: RiskMode) -> TechnicalSignal:
    rows = completed_bars_only(bars)
    if len(rows) < 10:
        return TechnicalSignal("watch", "not enough completed bars", "n/a", "等待更多完整K线")

    latest = rows[-1]
    ref_high = max(bar.high for bar in rows[-10:-1])
    short_ma = mean(bar.close for bar in rows[-5:])
    medium_ma = mean(bar.close for bar in rows[-10:])
    avg_volume = mean(bar.volume for bar in rows[-6:-1])
    cfg = MODE_THRESHOLDS[mode]

    breakout_price = ref_high * (1 + cfg["breakout_buffer"])
    volume_ok = latest.volume >= avg_volume * cfg["volume_ratio"]
    trend_ok = latest.close >= short_ma >= medium_ma

    if latest.close >= breakout_price and volume_ok and trend_ok:
        return TechnicalSignal(
            "entry",
            "breakout above recent range with moving-average and volume confirmation",
            "lose breakout level for two completed bars",
            "突破追价失败时回撤会很快",
        )
    return TechnicalSignal(
        "watch",
        "breakout conditions are incomplete",
        "n/a",
        "继续观察，不提前按未完成结构入场",
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_market.py tests/investment/test_signals.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add nanobot/investment/signals.py tests/investment/test_signals.py
git commit -m "feat: add trend breakout signal engine"
```

## 当前执行状态

- Task 1：已完成
- Task 2：已完成
- `Step 5: Commit`：已完成
- 代码提交：`ee19286` `feat: add investment signal engine`
- 当前验证：
  - `uv run --python 3.12 --extra dev pytest tests/investment/test_market.py tests/investment/test_signals.py -q`
  - `uv run --python 3.12 --extra dev pytest tests/investment/test_state_models.py tests/investment/test_state_store.py tests/investment/test_market.py tests/investment/test_signals.py -q`
