"""
Cursor Auto Usage 看板

一条命令看清 Auto/Agent 路由的实际模型占比：
- `verkeep-verify cursor` / `cursor board`  展示看板
- `cursor board --watch`              定时增量导入并刷新
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from verkeep_verify.monitor.cursor_usage import (
    PeriodUsageReport,
    TaskUsageReport,
    aggregate_period,
    aggregate_task,
    format_model_share_line,
    format_output_share_line,
    parse_since,
)
from verkeep_verify.storage.database import Database

console = Console()

MODEL_STYLES: Dict[str, str] = {
    "claude-fable-5": "magenta",
    "claude-sonnet-4": "bright_magenta",
    "grok-4.5": "cyan",
    "gpt-4": "green",
    "gpt-4o": "bright_green",
    "composer-2": "blue",
    "unknown": "dim",
    "default": "dim",
    "auto-opaque": "yellow",
    "pending-infer": "yellow",
}


def _model_style(model: str) -> str:
    return MODEL_STYLES.get(model, "white")


def _bar_text(pct: float, model: str, width: int = 24) -> Text:
    filled = int(round(pct / 100 * width))
    text = Text()
    text.append("█" * filled, style=_model_style(model))
    text.append("░" * (width - filled), style="dim")
    return text


def _stacked_bar(shares: Dict[str, Dict[str, Any]], width: int = 40) -> Text:
    """多模型堆叠条，一眼看清占比结构。"""
    text = Text()
    if not shares:
        text.append("░" * width, style="dim")
        return text

    used = 0
    items = list(shares.items())
    for i, (model, info) in enumerate(items):
        pct = info["pct"]
        if i == len(items) - 1:
            n = width - used
        else:
            n = max(1, int(round(pct / 100 * width))) if pct > 0 else 0
            used += n
        if n > 0:
            text.append("█" * n, style=_model_style(model))
    if used < width:
        text.append("░" * (width - used), style="dim")
    return text


def _share_rows(
    shares: Dict[str, Dict[str, Any]],
    unit_label: str,
    pct_fmt: str = ".0f",
) -> list[Text]:
    rows: list[Text] = []
    for model, info in shares.items():
        line = Text()
        label = model if model not in ("unknown", "auto-opaque", "pending-infer") else model
        line.append(f"  {label:<20} ")
        line.append_text(_bar_text(info["pct"], model))
        line.append(
            f"  {info['pct']:{pct_fmt}}%  ({info['count']} {unit_label})",
            style="dim",
        )
        rows.append(line)
    return rows


def _task_focus_panel(report: TaskUsageReport, db: Optional[Database] = None) -> Panel:
    short_id = report.task_id[:8]
    title = (report.title or "(无标题)")[:48]
    header = Text()
    header.append(f"{short_id}  ", style="bold cyan")
    header.append(title, style="bold")
    header.append(
        f"\n{report.mode} · {report.route_kind} · "
        f"{report.request_count} req · {report.code_unit_count} units · "
        f"可解析率 {report.resolution_rate * 100:.0f}%",
        style="dim",
    )

    body = Text()
    if report.output_shares:
        body.append("\n产出  ", style="bold")
        body.append_text(_stacked_bar(report.output_shares, width=32))
        body.append(
            "  " + format_output_share_line({m: v["pct"] for m, v in report.output_shares.items()}),
            style="dim",
        )
    if report.request_shares:
        body.append("\n请求  ", style="bold")
        body.append_text(_stacked_bar(report.request_shares, width=32))
        body.append(
            "  " + format_model_share_line({m: v["pct"] for m, v in report.request_shares.items()}),
            style="dim",
        )

    # 盲测推断提示：pending-infer 产出 >50% 且有存储推断时添加
    opaque_pct = report.output_shares.get("pending-infer", {}).get("pct", 0) or report.output_shares.get(
        "auto-opaque", {}
    ).get("pct", 0)
    if (opaque_pct > 50 or report.pending_infer_count > 0) and db is not None:
        try:
            from verkeep_verify.monitor.blindtest_view import get_inferred_view

            view = get_inferred_view(db, report.task_id)
            if view and view.inferred_shares:
                top_model = max(view.inferred_shares.items(), key=lambda x: x[1]["pct"])
                top_name = top_model[0]
                top_pct = top_model[1]["pct"]
                body.append(
                    f"\n盲测推断: {top_name} ~{top_pct:.0f}%"
                    f" (独立视图, cursor task {short_id} --inferred)",
                    style="dim",
                )
        except Exception:
            pass

    return Panel(
        Text.assemble(header, body),
        title="重点任务（产出最多）",
        border_style="cyan",
    )


def _summary_panel(period: PeriodUsageReport) -> Panel:
    summary = Text()
    summary.append(f"{period.task_count} 任务", style="bold")
    summary.append(f"  ·  {period.total_requests} 请求", style="dim")
    summary.append(f"  ·  {period.total_output_units} code units", style="dim")
    if period.auto_task_count or period.mixed_task_count:
        summary.append(
            f"\nAuto/Mixed 路由: {period.auto_task_count + period.mixed_task_count} 任务",
            style="yellow",
        )
    if period.total_requests:
        summary.append(
            f"\nAuto 可解析率: {period.resolution_rate * 100:.0f}% "
            f"({period.resolved_requests}/{period.total_requests} requests)",
            style="yellow" if period.resolution_rate < 0.5 else "green",
        )
    return Panel(summary, title=f"Cursor Auto Usage — 最近 {period.since_label}", border_style="blue")


def _shares_panel(
    title: str,
    shares: Dict[str, Dict[str, Any]],
    unit_label: str,
    pct_fmt: str,
    border_style: str,
) -> Panel:
    if not shares:
        return Panel("[dim]暂无数据[/dim]", title=title, border_style=border_style)

    lines = _share_rows(shares, unit_label, pct_fmt=pct_fmt)
    stacked = Text()
    stacked.append_text(_stacked_bar(shares, width=48))
    stacked.append("\n")
    for line in lines:
        stacked.append_text(line)
        stacked.append("\n")
    return Panel(stacked, title=title, border_style=border_style)


def _tasks_table(period: PeriodUsageReport) -> Table:
    table = Table(title="任务列表", expand=True, show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("标题", max_width=28)
    table.add_column("路由")
    table.add_column("请求", justify="right")
    table.add_column("产出", justify="right")
    table.add_column("产出占比", style="bold")
    table.add_column("请求占比", style="dim")

    for t in period.tasks:
        report = aggregate_task(Database(), t.task_id)
        out_shares = {m: v["pct"] for m, v in (report.output_shares if report else {}).items()}
        req_shares = t.model_request_shares
        table.add_row(
            t.task_id[:8],
            (t.title or "(无标题)")[:28],
            t.route_kind,
            str(t.request_count),
            str(t.code_unit_count),
            format_output_share_line(out_shares) if out_shares else "—",
            format_model_share_line(req_shares),
        )
    return table


def build_view(
    period: PeriodUsageReport,
    focus: Optional[TaskUsageReport] = None,
    updated_at: Optional[str] = None,
    db: Optional[Database] = None,
) -> Group:
    """构建 Rich 看板视图。"""
    focus_report = focus or period.latest_report
    items = [
        _summary_panel(period),
        _shares_panel(
            "产出占比（合计）",
            period.output_shares,
            "units",
            ".1f",
            "magenta",
        ),
        _shares_panel(
            "请求占比（合计）",
            period.request_shares,
            "requests",
            ".0f",
            "cyan",
        ),
    ]
    if focus_report:
        items.append(_task_focus_panel(focus_report, db=db))
    if period.tasks:
        items.append(_tasks_table(period))

    footer = Text()
    hint = "Ctrl+C 退出" if updated_at else "verkeep-verify cursor board --watch  常驻刷新"
    footer.append(hint, style="dim")
    if updated_at:
        footer.append(f"  ·  更新于 {updated_at}", style="dim")
    items.append(Panel(footer, border_style="dim"))

    return Group(*items)


def _load_period(
    since: str = "7d",
    limit: int = 20,
    auto_only: bool = False,
) -> PeriodUsageReport:
    db = Database()
    since_dt = parse_since(since)
    return aggregate_period(db, since=since_dt, limit=limit, auto_only=auto_only)


def ensure_imported(since: str = "7d", full: bool = False) -> None:
    from verkeep_verify.monitor.cursor_usage import CursorUsageImporter

    importer = CursorUsageImporter()
    importer.import_all(since=parse_since(since), full=full)


def show_board(
    since: str = "7d",
    limit: int = 20,
    auto_only: bool = False,
    refresh: bool = True,
) -> None:
    """展示看板（默认先增量导入）。"""
    if refresh:
        with console.status("[bold green]同步 Cursor 数据..."):
            ensure_imported(since=since, full=False)

    db = Database()
    period = _load_period(since=since, limit=limit, auto_only=auto_only)
    if period.task_count == 0:
        console.print("[yellow]暂无任务数据。[/yellow]")
        console.print("[dim]尝试: verkeep-verify cursor import --since 30d[/dim]")
        return

    console.print(build_view(period, db=db))


def watch_board(
    since: str = "7d",
    limit: int = 20,
    auto_only: bool = False,
    interval_seconds: int = 60,
) -> None:
    """常驻看板：定时增量导入并刷新。"""
    console.print(
        f"[dim]Cursor Auto 看板已启动，每 {interval_seconds}s 同步，Ctrl+C 退出[/dim]"
    )

    try:
        with Live(console=console, refresh_per_second=2, screen=False) as live:
            while True:
                with console.status("[bold green]同步 Cursor 数据..."):
                    ensure_imported(since=since, full=False)
                period = _load_period(since=since, limit=limit, auto_only=auto_only)
                ts = datetime.now().strftime("%H:%M:%S")
                live.update(build_view(period, updated_at=ts))

                slept = 0
                while slept < interval_seconds:
                    time.sleep(min(2, interval_seconds - slept))
                    slept += 2
    except KeyboardInterrupt:
        console.print("\n[yellow]看板已退出[/yellow]")
