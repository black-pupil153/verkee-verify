"""
智力打分看板

给命令行边上提供一个"当前模型智力打分"的持续视图：
- `score --once`  跑一次打分并展示
- `score --watch` 常驻刷新（类似 top）
打分结果落库 score_snapshots，供趋势展示与 report 使用。
"""

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from verkee_verify.config import ConfigManager
from verkee_verify.monitor.engine import VerifyEngine
from verkee_verify.storage.database import Database

console = Console()

# 趋势火花图字符
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: List[float]) -> str:
    """把一串分数渲染成火花图"""
    nums = [v for v in values if v is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    span = hi - lo or 1.0
    out = []
    for v in nums:
        idx = int((v - lo) / span * (len(SPARK_CHARS) - 1))
        out.append(SPARK_CHARS[idx])
    return "".join(out)


def _score_color(score: Optional[float]) -> str:
    if score is None:
        return "dim"
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow"
    return "red"


def run_scoring(
    base_url: str,
    api_key: str,
    model: str,
    num_probes: int = 6,
    num_questions: int = 8,
) -> Dict[str, Any]:
    """跑一次打分，返回快照并落库"""
    engine = VerifyEngine(base_url=base_url, api_key=api_key, model=model)
    result = engine.verify(
        full=True,
        num_probes=num_probes,
        num_quality_questions=num_questions,
    )

    fp = result.get("fingerprint", {})
    quality = result.get("quality", {})

    intelligence = quality.get("score")
    snapshot = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "model": model,
        "base_url": base_url,
        "intelligence_score": intelligence,
        "overall_score": result.get("overall_score"),
        "quality_score": quality.get("score"),
        "baseline": quality.get("baseline"),
        "deviation": quality.get("deviation"),
        "fingerprint_family": fp.get("family"),
        "fingerprint_confidence": fp.get("confidence"),
        "fingerprint_match": fp.get("match"),
        "latency_ms": fp.get("avg_latency_ms"),
        "correct": quality.get("correct"),
        "total": quality.get("total"),
        "is_anomaly": bool(result.get("overall_score", 100) < 75),
        "note": result.get("recommendation"),
    }

    try:
        Database().save_score_snapshot(snapshot)
    except Exception as e:
        console.print(f"[dim]打分落库失败: {e}[/dim]")

    return snapshot


def _build_view(current: Optional[Dict[str, Any]] = None) -> Group:
    """构建看板视图（读 DB 渲染最新分与趋势）"""
    db = Database()
    latest = db.get_latest_scores(hours=24 * 30)

    # 顶部大字：当前模型分数
    header_items = []
    if current:
        score = current.get("intelligence_score")
        color = _score_color(score)
        model = current.get("model", "?")
        score_txt = f"{score:.0f}" if score is not None else "--"
        big = Text()
        big.append(f"{model}  ", style="bold cyan")
        big.append(f"智力分 {score_txt}/100", style=f"bold {color}")
        fam = current.get("fingerprint_family") or "?"
        conf = current.get("fingerprint_confidence")
        conf_txt = f"{conf:.0%}" if conf is not None else "?"
        big.append(f"   指纹 {fam}({conf_txt})", style="dim")
        lat = current.get("latency_ms")
        if lat:
            big.append(f"   延迟 {lat}ms", style="dim")
        header_items.append(Panel(big, title="当前渠道", border_style=color))

    # 各模型最新分 + 趋势
    table = Table(title="模型智力打分（最近30天，含趋势）", expand=True)
    table.add_column("模型", style="cyan", no_wrap=True)
    table.add_column("智力分", justify="right")
    table.add_column("基准", justify="right", style="dim")
    table.add_column("偏差", justify="right")
    table.add_column("指纹", style="dim")
    table.add_column("延迟", justify="right", style="dim")
    table.add_column("趋势", style="blue")
    table.add_column("更新时间", style="dim")

    if not latest:
        table.add_row("(暂无打分数据)", "-", "-", "-", "-", "-", "-", "-")
    else:
        for row in latest:
            model = row.get("model", "?")
            score = row.get("intelligence_score")
            color = _score_color(score)
            score_txt = Text(f"{score:.0f}" if score is not None else "--", style=color)

            deviation = row.get("deviation")
            if deviation is None:
                dev_txt = Text("-", style="dim")
            elif deviation > 8:
                dev_txt = Text(f"-{deviation:.0f}", style="red")
            elif deviation > 3:
                dev_txt = Text(f"-{deviation:.0f}", style="yellow")
            else:
                dev_txt = Text(f"{-deviation:+.0f}", style="green")

            fam = row.get("fingerprint_family") or "?"
            match = row.get("fingerprint_match")
            fam_txt = f"{fam}{'✓' if match else '✗'}"

            lat = row.get("latency_ms")
            lat_txt = f"{lat}ms" if lat else "-"

            history = db.get_score_history(model=model, hours=24 * 30, limit=40)
            spark = _sparkline([h.get("intelligence_score") for h in history])

            baseline = row.get("baseline")
            base_txt = f"{baseline:.0f}" if baseline is not None else "-"

            ts = (row.get("timestamp") or "")[:19].replace("T", " ")

            table.add_row(
                model, score_txt, base_txt, dev_txt, fam_txt, lat_txt, spark, ts
            )

    return Group(*header_items, table)


def score_once(num_probes: int = 6, num_questions: int = 8) -> None:
    """跑一次打分并展示（默认读 CC Switch 当前供应商）"""
    from verkee_verify.providers.cc_switch import resolve_provider

    provider = resolve_provider(prefer="auto")
    if not provider:
        console.print("[red]✗ 未找到上游配置（CC Switch / Claude settings / verkee-verify config）[/red]")
        return

    model = provider.model or "gpt-4"
    console.print(
        f"[cyan]正在给 {model} 打分...[/cyan] "
        f"[dim]({provider.source}: {provider.name})[/dim]"
    )
    with console.status("[bold green]评测中..."):
        current = run_scoring(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=model,
            num_probes=num_probes,
            num_questions=num_questions,
        )
    console.print(_build_view(current))


def watch(interval_seconds: int = 300, num_probes: int = 6, num_questions: int = 8) -> None:
    """常驻看板，定时刷新打分"""
    from verkee_verify.providers.cc_switch import resolve_provider

    provider = resolve_provider(prefer="auto")
    if not provider:
        console.print("[red]✗ 未找到上游配置（CC Switch / Claude settings / verkee-verify config）[/red]")
        return

    model = provider.model or "gpt-4"
    console.print(
        f"[dim]智力看板已启动 ({provider.name})，每 {interval_seconds}s 刷新，Ctrl+C 退出[/dim]"
    )

    current: Optional[Dict[str, Any]] = None
    try:
        with Live(_build_view(current), console=console, refresh_per_second=2) as live:
            while True:
                # 每次刷新重新读，方便你在 CC Switch 里切换供应商后自动跟上
                provider = resolve_provider(prefer="auto") or provider
                model = provider.model or model
                current = run_scoring(
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    model=model,
                    num_probes=num_probes,
                    num_questions=num_questions,
                )
                live.update(_build_view(current))
                slept = 0
                while slept < interval_seconds:
                    time.sleep(min(2, interval_seconds - slept))
                    slept += 2
    except KeyboardInterrupt:
        console.print("\n[yellow]看板已退出[/yellow]")


def show_board_only() -> None:
    """只展示历史看板，不触发新的打分"""
    console.print(_build_view(None))
