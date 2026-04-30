# Investment Sell-Side Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the investment signal engine so it can produce real `hold`, `reduce`, and `exit` states in addition to existing `entry` and `watch` states.

**Architecture:** Keep the existing investment layers intact. `nanobot/investment/signals.py` remains responsible for technical state detection, while `nanobot/investment/decisions.py` continues translating those states into position-aware recommendations. The shared `analysis.py` pipeline should benefit automatically because it already calls `evaluate_trend_breakout`.

**Tech Stack:** Python 3.11+, pytest, existing `nanobot.investment.market.Bar` and `TechnicalSignal` models.

---

## Files

- Modify: `tests/investment/test_signals.py`
- Modify: `nanobot/investment/signals.py`
- Modify: `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`

## Behavior Rules

Use only completed bars via `completed_bars_only`.

Keep existing entry behavior:

- `entry` still requires breakout level, volume confirmation, and trend confirmation.
- Risk modes continue to control breakout buffer and volume confirmation.

Add sell-side maintenance states:

- `hold`: latest completed close is above or equal to the short moving average, and the short moving average is above or equal to the medium moving average.
- `reduce`: latest completed close is below the short moving average while still above or equal to the medium moving average, or latest volume is meaningfully elevated while the candle closes weakly versus its own range.
- `exit`: latest completed close is below the medium moving average while the short moving average is below the medium moving average, or the latest two completed closes are both below the previous breakout reference level.
- `watch`: insufficient data or no actionable/maintenance condition.

Recommended exact thresholds:

- Short moving average: latest 5 completed closes.
- Medium moving average: latest 10 completed closes.
- Breakout reference: highest high from the 10 completed bars immediately before the latest bar.
- Failed breakout exit: the latest two completed closes are both below the breakout reference.
- Weak close for reduce: latest volume is at least `1.2 * average volume of the previous five completed bars`, and latest close is in the lower 40% of the latest bar range.

## Task 1: Add Failing Signal Tests

**Files:**
- Modify: `tests/investment/test_signals.py`

- [x] **Step 1: Add focused test helpers**

Add helpers that make maintenance scenarios readable:

```python
def _bars_from_closes(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[Bar]:
    start = datetime(2026, 4, 26, 9, 30)
    if volumes is None:
        volumes = [100.0] * len(closes)
    if highs is None:
        highs = [close + 0.1 for close in closes]
    if lows is None:
        lows = [close - 0.1 for close in closes]

    return [
        Bar(
            symbol="510300",
            kind="etf",
            ends_at=start + timedelta(hours=idx),
            open=close,
            high=highs[idx],
            low=lows[idx],
            close=close,
            volume=volumes[idx],
            complete=True,
        )
        for idx, close in enumerate(closes)
    ]
```

- [x] **Step 2: Add hold test**

```python
def test_returns_hold_when_trend_remains_healthy_without_new_breakout() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.95],
        highs=[11.2] * 10 + [11.0],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "hold"
    assert "trend remains healthy" in signal.reason.lower()
```

- [x] **Step 3: Add reduce test for short moving average loss**

```python
def test_returns_reduce_when_latest_close_loses_short_average_but_holds_medium_average() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 11.0, 11.0, 11.0, 11.0, 11.0, 10.55],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "reduce"
    assert "short moving average" in signal.reason.lower()
```

- [x] **Step 4: Add reduce test for high-volume weak close**

```python
def test_returns_reduce_when_high_volume_weak_close_shows_momentum_fading() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.85],
        volumes=[100.0] * 10 + [150.0],
        highs=[10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.1, 11.2],
        lows=[9.9, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.8],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "reduce"
    assert "momentum" in signal.reason.lower()
```

- [x] **Step 5: Add exit test for broken moving average structure**

```python
def test_returns_exit_when_price_and_short_average_lose_medium_average() -> None:
    bars = _bars_from_closes(
        [11.0, 11.0, 11.0, 11.0, 11.0, 10.4, 10.3, 10.2, 10.1, 10.0, 9.9],
        volumes=[100.0] * 11,
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "exit"
    assert "medium moving average" in signal.reason.lower()
```

- [x] **Step 6: Add exit test for failed breakout**

```python
def test_returns_exit_when_two_completed_closes_fail_below_breakout_reference() -> None:
    bars = _bars_from_closes(
        [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.2, 10.6, 10.5],
        volumes=[100.0] * 11,
        highs=[10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.4, 10.8, 10.7],
    )

    signal = evaluate_trend_breakout(bars, mode="balanced")

    assert signal.state == "exit"
    assert "breakout reference" in signal.reason.lower()
```

- [x] **Step 7: Run tests to verify RED**

Run:

```bash
pytest tests/investment/test_signals.py -q
```

Expected: the newly added `hold`, `reduce`, and `exit` tests fail because `evaluate_trend_breakout` still returns `watch` for these scenarios.

