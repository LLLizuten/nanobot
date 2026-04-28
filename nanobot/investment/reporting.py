"""Text formatting for investment cycle reports."""

from __future__ import annotations

from nanobot.investment.decisions import Action, Recommendation

ACTION_LABELS: dict[Action, str] = {
    "buy": "买入",
    "add": "加仓",
    "reduce": "减仓",
    "sell": "卖出",
    "hold": "持有",
    "watch": "观察",
}
FORMAL_ACTIONS: frozenset[Action] = frozenset({"buy", "add", "reduce", "sell"})


def format_cycle_report(
    *,
    generated_at: str,
    summary: dict[str, int],
    recommendations: list[Recommendation],
    changed_symbols: set[str],
) -> str:
    formal_recommendations = _changed_formal_recommendations(
        recommendations=recommendations,
        changed_symbols=changed_symbols,
    )
    changed_count = len(formal_recommendations)
    watchlist_count = summary["watchlist"]
    position_count = summary["positions"]
    lines = [
        f"【状态播报 | {generated_at}】",
        (
            "摘要: "
            f"自选池 {watchlist_count} 只，"
            f"持仓 {position_count} 只，"
            f"本轮新增正式信号 {changed_count} 条"
        ),
        f"自选池: {watchlist_count} 只",
        f"持仓中: {position_count} 只",
        f"本轮新增正式信号: {changed_count} 条",
        "",
    ]

    for item in formal_recommendations:
        lines.extend(
            [
                "【正式信号】",
                f"标的: {item.symbol}",
                f"当前持仓状态: {item.current_tranche}",
                f"建议动作: {ACTION_LABELS[item.action]}",
                f"原因: {item.reason}",
                f"失效条件: {item.invalidation}",
                f"风险提示: {item.risk_note}",
                f"当前可执行: {'是' if item.executable else '否'}",
                "",
            ]
        )

    return "\n".join(lines).strip()


def _changed_formal_recommendations(
    *,
    recommendations: list[Recommendation],
    changed_symbols: set[str],
) -> list[Recommendation]:
    seen_symbols: set[str] = set()
    items: list[Recommendation] = []
    for item in recommendations:
        if item.symbol not in changed_symbols:
            continue
        if item.action not in FORMAL_ACTIONS:
            continue
        if item.symbol in seen_symbols:
            continue
        seen_symbols.add(item.symbol)
        items.append(item)
    return items
