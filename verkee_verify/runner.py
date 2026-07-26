"""
一键包装运行：后台起代理 → 注入环境变量 → 执行用户命令 → 退出时关掉代理

典型用法：
  verkee-verify run -- claude
  verkee-verify run --port 8080 -- python my_script.py

上游配置优先从 CC Switch 当前供应商读取，无需再手动 config set。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from typing import List, Optional

import httpx
from rich.console import Console

from verkee_verify.providers.cc_switch import ProviderConfig, resolve_provider

console = Console()


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _wait_healthy(base: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _start_proxy_thread(host: str, port: int, provider: ProviderConfig) -> threading.Thread:
    """在守护线程里跑代理（进程退出时线程随之结束）"""
    from verkee_verify.proxy.server import ProxyServer

    server = ProxyServer(provider.base_url, provider.api_key, quiet=True)

    def _run():
        import asyncio

        try:
            asyncio.run(server.start(host=host, port=port))
        except Exception:
            pass

    t = threading.Thread(target=_run, name="verkee-verify-proxy", daemon=True)
    t.start()
    return t


def _build_child_env(host: str, port: int, provider: ProviderConfig) -> dict:
    """给子进程注入 Claude Code / OpenAI 兼容客户端会读的变量"""
    env = os.environ.copy()
    anthropic_base = f"http://{host}:{port}"
    openai_base = f"http://{host}:{port}/v1"

    # 强制走本地代理（覆盖 CC Switch 写进 ~/.claude/settings 的上游地址）
    env["ANTHROPIC_BASE_URL"] = anthropic_base
    env["OPENAI_BASE_URL"] = openai_base
    env["OPENAI_API_BASE"] = openai_base

    api_key = provider.api_key
    if api_key:
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_API_KEY"] = api_key
        env["OPENAI_API_KEY"] = api_key

    # 保留 CC Switch 里的模型别名等额外 env
    if provider.extra_env:
        for k, v in provider.extra_env.items():
            # 不要覆盖我们已经改成本地代理的 BASE_URL
            if k in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
                continue
            env[k] = v

    if provider.model and "ANTHROPIC_MODEL" not in env:
        env["ANTHROPIC_MODEL"] = provider.model

    # 避免系统 HTTPS_PROXY 把本地代理请求拐走
    no_proxy = env.get("NO_PROXY") or env.get("no_proxy") or ""
    extras = ["127.0.0.1", "localhost", host]
    parts = [p.strip() for p in no_proxy.replace(",", " ").split() if p.strip()]
    for e in extras:
        if e not in parts:
            parts.append(e)
    env["NO_PROXY"] = ",".join(parts)
    env["no_proxy"] = env["NO_PROXY"]

    return env


def run_with_proxy(
    command: List[str],
    host: str = "127.0.0.1",
    port: int = 8080,
    quiet: bool = False,
    prefer: str = "auto",
) -> int:
    """
    启动本地代理，带着监控环境变量执行 command，返回子进程退出码。
    """
    if not command:
        console.print("[red]✗ 请在 -- 后面写要运行的命令，例如: verkee-verify run -- claude[/red]")
        return 2

    provider = resolve_provider(prefer=prefer)
    if not provider:
        console.print("[red]✗ 未找到上游配置[/red]")
        console.print("  请在 CC Switch 里选一个供应商，或: [cyan]verkee-verify config set base_url <url>[/cyan]")
        return 1

    # 端口占用则尝试顺延几个
    chosen = port
    if not _port_free(host, chosen):
        for candidate in range(port, port + 20):
            if _port_free(host, candidate):
                chosen = candidate
                break
        else:
            console.print(f"[red]✗ 端口 {port} 附近均被占用[/red]")
            return 1
        if chosen != port and not quiet:
            console.print(f"[yellow]端口 {port} 占用，改用 {chosen}[/yellow]")

    if not quiet:
        console.print(
            f"[cyan]启动监控代理[/cyan]  "
            f"来源=[green]{provider.source}[/green]  "
            f"供应商=[green]{provider.name}[/green]"
        )
        console.print(f"[dim]上游: {provider.base_url}[/dim]")
        if provider.model:
            console.print(f"[dim]模型: {provider.model}[/dim]")
        console.print(f"[dim]本地: http://{host}:{chosen}  |  命令: {' '.join(command)}[/dim]")

    _start_proxy_thread(host, chosen, provider)
    base = f"http://{host}:{chosen}"
    if not _wait_healthy(base):
        console.print("[red]✗ 代理未能在时限内就绪[/red]")
        return 1

    if not quiet:
        console.print("[green]✓[/green] 代理就绪，正在启动命令（退出命令后代理会自动结束）\n")

    env = _build_child_env(host, chosen, provider)
    try:
        proc = subprocess.Popen(command, env=env)
    except FileNotFoundError:
        console.print(f"[red]✗ 找不到命令: {command[0]}[/red]")
        return 127

    def _forward_signal(signum, frame):
        try:
            proc.send_signal(signum)
        except Exception:
            pass

    old_int = signal.signal(signal.SIGINT, _forward_signal)
    old_term = signal.signal(signal.SIGTERM, _forward_signal)
    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
        if not quiet:
            console.print(
                "\n[dim]命令已结束，监控代理随之退出。查看记录: verkee-verify history --last 1d[/dim]"
            )