## Task 2: Implement Sell-Side Signal States

**Files:**
- Modify: `nanobot/investment/signals.py`

- [x] **Step 1: Add small helper calculations**

Inside `evaluate_trend_breakout`, after existing moving average and volume calculations, compute:

```python
previous = rows[-2]
previous_breakout_failed = previous.close < recent_high
latest_breakout_failed = latest.close < recent_high
medium_trend_broken = latest.close < medium_ma and short_ma < medium_ma
short_support_lost = latest.close < short_ma and latest.close >= medium_ma
latest_range = latest.high - latest.low
weak_range_close = latest_range > 0 and latest.close <= latest.low + latest_range * 0.4
momentum_fading = latest.volume >= avg_volume * 1.2 and weak_range_close
trend_healthy = latest.close >= short_ma >= medium_ma
```

- [x] **Step 2: Preserve existing entry branch first**

Keep this check before sell-side states:

```python
if latest.close >= breakout_level and volume_confirmed and trend_confirmed:
    return TechnicalSignal(
        state="entry",
        reason="breakout above recent range with volume and trend confirmation",
        invalidation="lose the breakout level on completed bars",
        risk_note="突破失败时通常会快速回落",
    )
```

- [x] **Step 3: Add exit branches before reduce**

```python
if previous_breakout_failed and latest_breakout_failed:
    return TechnicalSignal(
        state="exit",
        reason="two completed closes failed below the breakout reference",
        invalidation="reclaim the breakout reference on completed bars",
        risk_note="突破失败可能导致趋势快速转弱",
    )

if medium_trend_broken:
    return TechnicalSignal(
        state="exit",
        reason="price and short moving average lost the medium moving average",
        invalidation="reclaim the medium moving average with improving short-term trend",
        risk_note="中期趋势失守时应优先控制回撤",
    )
```

- [x] **Step 4: Add reduce branches**

```python
if short_support_lost:
    return TechnicalSignal(
        state="reduce",
        reason="latest close lost the short moving average while holding the medium moving average",
        invalidation="recover the short moving average on completed bars",
        risk_note="短线转弱但中期结构尚未完全破坏",
    )

if momentum_fading:
    return TechnicalSignal(
        state="reduce",
        reason="high-volume weak close suggests momentum is fading",
        invalidation="recover with a strong close and normalized volume",
        risk_note="放量弱收可能意味着突破动能衰减",
    )
```

- [x] **Step 5: Add hold branch**

```python
if trend_healthy:
    return TechnicalSignal(
        state="hold",
        reason="trend remains healthy without a fresh breakout signal",
        invalidation="lose the short moving average or show failed breakout behavior",
        risk_note="趋势仍健康，但未出现新的加仓确认",
    )
```

- [x] **Step 6: Keep existing watch fallback**

Keep the final fallback as `watch`, with the existing incomplete-condition wording.

- [x] **Step 7: Run focused tests**

Run:

```bash
pytest tests/investment/test_signals.py -q
```

Expected: all signal tests pass.

## Task 3: Verify Decision Integration and Update Status Doc

**Files:**
- Modify: `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`
- Optional test read-only verification: `tests/investment/test_decisions.py`

- [x] **Step 1: Run integration-adjacent tests**

Run:

```bash
pytest tests/investment/test_signals.py tests/investment/test_decisions.py tests/investment/test_service.py -q
```

Expected: all selected investment tests pass.

- [x] **Step 2: Update implementation status**

In `docs/superpowers/specs/2026-04-29-investment-assistant-gap-closure-design.md`, change the sell-side section under `## 实施状态` from `[待完成]` to `[已完成]` and record:

```markdown
- `[已完成]` 卖出侧信号补齐
  - `signals.py` 已能基于已收盘完整 K 线真实产出 `hold / reduce / exit`。
  - `hold` 覆盖已有趋势健康但无新增突破确认的状态。
  - `reduce` 覆盖短期均线失守但中期结构尚存、以及放量弱收的动能衰减状态。
  - `exit` 覆盖连续两根已收盘 K 线跌回突破参考位下方、以及价格和短期均线同步失守中期均线的结构破坏状态。
  - 已通过 `pytest tests/investment/test_signals.py tests/investment/test_decisions.py tests/investment/test_service.py -q` 验证。
```

- [x] **Step 3: Run final focused verification**

Run:

```bash
pytest tests/investment/test_signals.py tests/investment/test_decisions.py tests/investment/test_service.py -q
```

Expected: all selected investment tests pass after the documentation update.

## Self-Review Checklist

- Spec coverage: covers the documented gap for real `hold / reduce / exit` signal output.
- Scope control: does not add automatic trading, new strategies, full-market scanning, or extra position management.
- Structure: keeps signal detection in `signals.py` and recommendation translation in `decisions.py`.
- TDD: test additions precede production code changes.
- Documentation: gap spec status is updated only after verification.
