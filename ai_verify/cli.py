"""
AI Verify CLI - 命令行入口
"""

import click
from typing import Optional

from rich.console import Console
from rich.table import Table

from ai_verify import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="ai-verify")
def main():
    """
    AI Verify - AI API 实时监控工具

    给你的 AI API 装一个监控摄像头，实时检测模型真假、质量变化和异常行为。
    """
    pass


# ============== 配置命令 ==============
@main.group()
def config():
    """配置管理"""
    pass


@config.command("init")
def config_init():
    """初始化配置文件"""
    from ai_verify.config import ConfigManager

    manager = ConfigManager()
    manager.init_config()
    console.print("[green]✓[/green] 配置文件已创建: ~/.ai-verify/config.yaml")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """设置配置项

    示例:
        ai-verify config set base_url https://api.example.com/v1
        ai-verify config set api_key sk-xxx
        ai-verify config set model gpt-4
    """
    from ai_verify.config import ConfigManager

    manager = ConfigManager()
    manager.set(key, value)
    console.print(f"[green]✓[/green] 已设置 {key} = {value[:20]}...")


@config.command("list")
def config_list():
    """查看当前配置"""
    from ai_verify.config import ConfigManager

    manager = ConfigManager()
    cfg = manager.load()

    table = Table(title="当前配置")
    table.add_column("配置项", style="cyan")
    table.add_column("值", style="green")

    for key, value in cfg.items():
        if "key" in key.lower() and value:
            value = value[:8] + "..." + value[-4:]
        table.add_row(key, str(value) if value else "(未设置)")

    console.print(table)


# ============== 代理命令 ==============
@main.group()
def proxy():
    """代理服务器管理"""
    pass


@proxy.command("start")
@click.option("--port", default=8080, help="代理端口")
@click.option("--host", default="127.0.0.1", help="监听地址")
def proxy_start(port: int, host: str):
    """启动代理服务器"""
    from ai_verify.proxy.server import start_proxy_server

    console.print(f"[cyan]启动代理服务器...[/cyan]")
    console.print(f"代理地址: [green]http://{host}:{port}/v1[/green]")
    console.print(
        f"设置环境变量: [yellow]export OPENAI_BASE_URL=http://{host}:{port}/v1[/yellow]"
    )
    console.print("")
    console.print("[dim]按 Ctrl+C 停止[/dim]")

    start_proxy_server(host=host, port=port)


@proxy.command("status")
def proxy_status():
    """查看代理状态"""
    console.print("[yellow]代理服务器未运行[/yellow]")
    console.print("使用 [cyan]ai-verify proxy start[/cyan] 启动")


# ============== 监控命令 ==============
@main.group()
def monitor():
    """定时监控管理"""
    pass


@monitor.command("start")
@click.option("--interval", default="6h", help="检测间隔 (如: 90s, 30m, 6h, 1d)")
@click.option("--probes", default=6, help="每次巡检的指纹探针数量")
@click.option("--questions", default=8, help="每次巡检的质量题目数量")
def monitor_start(interval: str, probes: int, questions: int):
    """启动定时监控 (前台运行，周期性打分并在异常时报警)"""
    from ai_verify.monitor.daemon import run

    run(interval=interval, num_probes=probes, num_questions=questions)


@monitor.command("stop")
def monitor_stop():
    """停止监控"""
    console.print("[dim]定时监控为前台运行，在其终端按 Ctrl+C 即可停止[/dim]")


@monitor.command("status")
def monitor_status():
    """查看监控状态"""
    console.print("[dim]定时监控为前台进程，请查看运行它的终端窗口[/dim]")


# ============== 供应商（CC Switch） ==============
@main.group()
def providers():
    """查看 CC Switch / Claude 当前供应商"""
    pass


@providers.command("list")
def providers_list():
    """列出 CC Switch 里的 Claude 供应商"""
    from ai_verify.providers.cc_switch import (
        get_current_cc_switch_provider,
        list_cc_switch_providers,
    )

    current = get_current_cc_switch_provider()
    current_id = current.provider_id if current else None
    items = list_cc_switch_providers()
    if not items:
        console.print(
            "[yellow]未找到 CC Switch 供应商（~/.cc-switch/cc-switch.db）[/yellow]"
        )
        return

    table = Table(title="CC Switch Claude 供应商")
    table.add_column("", width=2)
    table.add_column("名称", style="cyan")
    table.add_column("Base URL")
    table.add_column("模型", style="dim")
    table.add_column("Key", style="dim")

    for p in items:
        mark = "●" if p.provider_id == current_id else ""
        m = p.masked()
        table.add_row(mark, p.name, p.base_url, p.model or "-", m["api_key"] or "-")

    console.print(table)
    if current:
        console.print(f"[dim]当前选中: {current.name}（来自 {current.source}）[/dim]")


