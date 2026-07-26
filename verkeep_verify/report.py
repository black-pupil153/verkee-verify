"""
监控报告生成

聚合 score_snapshots、api_calls 与 Cursor Auto Usage，输出周期性报告。
"""

from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from verkeep_verify.monitor.cursor_usage import (
    PeriodUsageReport,
    aggregate_period,
    aggregate_task,
    cursor_usage_insights,
    format_model_share_line,
    format_output_share_line,
    parse_since,
    period_to_since,
)
from verkeep_verify.storage.database import Database

console = Console()

PERIOD_HOURS = {"daily": 24, "weekly": 24 * 7, "monthly": 24 * 30}
PERIOD_LABELS = {"daily": "日报", "weekly": "周报", "monthly": "月报"}


def _trend(scores: List[float]) -> str:
    """根据首尾分数判断趋势"""
    vals = [s for s in scores if s is not None]
    if len(vals) < 2:
        return "—"
    delta = vals[-1] - vals[0]
    if delta <= -5:
        return f"↓ 下降 {abs(delta):.0f} 分"
    if delta >= 5:
        return f"↑ 上升 {delta:.0f} 分"
    return "→ 稳定"


def _shares_table(
    title: str,
    shares: Dict[str, Dict],
    unit: str,
    pct_fmt: str,
) -> Table:
    table = Table(title=title, expand=True)
    table.add_column("模型", style="cyan")
    table.add_column("占比", justify="right")
    table.add_column("数量", justify="right", style="dim")
    for model, info in shares.items():
        table.add_row(model, f"{info['pct']:{pct_fmt}}%", f"{info['count']} {unit}")
    return table


def load_cursor_period(
    period: str,
    db: Optional[Database] = None,
    refresh: bool = True,
    limit: int = 50,
) -> Optional[PeriodUsageReport]:
    """加载 Cursor 周期数据，必要时先增量导入。"""
    if refresh:
        from verkeep_verify.dashboard_cursor import ensure_imported

        ensure_imported(since=period_to_since(period), full=False)

    since = parse_since(period_to_since(period))
    period_report = aggregate_period(db or Database(), since=since, limit=limit)
    if period_report.task_count == 0:
        return None
    return period_report


def render_cursor_section(
    period: str = "weekly",
    db: Optional[Database] = None,
    refresh: bool = True,
) -> bool:
    """渲染 Cursor Auto Usage 章节，有数据返回 True。"""
    period_report = load_cursor_period(period, db=db, refresh=refresh)
    if not period_report:
        console.print("  [dim]暂无 Cursor 任务数据，先运行 verkeep-verify cursor import[/dim]")
        console.print()
        return False

    console.print(
        f"  {period_report.task_count} 任务 │ "
        f"{period_report.total_requests} 请求 │ "
        f"{period_report.total_output_units} code units │ "
        f"Auto/Mixed {period_report.auto_task_count + period_report.mixed_task_count} 任务"
    )
    console.print()

    if period_report.output_shares:
        console.print(_shares_table("产出占比", period_report.output_shares, "units", ".1f"))
        console.print()
    if period_report.request_shares:
        console.print(_shares_table("请求占比", period_report.request_shares, "requests", ".0f"))
        console.print()

    insights = cursor_usage_insights(period_report)
    if insights:
        console.print("[bold]路由洞察[/bold]")
        for line in insights:
            console.print(f"  • {line}")
        console.print()

    top = sorted(period_report.tasks, key=lambda t: -t.code_unit_count)[:5]
    if top:
        task_table = Table(title="产出 Top 5 任务", expand=True)
        task_table.add_column("ID", style="cyan", no_wrap=True)
        task_table.add_column("标题", max_width=28)
        task_table.add_column("路由")
        task_table.add_column("产出", justify="right")
        task_table.add_column("产出占比", style="bold")
        task_table.add_column("请求占比", style="dim")
        db_ref = db or Database()
        rows_added = 0
        for t in top:
            if t.code_unit_count == 0:
                continue
            detail = aggregate_task(db_ref, t.task_id)
            out_shares = (
                {m: v["pct"] for m, v in detail.output_shares.items()} if detail else {}
            )
            task_table.add_row(
                t.task_id[:8],
                (t.title or "(无标题)")[:28],
                t.route_kind,
                str(t.code_unit_count),
                format_output_share_line(out_shares),
                format_model_share_line(t.model_request_shares),
            )
            rows_added += 1
        if rows_added:
            console.print(task_table)
            console.print()

    console.print(
        "[dim]详情看板: verkeep-verify cursor --since "
        f"{period_to_since(period)}[/dim]"
    )
    console.print()
    return True


