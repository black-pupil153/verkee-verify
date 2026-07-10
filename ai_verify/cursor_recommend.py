"""
Cursor recommend — suggest actions when Auto model resolution is low.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from rich.console import Console

from ai_verify.cursor_hooks import hooks_installed
from ai_verify.monitor.cursor_usage import PeriodUsageReport, aggregate_period, parse_since
from ai_verify.storage.database import Database

AUTO_FORUM_URL = "https://forum.cursor.com/t/auto-model-mechanism-in-cursor/159697"
RESOLUTION_THRESHOLD = 0.5
DEFAULT_BLINDTEST_MODEL_PATH = Path.home() / ".ai-verify" / "blindtest" / "model.json"

console = Console()


def _blindtest_model_exists() -> bool:
    return DEFAULT_BLINDTEST_MODEL_PATH.is_file()


def build_recommendations(
    period: PeriodUsageReport,
    hooks_ok: Optional[bool] = None,
    task_id_hint: Optional[str] = None,
) -> List[str]:
    """Build recommendation lines based on period stats."""
    lines: List[str] = []
    rate = period.resolution_rate
    opaque_units = period.output_shares.get("auto-opaque", {}).get("count", 0)
    opaque_pct = period.output_shares.get("auto-opaque", {}).get("pct", 0)

    lines.append(
        f"Auto 可解析率: [bold]{rate * 100:.0f}%[/bold] "
        f"({period.resolved_requests}/{period.total_requests} requests)"
    )
    if opaque_units:
        lines.append(
            f"auto-opaque 产出: [yellow]{opaque_units} units[/yellow] "
            f"({opaque_pct:.1f}% of tracked output)"
        )

    if rate >= RESOLUTION_THRESHOLD:
        lines.append(
            "[green]解析率尚可，无需额外操作。[/green] "
            "继续用 ai-verify cursor task --latest 观察即可。"
        )
        return lines

    if hooks_ok is None:
        hooks_ok = hooks_installed()

    if not hooks_ok:
        lines.append(
            "[yellow]建议 1:[/yellow] 安装 Cursor Hooks 探针以捕获 stop/subagent 事件中的 model 字段："
        )
        lines.append("  [cyan]ai-verify cursor hooks install[/cyan]")
        lines.append("  安装后请完全重启 Cursor，再跑 1 次 Auto Agent turn，然后：")
        lines.append("  [cyan]ai-verify cursor hooks analyze[/cyan]")
    else:
        lines.append("[dim]Hooks 已安装（~/.cursor/hooks.json 含 cursor-track.sh）[/dim]")
        lines.append(
            "[yellow]Hooks 已装但解析率仍低：[/yellow] Cursor Auto 可能在 hook payload 中仍写 default。"
        )
        lines.append(f"  参考: {AUTO_FORUM_URL}")

    lines.append(
        "[yellow]建议 2:[/yellow] 在 Cursor 模型选择器中关闭 Auto，改选手选高阶模型（如 Claude Sonnet / Composer 2.5）"
    )
    lines.append("  验证: [cyan]ai-verify cursor import --since 1d && ai-verify cursor task --latest[/cyan]")
    lines.append("  手选后应出现具体 catalogModelId / resolved_model，而非 auto-opaque。")

    # 建议 3：盲测指纹推断
    if not _blindtest_model_exists():
        lines.append(
            "[yellow]建议 3:[/yellow] 构建盲测指纹分类器，对 auto-opaque turns 推断底层模型："
        )
        lines.append("  [cyan]ai-verify blindtest build-corpus && ai-verify blindtest train[/cyan]")
        lines.append("  训练后可运行: [cyan]ai-verify cursor task <id> --inferred[/cyan]")
    else:
        hint = task_id_hint or "<task_id>"
        lines.append(
            "[yellow]建议 3:[/yellow] 盲测模型已就绪，可查看 auto-opaque turns 的推断视图："
        )
        lines.append(f"  [cyan]ai-verify cursor task {hint} --inferred[/cyan]")
        lines.append("  （独立视图，不计入正式占比，附概率标注）")

    return lines


def show_recommendations(since: str = "7d") -> None:
    """Print cursor usage recommendations for low Auto resolution."""
    db = Database()
    period = aggregate_period(db, since=parse_since(since))
    console.print(f"[bold]Cursor Auto — 建议 ({since})[/bold]\n")

    if period.task_count == 0:
        console.print("[yellow]暂无数据，请先运行: ai-verify cursor import --since 7d[/yellow]")
        return

    # 取最近有 auto-opaque 产出的任务作为提示 id
    task_id_hint = None
    if period.latest_report:
        task_id_hint = period.latest_report.task_id[:8]

    for line in build_recommendations(period, task_id_hint=task_id_hint):
        console.print(line)