@providers.command("current")
def providers_current():
    """显示当前会用于监控的上游配置"""
    from ai_verify.providers.cc_switch import resolve_provider

    p = resolve_provider(prefer="auto")
    if not p:
        console.print("[yellow]未找到可用上游配置[/yellow]")
        return
    m = p.masked()
    table = Table(title="当前上游")
    table.add_column("项", style="cyan")
    table.add_column("值")
    for k in ("name", "source", "base_url", "model", "api_key"):
        table.add_row(k, str(m.get(k) or "-"))
    console.print(table)


# ============== 一键包装运行 ==============
@main.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option("--port", default=8080, help="本地代理端口")
@click.option("--host", default="127.0.0.1", help="监听地址")
@click.option("--quiet", is_flag=True, help="少打启动提示")
@click.option(
    "--from",
    "prefer",
    default="auto",
    type=click.Choice(["auto", "cc-switch", "claude", "ai-verify"]),
    help="上游配置来源（默认自动读 CC Switch）",
)
@click.pass_context
def run(ctx, port: int, host: str, quiet: bool, prefer: str):
    """一键监控：自动读 CC Switch 当前供应商，后台起代理并运行命令

    \b
    示例:
      ai-verify run -- claude
      ai-verify run --port 9090 -- claude
      ai-verify run --from ai-verify -- python my_script.py
    """
    import sys

    from ai_verify.runner import run_with_proxy

    command = list(ctx.args)
    if not command:
        console.print("[red]✗ 请在 -- 后面写命令[/red]")
        console.print("  示例: [cyan]ai-verify run -- claude[/cyan]")
        sys.exit(2)

    code = run_with_proxy(
        command=command, host=host, port=port, quiet=quiet, prefer=prefer
    )
    sys.exit(code)


# ============== 验证命令 ==============
@main.command()
@click.option("--full", is_flag=True, help="完整验证(指纹+质量+安全)")
@click.option("--model", default=None, help="指定验证模型")
@click.option("--probes", default=10, help="指纹探针数量")
@click.option("--questions", default=10, help="质量测试问题数量")
@click.option(
    "--from",
    "prefer",
    default="auto",
    type=click.Choice(["auto", "cc-switch", "claude", "ai-verify"]),
    help="上游配置来源（默认自动读 CC Switch）",
)
def check(full: bool, model, probes: int, questions: int, prefer: str):
    """验证 API 渠道（默认读取 CC Switch 当前供应商）"""
    from ai_verify.monitor.engine import VerifyEngine, display_verify_result
    from ai_verify.providers.cc_switch import resolve_provider

    provider = resolve_provider(prefer=prefer)
    if not provider:
        console.print("[red]✗ 未找到上游配置[/red]")
        console.print(
            "  请在 CC Switch 选一个供应商，或: ai-verify config set base_url <url>"
        )
        return

    use_model = model or provider.model or "gpt-4"
    console.print(
        f"[dim]来源: {provider.source} | 供应商: {provider.name} | {provider.base_url}[/dim]"
    )

    engine = VerifyEngine(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=use_model,
    )

    # 进度显示
    def progress_callback(current, total, stage=""):
        pct = current / total * 100
        console.print(f"[dim]  {stage}: {current}/{total} ({pct:.0f}%)[/dim]", end="\r")

    console.print("[cyan]开始验证...[/cyan]")
    console.print(f"[dim]  模型: {use_model}[/dim]")
    console.print(f"[dim]  指纹探针: {probes} 个[/dim]")
    if full:
        console.print(f"[dim]  质量测试: {questions} 题[/dim]")
    console.print()

    with console.status("[bold green]正在验证..."):
        result = engine.verify(
            full=full,
            num_probes=probes,
            num_quality_questions=questions,
        )

    # 显示结果
    display_verify_result(result)


# ============== 智力打分看板 ==============
@main.command()
@click.option("--once", "once", is_flag=True, help="只打一次分并展示")
@click.option("--watch", "watch_mode", is_flag=True, help="常驻看板，定时刷新")
@click.option("--board", is_flag=True, help="只看历史看板，不触发新的打分")
@click.option("--interval", default="5m", help="watch 模式刷新间隔 (如: 5m, 30m, 1h)")
@click.option("--probes", default=6, help="指纹探针数量")
@click.option("--questions", default=8, help="质量题目数量")
def score(
    once: bool,
    watch_mode: bool,
    board: bool,
    interval: str,
    probes: int,
    questions: int,
):
    """给当前渠道的模型打智力分 (命令行边上的智力打分看板)"""
    from ai_verify import dashboard
    from ai_verify.monitor.daemon import parse_interval

    if board:
        dashboard.show_board_only()
        return

    if watch_mode:
        dashboard.watch(
            interval_seconds=parse_interval(interval),
            num_probes=probes,
            num_questions=questions,
        )
        return

    # 默认行为等同 --once
    dashboard.score_once(num_probes=probes, num_questions=questions)


