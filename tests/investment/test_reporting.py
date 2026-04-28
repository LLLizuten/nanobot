import pytest

from nanobot.investment.decisions import Recommendation
from nanobot.investment.reporting import ACTION_LABELS, format_cycle_report


def _recommendation(
    *,
    symbol: str = "510300",
    action: str = "add",
    current_tranche: str = "entry",
    target_tranche: str = "add1",
    executable: bool = True,
) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        action=action,
        current_tranche=current_tranche,
        target_tranche=target_tranche,
        executable=executable,
        reason="breakout confirmed",
        invalidation="lose breakout",
        risk_note="trend may fail",
    )


def test_cycle_report_highlights_changed_formal_signals() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 4, "positions": 2},
        recommendations=[_recommendation()],
        changed_symbols={"510300"},
    )

    assert "状态播报" in report
    assert "自选池: 4 只" in report
    assert "持仓中: 2 只" in report
    assert "正式信号" in report
    assert "标的: 510300" in report
    assert "当前持仓状态: entry" in report
    assert "建议动作: 加仓" in report
    assert "原因: breakout confirmed" in report
    assert "失效条件: lose breakout" in report
    assert "风险提示: trend may fail" in report
    assert "当前可执行: 是" in report


def test_cycle_report_omits_unchanged_recommendations_from_formal_signal_section() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 4, "positions": 2},
        recommendations=[
            _recommendation(symbol="510300"),
            _recommendation(symbol="600519", action="buy", current_tranche="flat", target_tranche="entry"),
        ],
        changed_symbols={"510300"},
    )

    assert "本轮新增正式信号: 1 条" in report
    assert "标的: 510300" in report
    assert "标的: 600519" not in report


def test_cycle_report_excludes_watch_and_hold_from_changed_formal_signals() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 4, "positions": 2},
        recommendations=[
            _recommendation(symbol="510300", action="watch", current_tranche="flat", target_tranche="flat"),
            _recommendation(symbol="600519", action="hold", current_tranche="entry", target_tranche="entry"),
        ],
        changed_symbols={"510300", "600519"},
    )

    assert "本轮新增正式信号: 0 条" in report
    assert "【正式信号】" not in report
    assert "标的: 510300" not in report
    assert "标的: 600519" not in report


def test_cycle_report_counts_and_expands_each_changed_symbol_once() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 4, "positions": 2},
        recommendations=[
            _recommendation(symbol="510300", action="watch", current_tranche="flat", target_tranche="flat"),
            _recommendation(symbol="510300", action="buy", current_tranche="flat", target_tranche="entry"),
            _recommendation(symbol="510300", action="add", current_tranche="entry", target_tranche="add1"),
        ],
        changed_symbols={"510300"},
    )

    assert "本轮新增正式信号: 1 条" in report
    assert report.count("【正式信号】") == 1
    assert report.count("标的: 510300") == 1
    assert "建议动作: 买入" in report


@pytest.mark.parametrize(
    "action, label",
    [
        ("buy", "买入"),
        ("add", "加仓"),
        ("reduce", "减仓"),
        ("sell", "卖出"),
        ("hold", "持有"),
        ("watch", "观察"),
    ],
)
def test_cycle_report_uses_chinese_action_labels(action: str, label: str) -> None:
    assert ACTION_LABELS[action] == label

    if action in {"watch", "hold"}:
        return

    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 1, "positions": 1},
        recommendations=[_recommendation(action=action)],
        changed_symbols={"510300"},
    )
    assert f"建议动作: {label}" in report


def test_cycle_report_marks_not_executable_recommendation() -> None:
    report = format_cycle_report(
        generated_at="2026-04-26 10:30",
        summary={"watchlist": 1, "positions": 1},
        recommendations=[_recommendation(action="sell", target_tranche="flat", executable=False)],
        changed_symbols={"510300"},
    )

    assert "建议动作: 卖出" in report
    assert "当前可执行: 否" in report
