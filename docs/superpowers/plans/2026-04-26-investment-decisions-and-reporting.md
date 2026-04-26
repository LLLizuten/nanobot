# Investment Decisions And Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把技术信号与用户持仓翻译成可执行动作，并生成适合微信发送的状态播报和正式信号文本。

**Architecture:** `decisions.py` 只负责“技术状态 -> 用户动作”的翻译，包含固定分批和 `T+1` 约束；`reporting.py` 只负责消息排版，不直接访问存储或抓行情。这样调度层只需要组合输入输出，不承载业务判断。

**Tech Stack:** Python 3.11, dataclasses, datetime, pytest

---

### Task 1: 持仓感知决策引擎

**Files:**
- Create: `nanobot/investment/decisions.py`
- Test: `tests/investment/test_decisions.py`

- [ ] **Step 1: Write the failing test**

```python
from nanobot.investment.decisions import decide_recommendation
from nanobot.investment.models import PositionRecord
from nanobot.investment.signals import TechnicalSignal


def test_entry_signal_without_position_becomes_buy() -> None:
    signal = TechnicalSignal("entry", "breakout", "lose breakout", "trend may fail")

    rec = decide_recommendation(
        symbol="510300",
        kind="etf",
        signal=signal,
        position=None,
        as_of_date="2026-04-26",
    )

    assert rec.action == "buy"
    assert rec.target_tranche == "entry"
    assert rec.executable is True


def test_same_day_exit_signal_is_marked_not_executable_under_t1() -> None:
    signal = TechnicalSignal("exit", "breakout failed", "n/a", "protect capital")
    position = PositionRecord(
        symbol="600519",
        kind="stock",
        cost_basis=1788.0,
        tranche_state="entry",
        latest_buy_date="2026-04-26",
        shares=100,
    )

    rec = decide_recommendation(
        symbol="600519",
        kind="stock",
        signal=signal,
        position=position,
        as_of_date="2026-04-26",
    )

    assert rec.action == "sell"
    assert rec.executable is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_decisions.py -v`
Expected: FAIL with `ImportError: cannot import name 'decide_recommendation'`

- [ ] **Step 3: Write minimal implementation**

```python
# nanobot/investment/decisions.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nanobot.investment.models import PositionRecord, TrancheState
from nanobot.investment.signals import TechnicalSignal

Action = Literal["buy", "add", "reduce", "sell", "hold", "watch"]


@dataclass
class Recommendation:
    symbol: str
    action: Action
    target_tranche: TrancheState
    executable: bool
    reason: str
    invalidation: str
    risk_note: str


def decide_recommendation(
    *,
    symbol: str,
    kind: str,
    signal: TechnicalSignal,
    position: PositionRecord | None,
    as_of_date: str,
) -> Recommendation:
    if position is None and signal.state == "entry":
        return Recommendation(symbol, "buy", "entry", True, signal.reason, signal.invalidation, signal.risk_note)
    if position is None:
        return Recommendation(symbol, "watch", "flat", True, signal.reason, signal.invalidation, signal.risk_note)

    executable = not (position.latest_buy_date == as_of_date and signal.state == "exit")
    if signal.state == "exit":
        return Recommendation(symbol, "sell", "flat", executable, signal.reason, signal.invalidation, signal.risk_note)
    if signal.state == "reduce":
        return Recommendation(symbol, "reduce", "entry", True, signal.reason, signal.invalidation, signal.risk_note)
    if signal.state == "entry" and position.tranche_state == "entry":
        return Recommendation(symbol, "add", "add1", True, signal.reason, signal.invalidation, signal.risk_note)
    if signal.state == "entry" and position.tranche_state == "add1":
        return Recommendation(symbol, "add", "full", True, signal.reason, signal.invalidation, signal.risk_note)
    return Recommendation(symbol, "hold", position.tranche_state, True, signal.reason, signal.invalidation, signal.risk_note)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_decisions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/investment/decisions.py tests/investment/test_decisions.py
git commit -m "feat: add investment decision engine"
```

### Task 2: 微信播报文本格式化

**Files:**
- Create: `nanobot/investment/reporting.py`
- Test: `tests/investment/test_reporting.py`

- [ ] **Step 1: Write the failing test**

```python
from nanobot.investment.decisions import Recommendation
from nanobot.investment.reporting import format_cycle_report


def test_cycle_report_highlights_changed_formal_signals() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 4, "positions": 2},
        recommendations=[
            Recommendation("510300", "add", "add1", True, "breakout confirmed", "lose breakout", "trend may fail")
        ],
        changed_symbols={"510300"},
    )

    assert "状态播报" in report
    assert "正式信号" in report
    assert "510300" in report
    assert "add" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/investment/test_reporting.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_cycle_report'`

- [ ] **Step 3: Write minimal implementation**

```python
# nanobot/investment/reporting.py
from __future__ import annotations

from nanobot.investment.decisions import Recommendation


def format_cycle_report(
    *,
    generated_at: str,
    summary: dict[str, int],
    recommendations: list[Recommendation],
    changed_symbols: set[str],
) -> str:
    lines = [
        f"【状态播报 | {generated_at}】",
        f"自选池: {summary['watchlist']} 只",
        f"持仓中: {summary['positions']} 只",
        f"本轮新增正式信号: {sum(1 for item in recommendations if item.symbol in changed_symbols)} 条",
        "",
    ]
    for item in recommendations:
        if item.symbol not in changed_symbols:
            continue
        lines.extend([
            "【正式信号】",
            f"标的: {item.symbol}",
            f"建议: {item.action}",
            f"原因: {item.reason}",
            f"失效条件: {item.invalidation}",
            f"风险提示: {item.risk_note}",
            f"当前可执行: {'是' if item.executable else '否'}",
            "",
        ])
    return "\n".join(lines).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/investment/test_reporting.py tests/investment/test_decisions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/investment/reporting.py tests/investment/test_reporting.py
git commit -m "feat: add investment report formatting"
```