# ============== 历史命令 ==============
@main.command()
@click.option("--last", default="7d", help="时间范围 (如: 7d, 30d)")
@click.option("--model", default=None, help="筛选模型")
def history(last: str, model):
    """查看历史监控记录"""
    from ai_verify.storage.database import Database

    db = Database()
    records = db.get_call_history(hours=_parse_duration(last), model=model)

    if not records:
        console.print("[yellow]暂无历史记录[/yellow]")
        return

    table = Table(title=f"历史记录 (最近 {last})")
    table.add_column("时间", style="dim")
    table.add_column("模型", style="cyan")
    table.add_column("状态")
    table.add_column("延迟", style="yellow")
    table.add_column("异常", style="magenta")

    for r in records[:50]:  # 最多显示50条
        is_ok = not r.get("is_anomaly")
        status = "✓" if is_ok else "⚠"
        status_color = "green" if is_ok else "yellow"
        quality = r.get("quality_score")
        quality_str = f"{quality}" if quality is not None else "-"
        anomaly = r.get("anomaly_type") or ("-" if is_ok else "?")
        table.add_row(
            r.get("timestamp", "")[:19],
            r.get("model", ""),
            f"[{status_color}]{status}[/{status_color}]",
            f"{r.get('latency_ms', 0)}ms",
            str(anomaly),
        )

    console.print(table)


# ============== 报警命令 ==============
@main.group()
def alert():
    """报警管理"""
    pass


@alert.command("test")
@click.option("--webhook", default=None, help="测试指定的 webhook URL")
def alert_test(webhook):
    """测试报警功能"""
    from ai_verify.alerts import AlertManager, AlertLevel

    manager = AlertManager()

    # 如果指定了 webhook，添加
    if webhook:
        manager.add_webhook(webhook)
        console.print(f"[cyan]测试 Webhook: {webhook[:50]}...[/cyan]")
    else:
        # 使用配置中的 webhook
        from ai_verify.config import ConfigManager

        cfg = ConfigManager().load()
        webhook_url = cfg.get("alerts.webhook")
        if webhook_url:
            manager.add_webhook(webhook_url)
            console.print(f"[cyan]使用配置的 Webhook[/cyan]")
        else:
            console.print("[yellow]未配置 Webhook，仅输出到控制台[/yellow]")

    # 发送测试报警
    manager.alert(
        title="AI Verify 测试报警",
        message="这是一条测试报警消息，验证报警功能是否正常工作。",
        level=AlertLevel.WARNING,
        details={
            "测试时间": "现在",
            "来源": "ai-verify test",
        },
    )

    console.print("[green]✓ 测试报警已发送[/green]")


@alert.command("set")
@click.argument("webhook_url")
@click.option(
    "--platform", default="auto", help="平台类型: auto, lark, dingtalk, wechat, slack"
)
def alert_set(webhook_url: str, platform: str):
    """配置报警 Webhook"""
    from ai_verify.config import ConfigManager

    manager = ConfigManager()
    manager.set("alerts.webhook", webhook_url)
    manager.set("alerts.webhook_platform", platform)

    console.print(f"[green]✓[/green] Webhook 已配置")
    console.print(f"  URL: {webhook_url[:50]}...")
    console.print(f"  平台: {platform}")
    console.print()
    console.print("[dim]测试报警: ai-verify alert test[/dim]")


# ============== 报告命令 ==============
@main.command()
@click.option(
    "--period", type=click.Choice(["daily", "weekly", "monthly"]), default="weekly"
)
def report(period: str):
    """生成监控报告"""
    from ai_verify import report as report_mod

    report_mod.generate(period=period)


# ============== Cursor Auto Usage ==============
@main.group(invoke_without_command=True)
@click.option("--since", default="7d", help="时间范围 (如 7d, 30d)")
@click.pass_context
def cursor(ctx, since: str):
    """Cursor Auto Usage — 透视 Cursor Agent 模型路由（只读本地遥测）"""
    if ctx.invoked_subcommand is None:
        from ai_verify.dashboard_cursor import show_board

        show_board(since=since)


@cursor.command("report")
@click.option(
    "--period",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="weekly",
    help="报告周期",
)
@click.option("--no-refresh", is_flag=True, help="不自动导入，仅用已有数据")
def cursor_report(period: str, no_refresh: bool):
    """生成 Cursor Auto Usage 专项报告（日报/周报/月报）"""
    from ai_verify.report import generate_cursor

    generate_cursor(period=period, refresh=not no_refresh)