def generate_cursor(period: str = "weekly", refresh: bool = True) -> None:
    """生成 Cursor Auto Usage 专项报告。"""
    label = PERIOD_LABELS.get(period, period)
    since_label = period_to_since(period)
    console.print()
    console.print(f"[bold cyan]Cursor Auto Usage {label}[/bold cyan]  (最近 {since_label})")
    console.print()
    render_cursor_section(period, refresh=refresh)
    console.print(
        "[dim]注：占比为本地遥测推断，带置信度标签；"
        "Auto 路由不透明时 unknown 桶不强行分配。[/dim]"
    )
    console.print()


def generate(period: str = "weekly") -> None:
    """生成并打印报告"""
    hours = PERIOD_HOURS.get(period, 24 * 7)
    db = Database()

    snapshots = db.get_score_history(hours=hours, limit=2000)
    call_stats = db.get_stats(hours=hours)

    console.print()
    console.print(f"[bold cyan]Verkeep Verify {period} 报告[/bold cyan]  (最近 {hours} 小时)")
    console.print()

    # 一、调用概况
    console.print("[bold]一、代理调用概况[/bold]")
    console.print(
        f"  总调用 {call_stats['total_calls']} 次 │ "
        f"异常 {call_stats['anomalies']} 次 │ "
        f"平均延迟 {call_stats['avg_latency_ms']}ms"
    )
    console.print()

    # 二、各模型智力打分
    console.print("[bold]二、模型智力打分[/bold]")
    by_model: Dict[str, List[dict]] = {}
    if not snapshots:
        console.print("  [dim]该周期内暂无打分数据，先运行 verkeep-verify score 或 monitor start[/dim]")
        console.print()
    else:
        for s in snapshots:
            by_model.setdefault(s["model"], []).append(s)

        table = Table(expand=True)
        table.add_column("模型", style="cyan")
        table.add_column("打分次数", justify="right", style="dim")
        table.add_column("平均智力分", justify="right")
        table.add_column("最低", justify="right", style="dim")
        table.add_column("最高", justify="right", style="dim")
        table.add_column("趋势")
        table.add_column("异常次数", justify="right", style="magenta")

        for model, items in sorted(by_model.items()):
            scores = [
                i.get("intelligence_score")
                for i in items
                if i.get("intelligence_score") is not None
            ]
            if not scores:
                continue
            avg = sum(scores) / len(scores)
            anomaly_count = sum(1 for i in items if i.get("is_anomaly"))
            avg_color = "green" if avg >= 85 else "yellow" if avg >= 70 else "red"
            table.add_row(
                model,
                str(len(items)),
                f"[{avg_color}]{avg:.1f}[/{avg_color}]",
                f"{min(scores):.0f}",
                f"{max(scores):.0f}",
                _trend(scores),
                str(anomaly_count),
            )

        console.print(table)
        console.print()

        # 三、降级提示
        console.print("[bold]三、降级/异常提示[/bold]")
        flagged = False
        for model, items in sorted(by_model.items()):
            scores = [
                i.get("intelligence_score")
                for i in items
                if i.get("intelligence_score") is not None
            ]
            trend = _trend(scores)
            if "下降" in trend:
                console.print(
                    f"  [yellow]⚠ {model} 智力分{trend}，建议关注是否被降智或偷换[/yellow]"
                )
                flagged = True
        if not flagged:
            console.print("  [green]✓ 未发现明显的持续降级[/green]")
        console.print()

    # 四、Cursor Auto Usage
    console.print("[bold]四、Cursor Auto Usage[/bold]")
    render_cursor_section(
        period,
        db=db,
        refresh=True,
    )
