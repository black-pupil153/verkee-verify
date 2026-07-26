"""
定时监控守护进程

周期性地给配置的渠道打分并落库；发现异常（综合分下滑/指纹不符）时报警。
前台运行，Ctrl+C 退出。
"""

import time
from datetime import datetime
from typing import Optional

from rich.console import Console

from verkee_verify.config import ConfigManager
from verkee_verify.dashboard import run_scoring

console = Console()


def parse_interval(text: str) -> int:
    """把 '6h' / '30m' / '90s' 解析为秒"""
    text = text.strip().lower()
    if not text:
        return 6 * 3600
    unit = text[-1]
    try:
        value = int(text[:-1]) if unit in "smhd" else int(text)
    except ValueError:
        return 6 * 3600
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return value * 3600  # 默认按小时


def _maybe_alert(snapshot: dict):
    """异常时报警到控制台 + Webhook"""
    overall = snapshot.get("overall_score")
    fingerprint_match = snapshot.get("fingerprint_match")
    deviation = snapshot.get("deviation") or 0

    reasons = []
    if overall is not None and overall < 75:
        reasons.append(f"综合分偏低({overall})")
    if fingerprint_match is False:
        reasons.append(f"指纹不匹配(检测为 {snapshot.get('fingerprint_family')})")
    if deviation and deviation > 10:
        reasons.append(f"质量偏差 {deviation:.0f} 分")

    if not reasons:
        return

    try:
        from verkee_verify.alerts import AlertLevel, AlertManager

        manager = AlertManager()
        cfg = ConfigManager().load()
        alerts_cfg = cfg.get("alerts") if isinstance(cfg.get("alerts"), dict) else {}
        webhook = alerts_cfg.get("webhook")
        if webhook:
            manager.add_webhook(webhook, alerts_cfg.get("webhook_platform", "auto"))

        manager.alert(
            title="Verkee Verify 定时巡检异常",
            message="；".join(reasons),
            level=AlertLevel.WARNING,
            details={
                "模型": snapshot.get("model"),
                "智力分": snapshot.get("intelligence_score"),
                "综合分": overall,
                "指纹": snapshot.get("fingerprint_family"),
            },
        )
    except Exception as e:
        console.print(f"[dim]报警失败: {e}[/dim]")


def run(interval: str = "6h", num_probes: int = 6, num_questions: int = 8) -> None:
    """启动定时监控（前台）"""
    from verkee_verify.providers.cc_switch import resolve_provider

    provider = resolve_provider(prefer="auto")
    if not provider:
        console.print("[red]✗ 未找到上游配置（CC Switch / Claude settings / verkee-verify config）[/red]")
        return

    interval_seconds = parse_interval(interval)
    model = provider.model or "gpt-4"

    console.print(
        f"[green]✓[/green] 定时监控已启动: {provider.name} / {model}, 间隔 {interval}"
    )
    console.print(f"[dim]上游: {provider.base_url}[/dim]")
    console.print("[dim]按 Ctrl+C 停止[/dim]\n")

    try:
        while True:
            # 每次巡检重新读，跟上 CC Switch 切换
            provider = resolve_provider(prefer="auto") or provider
            model = provider.model or model
            ts = datetime.now().strftime("%H:%M:%S")
            with console.status(f"[bold green]{ts} 正在巡检打分..."):
                snapshot = run_scoring(
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    model=model,
                    num_probes=num_probes,
                    num_questions=num_questions,
                )

            score = snapshot.get("intelligence_score")
            overall = snapshot.get("overall_score")
            console.print(
                f"[dim]{ts}[/dim] {model} │ 智力分 [bold]{score}[/bold] │ "
                f"综合 {overall} │ 指纹 {snapshot.get('fingerprint_family')}"
            )
            _maybe_alert(snapshot)

            slept = 0
            while slept < interval_seconds:
                time.sleep(min(5, interval_seconds - slept))
                slept += 5
    except KeyboardInterrupt:
        console.print("\n[yellow]定时监控已停止[/yellow]")