@cursor.command("board")
@click.option("--since", default="7d", help="时间范围")
@click.option("--limit", default=20, help="任务列表条数")
@click.option("--auto-only", is_flag=True, help="仅统计 auto/mixed 路由任务")
@click.option("--watch", is_flag=True, help="常驻刷新看板")
@click.option("--interval", default=60, help="刷新间隔（秒）")
@click.option("--no-refresh", is_flag=True, help="不自动导入，仅展示已有数据")
def cursor_board(
    since: str,
    limit: int,
    auto_only: bool,
    watch: bool,
    interval: int,
    no_refresh: bool,
):
    """Rich 看板：一眼看清 Auto 路由的模型产出/请求占比"""
    from ai_verify.dashboard_cursor import show_board, watch_board

    if watch:
        watch_board(
            since=since,
            limit=limit,
            auto_only=auto_only,
            interval_seconds=interval,
        )
    else:
        show_board(
            since=since,
            limit=limit,
            auto_only=auto_only,
            refresh=not no_refresh,
        )


@cursor.command("doctor")
def cursor_doctor():
    """诊断 Cursor 本地数据源是否可采集"""
    from ai_verify.providers.cursor import run_doctor

    report = run_doctor()
    console.print("[bold]Cursor Auto Usage — 环境诊断[/bold]\n")

    for check in report.checks:
        mark = "[green]✓[/green]" if check.ok else "[red]✗[/red]"
        console.print(f"{mark} {check.name:<18} {check.detail}")

    console.print("\n[bold]可采集字段:[/bold]")
    for label, via, _source in report.collectable_fields:
        console.print(f"  {label:<24} {via}")

    if report.suggestion:
        console.print(f"\n[dim]建议: {report.suggestion}[/dim]")


@cursor.command("import")
@click.option("--since", default="7d", help="导入时间范围 (如 7d, 30d)")
@click.option("--full", is_flag=True, help="忽略增量偏移，从头扫描日志")
def cursor_import(since: str, full: bool):
    """从 Cursor 本地日志导入模型用量数据"""
    from ai_verify.monitor.cursor_usage import CursorUsageImporter, parse_since

    since_dt = parse_since(since)
    importer = CursorUsageImporter()
    with console.status("[bold green]正在导入 Cursor 数据..."):
        result = importer.import_all(since=since_dt, full=full)

    console.print("[green]✓[/green] 导入完成")
    console.print(f"  任务: {result.tasks_upserted}")
    console.print(f"  事件: {result.events_upserted}")
    console.print(f"  日志文件: {result.log_files_processed}")
    console.print(f"  tracking 行: {result.tracking_rows}")
    console.print(
        f"  hook 事件: {result.hook_events_seen} (resolved {result.hook_events_resolved})"
    )
    console.print(f"\n[dim]查看: ai-verify cursor --since {since}[/dim]")


@cursor.command("tasks")
@click.option("--since", default="7d", help="时间范围")
@click.option("--limit", default=20, help="最多显示条数")
@click.option("--auto-only", is_flag=True, help="仅显示 auto/mixed 路由任务")
def cursor_tasks(since: str, limit: int, auto_only: bool):
    """列出最近 Cursor 任务及模型占比"""
    from ai_verify.monitor.cursor_usage import (
        format_model_share_line,
        format_output_share_line,
        list_tasks,
        parse_since,
    )
    from ai_verify.storage.database import Database

    db = Database()
    since_dt = parse_since(since)
    items = list_tasks(db, since=since_dt, limit=limit, auto_only=auto_only)

    console.print(f"[bold]Cursor Auto Usage — 最近 {since}[/bold]\n")
    if not items:
        console.print("[yellow]暂无任务，请先运行: ai-verify cursor import[/yellow]")
        return

    table = Table()
    table.add_column("任务ID", style="cyan", no_wrap=True)
    table.add_column("标题", max_width=32)
    table.add_column("模式")
    table.add_column("路由")
    table.add_column("请求", justify="right")
    table.add_column("产出", justify="right")
    table.add_column("产出占比", style="bold")
    table.add_column("请求占比", style="dim")

    for t in items:
        short_id = t.task_id[:8]
        title = (t.title or "(无标题)")[:32]
        from ai_verify.monitor.cursor_usage import aggregate_task

        report = aggregate_task(db, t.task_id)
        out_shares = (
            {m: v["pct"] for m, v in report.output_shares.items()} if report else {}
        )
        req_share = format_model_share_line(t.model_request_shares)
        out_share = format_output_share_line(out_shares) if out_shares else "—"
        table.add_row(
            short_id,
            title,
            t.mode,
            t.route_kind,
            str(t.request_count),
            str(t.code_unit_count),
            out_share,
            req_share,
        )
    console.print(table)


@cursor.command("task")
@click.argument("task_id", required=False)
@click.option("--latest", is_flag=True, help="显示最近一个任务")
@click.option("--search", default=None, help="按标题搜索任务")
@click.option("--score", is_flag=True, help="关联智力打分（score_snapshots）")
@click.option(
    "--inferred",
    is_flag=True,
    help="显示逐 turn 盲测细节（默认已对 Auto/Mixed 自动融合推断轨）",
)
def cursor_task(
    task_id: Optional[str], latest: bool, search: Optional[str], score: bool, inferred: bool
):
    """查看单个 Cursor 任务的模型用量详情"""
    from ai_verify.monitor.cursor_usage import (
        _bar,
        aggregate_task,
        render_task_score_table,
    )
    from ai_verify.storage.database import Database

    db = Database()

    if search:
        matches = db.search_cursor_tasks(search, limit=5)
        if not matches:
            console.print(f"[yellow]未找到匹配任务: {search}[/yellow]")
            return
        if len(matches) > 1:
            console.print("[yellow]多个匹配，使用第一个:[/yellow]")
        task_id = matches[0]["task_id"]
    elif latest or not task_id:
        latest_task = db.get_latest_cursor_task()
        if not latest_task:
            console.print("[yellow]暂无任务[/yellow]")
            return
        task_id = latest_task["task_id"]

    report = aggregate_task(db, task_id)
    if not report:
        console.print(f"[red]✗ 未找到任务: {task_id}[/red]")
        return

    console.print(f"[bold]Task {report.task_id}[/bold]")
    console.print(f"标题:   {report.title or '(无标题)'}")
    console.print(f"模式:   {report.mode} | 路由: {report.route_kind}")
    if report.started_at:
        ended = report.ended_at or "?"
        console.print(f"时间:   {report.started_at[:16]} ~ {ended[:16]}")
    console.print(
        f"请求:   {report.request_count} turns | "
        f"产出: {report.code_unit_count} code units | "
        f"Subagent: {report.subagent_count}"
    )
    console.print(
        f"可解析率: {report.resolution_rate * 100:.0f}% "
        f"({report.resolved_requests}/{report.request_count} requests) | "
        f"覆盖率: {report.coverage * 100:.0f}% "
        f"(fact∪inferred；pending-infer={report.pending_infer_count})"
    )
    console.print(
        "[dim]推断轨 ≠ 云端路由真值；仅 factual 为遥测事实。[/dim]"
    )

    console.print("\n[bold]── 请求占比（合并展示）────────────────[/bold]")
    for model, info in report.request_shares.items():
        console.print(
            f"  {model:<18} {_bar(info['pct'])}  {info['pct']:.0f}%  ({info['count']} requests)"
        )

    if report.factual_request_shares:
        console.print("\n[bold]── 事实轨（telemetry）────────────────[/bold]")
        for model, info in report.factual_request_shares.items():
            console.print(
                f"  {model:<18} {_bar(info['pct'])}  {info['pct']:.0f}%  ({info['count']} requests)"
            )

    if report.inferred_request_shares:
        console.print("\n[bold]── 推断轨（blindtest，非事实）────────[/bold]")
        for model, info in report.inferred_request_shares.items():
            console.print(
                f"  {model:<18} {_bar(info['pct'])}  {info['pct']:.0f}%  ({info['count']} requests)"
            )
    elif report.pending_infer_count > 0:
        console.print(
            "\n[yellow]有 pending-infer turns：已尝试自动推断；"
            "低于阈值或无 transcript 时仍会保留 pending-infer。"
            "逐 turn 细节: ai-verify cursor task --inferred[/yellow]"
        )

    if report.output_shares:
        console.print("\n[bold]── 产出占比 ──────────────────────────[/bold]")
        for model, info in report.output_shares.items():
            console.print(
                f"  {model:<18} {_bar(info['pct'])}  {info['pct']:.1f}%  ({info['count']} units)"
            )

    if score and (report.output_shares or report.request_shares):
        console.print()
        console.print(render_task_score_table(report, db))
        from ai_verify.monitor.cursor_usage import get_model_scores

        models = [
            m
            for m in set(report.output_shares) | set(report.request_shares)
            if m not in ("unknown", "auto-opaque", "pending-infer")
        ]
        scores = get_model_scores(db, models)
        if any(not scores.get(m) for m in models):
            console.print(
                "[dim]部分模型无智力分记录，可对当前渠道运行 ai-verify score 补测[/dim]"
            )

    if report.status_counts:
        console.print("\n[bold]── 状态分布 ──────────────────────────[/bold]")
        parts = [f"{k}: {v}" for k, v in sorted(report.status_counts.items())]
        console.print("  " + " | ".join(parts))

    if report.confidence_counts:
        console.print("\n[bold]── 证据质量 ──────────────────────────[/bold]")
        for conf, count in sorted(report.confidence_counts.items(), reverse=True):
            console.print(f"  {conf}: {count}/{report.request_count} requests")

    if report.subagents:
        console.print("\n[bold]── Subagent ─────────────────────────[/bold]")
        for sub in report.subagents:
            sid = str(sub.get("task_id", ""))[:8]
            reqs = sub.get("request_count", 0)
            units = sub.get("code_units", 0) or 0
            model_hint = "unknown" if units == 0 else "see parent"
            console.print(f"  {sid} → {reqs} request(s), model {model_hint}")

    if report.per_request:
        console.print("\n[bold]── Per-request 明细 ──────────────────[/bold]")
        console.print(
            f"  {'request_id':<22} {'selected':<12} {'resolved':<16} {'inferred':<12} {'status':<10} units tok"
        )
        for row in report.per_request:
            rid = (row.get("request_id") or "")[:20]
            sel = (row.get("selected_model") or "-")[:12]
            res = (row.get("resolved_model") or "unknown")[:16]
            inf = (row.get("inferred_model") or "-")[:12]
            status = (row.get("status") or "-")[:10]
            tok = ""
            if row.get("input_tokens") is not None or row.get("output_tokens") is not None:
                tok = f"{row.get('input_tokens') or 0}→{row.get('output_tokens') or 0}"
            console.print(
                f"  {rid:<22} {sel:<12} {res:<16} {inf:<12} {status:<10} "
                f"{row.get('units', 0)} {tok}"
            )

    if inferred:
        _render_inferred_view(db, report.task_id, console)


def _render_inferred_view(db, task_id: str, console) -> None:
    """渲染盲测推断逐 turn 细节（合并占比由 aggregate_task 融合）。"""
    from ai_verify.monitor.blindtest_infer import ensure_task_inferences
    from ai_verify.monitor.blindtest_view import get_inferred_view

    ensure_task_inferences(db, task_id)
    view = get_inferred_view(db, task_id)

    if view is None:
        from ai_verify.monitor.blindtest_infer import DEFAULT_MODEL_PATH

        console.print(
            "\n[yellow]── 盲测推断（逐 turn 细节）──[/yellow]"
        )
        if not DEFAULT_MODEL_PATH.is_file():
            console.print(
                "[dim]无推断记录，且未找到训练模型。"
                "先运行 ai-verify blindtest train[/dim]"
            )
        else:
            console.print("[dim]无推断结果（无 transcript 或全部低于阈值）[/dim]")
        return

    console.print("\n[bold yellow]── 盲测推断（逐 turn 细节）──[/bold yellow]")
    mv_line = f"模型版本: {view.model_version}"
    if view.trained_at:
        mv_line += f"  |  推断时间: {view.trained_at[:16]}"
    console.print(f"[dim]{mv_line}[/dim]")

    # Per-turn 表格
    # NOTE: remainder of function unchanged below — replaced only the preamble.
    console.print(
        f"\n  {'turn':<6} {'推断模型':<22} {'概率':>6}  {'top-2 候选'}"
    )
    console.print("  " + "─" * 64)
    for pt in view.per_turn:
        model_label = pt.inferred_model or "[dim]—[/dim]"
        prob_str = f"{pt.probability:.0%}"
        console.print(f"  {pt.turn_index:<6} {model_label:<22} {prob_str:>6}")

    # 汇总
    console.print()
    if view.inferred_shares:
        console.print("[bold]  推断占比（仅含给出结论的 turns）:[/bold]")
        total_decided = sum(v["count"] for v in view.inferred_shares.values())
        for model, info in view.inferred_shares.items():
            bar = "█" * int(round(info["pct"] / 100 * 20)) + "░" * (20 - int(round(info["pct"] / 100 * 20)))
            console.print(
                f"    {model:<22} {bar}  {info['pct']:.0f}%  ({info['count']}/{total_decided} turns)"
            )

    if view.abstained > 0:
        console.print(
            f"  [dim]低置信 {view.abstained} turns 不给结论（概率 < 阈值）[/dim]"
        )


@cursor.group("hooks")
def cursor_hooks_group():
    """Cursor Hooks 探针 — 安装/分析/卸载"""
    pass


@cursor_hooks_group.command("install")
def cursor_hooks_install():
    """安装 Cursor Hooks 探针（merge 到 ~/.cursor/hooks.json）"""
    from ai_verify.cursor_hooks import install_hooks

    result = install_hooks()
    console.print("[green]✓[/green] Hook 脚本已写入:")
    console.print(f"  {result.script_path}")
    console.print(f"[green]✓[/green] hooks.json 已更新: {result.hooks_json_path}")
    if result.backup_path:
        console.print(f"  备份: {result.backup_path}")
    if result.events_added:
        console.print(f"  新增事件: {', '.join(result.events_added)}")
    if result.events_existing:
        console.print(f"  已存在: {', '.join(result.events_existing)}")
    console.print(
        "\n[bold yellow]请完全重启 Cursor[/bold yellow]，然后跑 1 次 Auto Agent turn。"
    )
    console.print("之后运行: [cyan]ai-verify cursor hooks analyze[/cyan]")


@cursor_hooks_group.command("analyze")
def cursor_hooks_analyze():
    """分析 hook 探针 ndjson，检查是否含 resolved model"""
    from ai_verify.cursor_hooks import (
        analyze_probe_ndjson,
        format_analyze_result,
        probe_ndjson_path,
    )

    path = probe_ndjson_path()
    if not path.is_file():
        console.print(f"[yellow]未找到探针日志: {path}[/yellow]")
        console.print(
            "请先运行: ai-verify cursor hooks install，重启 Cursor 并执行一次 Agent turn"
        )
        return
    result = analyze_probe_ndjson(path)
    console.print("[bold]Cursor Hooks 探针分析[/bold]\n")
    console.print(format_analyze_result(result))
    if result.provides_resolved_model:
        console.print("\n[green]发现真实 model slug，可接入 import/merge。[/green]")
    else:
        console.print(
            "\n[yellow]未发现非 default 的 model 值；Auto 模式下 Hook 可能无法解析底层模型。[/yellow]"
        )


@cursor_hooks_group.command("uninstall")
def cursor_hooks_uninstall():
    """从 hooks.json 移除 ai-verify 探针条目"""
    from ai_verify.cursor_hooks import uninstall_hooks

    hooks_path, backup, removed = uninstall_hooks()
    if not removed:
        console.print("[yellow]未找到 ai-verify hook 条目[/yellow]")
        return
    console.print(f"[green]✓[/green] 已移除事件: {', '.join(removed)}")
    console.print(f"  更新: {hooks_path}")
    if backup:
        console.print(f"  备份: {backup}")
    console.print(
        "[dim]探针脚本 ~/.ai-verify/hooks/cursor-track.sh 仍保留，可手动删除[/dim]"
    )


@cursor.command("probe")
@click.option("--task-id", default=None, help="限定任务 ID（前缀匹配）")
@click.option("--limit", default=200, help="最多显示 model hit 条数")
def cursor_probe(task_id: Optional[str], limit: int):
    """取证扫描：本地日志中哪些字段含 model 信息"""
    from ai_verify.cursor_probe import format_probe_report, run_probe

    report = run_probe(task_id=task_id, limit=limit)
    console.print("[bold]Cursor Probe — 模型字段取证[/bold]\n")
    console.print(format_probe_report(report))


@cursor.command("recommend")
@click.option("--since", default="7d", help="统计时间范围")
def cursor_recommend(since: str):
    """Auto 解析率低时的操作建议（装 Hooks / 关 Auto）"""
    from ai_verify.cursor_recommend import show_recommendations

    show_recommendations(since=since)


def _parse_duration(duration: str) -> int:
    """解析时间范围为小时数"""
    unit = duration[-1]
    value = int(duration[:-1])

    if unit == "h":
        return value
    elif unit == "d":
        return value * 24
    elif unit == "w":
        return value * 24 * 7
    else:
        return 24


# ============== 盲测指纹命令 ==============
@main.group()
def blindtest():
    """盲测模型指纹识别（Auto 模式模型推断）"""
    pass


def _blindtest_dir():
    from ai_verify.blindtest.corpus import DEFAULT_BLINDTEST_DIR

    return DEFAULT_BLINDTEST_DIR


def _blindtest_model_path():
    return _blindtest_dir() / "model.json"


@blindtest.command("build-corpus")
@click.option("--since", default=None, help="只扫描该时间范围内的 transcripts，如 30d / 12h")
@click.option("--include-unlabeled", is_flag=True, help="同时保留无标签样本")
def blindtest_build_corpus(since: Optional[str], include_unlabeled: bool):
    """扫描 agent transcripts 构建带标签语料"""
    from datetime import datetime, timedelta

    from ai_verify.blindtest.corpus import build_corpus, save_corpus

    since_dt = None
    if since:
        since_dt = datetime.now() - timedelta(hours=_parse_duration(since))

    console.print("[cyan]扫描 agent transcripts 并关联模型标签…[/cyan]")
    corpus = build_corpus(since=since_dt, include_unlabeled=include_unlabeled)
    path = save_corpus(corpus)

    stats = corpus.stats
    console.print(f"[green]✓[/green] 语料已保存: {path}")
    console.print(
        f"  会话 {stats.get('conversations_scanned', 0)} 个, "
        f"turn {stats.get('turns_scanned', 0)} 个, "
        f"样本 {stats.get('samples', 0)} 条 (有标签 {stats.get('labeled', 0)})"
    )
    class_counts = stats.get("class_counts", {})
    if class_counts:
        table = Table(title="每类样本数")
        table.add_column("模型", style="cyan")
        table.add_column("样本数", style="green", justify="right")
        for model, count in sorted(class_counts.items(), key=lambda x: -x[1]):
            table.add_row(model, str(count))
        console.print(table)
        sources = stats.get("label_sources", {})
        if sources:
            console.print(
                "  标签来源: " + " | ".join(f"{k}: {v}" for k, v in sorted(sources.items()))
            )
    else:
        console.print(
            "[yellow]无带标签样本。请先在 Cursor 手选模型跑几个任务，再重新构建语料。[/yellow]"
        )


@blindtest.command("train")
@click.option("--threshold", default=0.7, show_default=True, help="推断概率阈值")
def blindtest_train(threshold: float):
    """训练盲测分类器并输出 TrainReport"""
    from ai_verify.blindtest.classifier import BlindModelClassifier
    from ai_verify.blindtest.corpus import load_corpus

    try:
        corpus = load_corpus()
    except FileNotFoundError:
        console.print("[red]✗ 未找到语料，请先运行 ai-verify blindtest build-corpus[/red]")
        raise SystemExit(1)

    clf = BlindModelClassifier(threshold=threshold)
    try:
        report = clf.train(corpus)
    except ValueError as exc:
        console.print(f"[red]✗ 训练失败: {exc}[/red]")
        raise SystemExit(1)

    clf.save(_blindtest_model_path())
    console.print(f"[green]✓[/green] 模型已保存: {_blindtest_model_path()}")

    table = Table(title="TrainReport")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="green")
    table.add_row("backend", report.backend)
    table.add_row("样本数", str(report.n_samples))
    table.add_row("会话数", str(report.n_conversations))
    cv = f"{report.cv_accuracy:.1%}" if report.cv_accuracy is not None else "N/A"
    table.add_row("CV 准确率 (留一会话)", f"{cv} ({report.cv_evaluated} 条留出)")
    table.add_row("校准温度", f"{report.temperature:.2f}")
    table.add_row("特征维度", str(report.feature_count))
    console.print(table)

    table2 = Table(title="每类明细")
    table2.add_column("模型", style="cyan")
    table2.add_column("样本数", justify="right")
    table2.add_column("CV 准确率", justify="right")
    for model, count in sorted(report.class_counts.items(), key=lambda x: -x[1]):
        acc = report.per_class_accuracy.get(model)
        table2.add_row(model, str(count), f"{acc:.0%}" if acc is not None else "-")
    console.print(table2)
    for note in report.notes:
        console.print(f"[yellow]note: {note}[/yellow]")


@blindtest.command("infer")
@click.argument("task_id")
@click.option("--save/--no-save", "save_db", default=True, help="是否写入 blindtest_inferences 表")
def blindtest_infer(task_id: str, save_db: bool):
    """对指定任务逐 turn 推断底层模型"""
    from ai_verify.blindtest.classifier import BlindModelClassifier
    from ai_verify.blindtest.corpus import load_turns_for_task
    from ai_verify.blindtest.features import extract_features

    model_path = _blindtest_model_path()
    if not model_path.is_file():
        console.print("[red]✗ 未找到模型，请先运行 ai-verify blindtest train[/red]")
        raise SystemExit(1)
    clf = BlindModelClassifier.load(model_path)

    turns = load_turns_for_task(task_id)
    if not turns:
        console.print(f"[red]✗ 未找到任务 {task_id} 的 transcript[/red]")
        raise SystemExit(1)

    full_task_id = turns[0].conversation_id
    console.print(
        f"任务 [cyan]{full_task_id[:8]}[/cyan] 共 {len(turns)} 个 turn, "
        f"阈值 {clf.threshold}, 候选类别: {', '.join(clf.classes)}"
    )

    db = None
    if save_db:
        from ai_verify.storage.database import Database

        db = Database()

    table = Table(title="Per-turn 盲测推断")
    table.add_column("turn", justify="right")
    table.add_column("推断模型", style="cyan")
    table.add_column("概率", justify="right")
    table.add_column("top 候选", style="dim")
    table.add_column("元数据标签", style="dim")

    for turn in turns:
        result = clf.predict_turn(extract_features(turn))
        inferred = result.inferred_model or "[dim]低于阈值[/dim]"
        candidates = ", ".join(f"{m} {p:.0%}" for m, p in result.top_candidates)
        known = turn.label or "-"
        table.add_row(
            str(turn.turn_index),
            inferred,
            f"{result.probability:.0%}",
            candidates,
            known,
        )
        if db is not None:
            db.save_blindtest_inference(
                {
                    "task_id": full_task_id,
                    "turn_index": turn.turn_index,
                    "request_id": turn.request_id,
                    "inferred_model": result.inferred_model,
                    "probability": result.probability,
                    "model_version": f"{clf.backend}-v1",
                }
            )
    console.print(table)
    if db is not None:
        console.print("[dim]结果已写入 blindtest_inferences 表[/dim]")


if __name__ == "__main__":
    main()
