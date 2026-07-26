"""
代理服务器模块

透明转发用户的 API 请求到目标渠道，并在旁路做被动监控：
- 支持 SSE 流式透传（边收边转，不破坏流式体验）
- 每次调用落库 SQLite（供 history / score 看板使用）
- 异常（模型替换 / 响应异常 / 延迟突增）触发 Webhook 报警
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import web
from rich.console import Console

from verkeep_verify.config import ConfigManager
from verkeep_verify.monitor.engine import VerifyEngine
from verkeep_verify.storage.database import Database

console = Console()

# 延迟报警阈值（毫秒）
HIGH_LATENCY_MS = 15000
# 响应过短阈值（字符）
SHORT_RESPONSE_CHARS = 5


class ProxyServer:
    """API 代理服务器"""

    def __init__(
        self,
        target_url: str,
        api_key: Optional[str] = None,
        quiet: bool = False,
    ):
        self.target_url = target_url.rstrip("/")
        self.api_key = api_key
        self.quiet = quiet
        self.session: Optional[aiohttp.ClientSession] = None
        self.verify_engine: Optional[VerifyEngine] = None
        self.call_count = 0

        self._db: Optional[Database] = None
        self.alert_manager = self._build_alert_manager()

        # 统计信息
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency_ms": 0,
            "models_seen": set(),
            "anomalies": 0,
        }

    def _log(self, message: str) -> None:
        """quiet 模式下写文件，避免打乱 Claude Code 等 TUI"""
        if self.quiet:
            try:
                from pathlib import Path

                from verkeep_verify.paths import verify_home

                log_path = verify_home() / "logs" / "proxy.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(message + "\n")
            except Exception:
                pass
        else:
            console.print(message)

    @property
    def db(self) -> Database:
        """延迟初始化数据库，避免测试/导入时强制写 ~/.verkeep/verify"""
        if self._db is None:
            self._db = Database()
        return self._db

    def _build_alert_manager(self):
        """根据配置构建报警管理器"""
        from verkeep_verify.alerts import AlertManager

        manager = AlertManager()
        cfg = ConfigManager().load()
        webhook = cfg.get("alerts", {}).get("webhook") if isinstance(cfg.get("alerts"), dict) else None
        platform = "auto"
        if isinstance(cfg.get("alerts"), dict):
            platform = cfg["alerts"].get("webhook_platform", "auto")
        if webhook:
            manager.add_webhook(webhook, platform)
        return manager

    async def start(self, host: str = "127.0.0.1", port: int = 8080):
        """启动代理服务器"""
        self.session = aiohttp.ClientSession()

        cfg = ConfigManager().load()
        if cfg.get("api_key"):
            self.verify_engine = VerifyEngine(
                base_url=self.target_url,
                api_key=cfg["api_key"],
                model=cfg.get("model", "gpt-4"),
            )

        app = web.Application()
        app.router.add_route("GET", "/health", self.health_check)
        app.router.add_route("GET", "/stats", self.get_stats)
        app.router.add_route("*", "/v1/{path:.*}", self.handle_request_v1)
        app.router.add_route("*", "/{path:.*}", self.handle_request)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)

        if not self.quiet:
            console.print(f"[green]✓[/green] 代理服务器已启动: http://{host}:{port}")
            console.print(f"[green]✓[/green] 目标 API: {self.target_url}")
            console.print("")
            console.print("[cyan]使用方式:[/cyan]")
            console.print(f"  export ANTHROPIC_BASE_URL=http://{host}:{port}")
            console.print(f"  或 export OPENAI_BASE_URL=http://{host}:{port}/v1")
            console.print("")
            console.print("[dim]按 Ctrl+C 停止[/dim]")
            console.print("")
        else:
            self._log(f"proxy started on http://{host}:{port} → {self.target_url}")

        await site.start()

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.session.close()

    async def handle_request_v1(self, request: web.Request) -> web.Response:
        path = request.match_info["path"]
        target_url = f"{self.target_url}/v1/{path}"
        return await self._forward_request(request, target_url)

    async def handle_request(self, request: web.Request) -> web.Response:
        path = request.match_info["path"]
        target_url = f"{self.target_url}/{path}"
        return await self._forward_request(request, target_url)

    async def _forward_request(self, request: web.Request, target_url: str) -> web.Response:
        """转发请求，透明支持普通与流式响应"""
        start_time = time.time()
        self.stats["total_requests"] += 1
        self.call_count += 1
        call_num = self.call_count

        headers = dict(request.headers)
        headers.pop("Host", None)

        if self.api_key and "Authorization" not in headers and "x-api-key" not in headers:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = await request.read()
        request_data = None
        try:
            request_data = json.loads(body)
        except Exception:
            pass

        is_stream_request = bool(request_data and request_data.get("stream"))

        try:
            upstream = await self.session.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=300),
            )
        except Exception as e:
            self.stats["failed_requests"] += 1
            self._log(f"request failed: {e}")
            return web.Response(status=502, body=json.dumps({"error": str(e)}))

        content_type = upstream.headers.get("Content-Type", "")
        is_stream_response = "text/event-stream" in content_type.lower() or is_stream_request

        if is_stream_response:
            return await self._handle_streaming(
                request, upstream, request_data, start_time, call_num
            )
        return await self._handle_non_streaming(
            upstream, request_data, start_time, call_num
        )

    async def _handle_non_streaming(
        self, upstream, request_data, start_time, call_num
    ) -> web.Response:
        response_body = await upstream.read()
        latency_ms = int((time.time() - start_time) * 1000)

        self.stats["successful_requests"] += 1
        self.stats["total_latency_ms"] += latency_ms

        response_data = None
        try:
            response_data = json.loads(response_body)
        except Exception:
            pass

        if response_data is not None:
            content, actual_model, usage = self._extract_from_json(response_data)
            asyncio.create_task(
                self._analyze(request_data, actual_model, content, usage, latency_ms, call_num)
            )

        # 过滤逐跳头，避免 Content-Length/Transfer-Encoding 冲突
        resp_headers = self._filter_headers(upstream.headers)
        return web.Response(
            status=upstream.status,
            body=response_body,
            headers=resp_headers,
        )

    async def _handle_streaming(
        self, request, upstream, request_data, start_time, call_num
    ) -> web.StreamResponse:
        """流式透传：边收边转，同时旁路累积用于分析"""
        resp_headers = self._filter_headers(upstream.headers)
        stream_resp = web.StreamResponse(status=upstream.status, headers=resp_headers)
        await stream_resp.prepare(request)

        raw_chunks: list[bytes] = []
        try:
            async for chunk in upstream.content.iter_any():
                raw_chunks.append(chunk)
                await stream_resp.write(chunk)
        except Exception as e:
            self._log(f"stream interrupted: {e}")
        finally:
            await stream_resp.write_eof()

        latency_ms = int((time.time() - start_time) * 1000)
        self.stats["successful_requests"] += 1
        self.stats["total_latency_ms"] += latency_ms

        raw = b"".join(raw_chunks)
        content, actual_model, usage = self._parse_sse(raw)
        asyncio.create_task(
            self._analyze(request_data, actual_model, content, usage, latency_ms, call_num)
        )
        return stream_resp

    @staticmethod
    def _filter_headers(headers) -> Dict[str, str]:
        """去掉逐跳/长度类响应头，交给 aiohttp 重新计算"""
        drop = {
            "content-length",
            "transfer-encoding",
            "content-encoding",
            "connection",
            "keep-alive",
        }
        return {k: v for k, v in headers.items() if k.lower() not in drop}

    @staticmethod
    def _extract_from_json(response_data: dict) -> tuple:
        """从非流式 JSON 响应提取 content / model / usage"""
        content = ""
        if "content" in response_data and isinstance(response_data["content"], list):
            # Anthropic
            parts = [c.get("text", "") for c in response_data["content"] if isinstance(c, dict)]
            content = "".join(parts)
        elif "choices" in response_data:
            # OpenAI 兼容
            choice = response_data["choices"][0] if response_data["choices"] else {}
            content = choice.get("message", {}).get("content", "") or ""

        actual_model = response_data.get("model")
        usage = response_data.get("usage", {}) or {}
        return content, actual_model, usage

    @staticmethod
    def _parse_sse(raw: bytes) -> tuple:
        """解析 SSE 流，累积文本内容并提取 model / usage（尽力而为）"""
        text = raw.decode("utf-8", errors="ignore")
        content_parts: list[str] = []
        actual_model = None
        usage: Dict[str, Any] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue

            if actual_model is None and obj.get("model"):
                actual_model = obj.get("model")

            # OpenAI 流式 delta
            for choice in obj.get("choices", []) or []:
                delta = choice.get("delta", {})
                if isinstance(delta, dict) and delta.get("content"):
                    content_parts.append(delta["content"])

            # Anthropic 流式：content_block_delta
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta", {})
                if isinstance(delta, dict) and delta.get("text"):
                    content_parts.append(delta["text"])
            if obj.get("type") == "message_start":
                msg = obj.get("message", {})
                if msg.get("model"):
                    actual_model = msg["model"]

            if obj.get("usage"):
                usage = obj["usage"]

        return "".join(content_parts), actual_model, usage

    async def _analyze(
        self,
        request_data: Optional[dict],
        actual_model: Optional[str],
        content: str,
        usage: dict,
        latency_ms: int,
        call_num: int,
    ):
        """被动分析：展示、异常检测、落库、报警"""
        try:
            requested_model = (request_data or {}).get("model", "unknown")
            actual_model = actual_model or requested_model
            self.stats["models_seen"].add(actual_model)

            input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0

            anomalies = self._detect_anomalies(
                requested_model, actual_model, content, latency_ms
            )

            self._display_call_info(
                call_num=call_num,
                model=requested_model,
                actual_model=actual_model,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                content_preview=content[:50],
                anomalies=anomalies,
            )

            await self._persist(
                requested_model=requested_model,
                actual_model=actual_model,
                content=content,
                request_data=request_data,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                anomalies=anomalies,
            )

            if anomalies:
                self.stats["anomalies"] += 1
                self._send_alert(requested_model, actual_model, anomalies, latency_ms)

        except Exception as e:
            self._log(f"analyze failed: {e}")

    def _detect_anomalies(
        self, requested_model: str, actual_model: str, content: str, latency_ms: int
    ) -> list:
        """轻量被动异常检测"""
        anomalies = []

        if actual_model and requested_model != actual_model and requested_model != "unknown":
            try:
                engine = VerifyEngine(
                    base_url=self.target_url,
                    api_key=self.api_key or "",
                    model=requested_model,
                )
                match = engine._check_model_match(actual_model)
            except Exception:
                match = False
            if not match:
                anomalies.append(("model_substitution", f"请求 {requested_model} → 返回 {actual_model}"))

        if content is not None and len(content.strip()) < SHORT_RESPONSE_CHARS:
            anomalies.append(("short_response", f"响应异常短({len(content.strip())} 字符)"))

        if latency_ms > HIGH_LATENCY_MS:
            anomalies.append(("high_latency", f"响应延迟 {latency_ms}ms"))

        return anomalies

    async def _persist(
        self,
        requested_model,
        actual_model,
        content,
        request_data,
        input_tokens,
        output_tokens,
        latency_ms,
        anomalies,
    ):
        """落库到 SQLite"""
        try:
            request_preview = ""
            if request_data:
                msgs = request_data.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    request_preview = str(last.get("content", ""))[:500]

            await self.db.save_call({
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "model": requested_model,
                "claimed_model": requested_model,
                "request_tokens": input_tokens,
                "response_tokens": output_tokens,
                "latency_ms": latency_ms,
                "status_code": 200,
                "fingerprint_family": None,
                "fingerprint_confidence": None,
                "quality_score": None,
                "is_anomaly": bool(anomalies),
                "anomaly_type": ",".join(a[0] for a in anomalies) if anomalies else None,
                "request_preview": request_preview,
                "response_preview": (content or "")[:500],
            })
        except Exception as e:
            self._log(f"persist failed: {e}")

    def _send_alert(self, requested_model, actual_model, anomalies, latency_ms):
        """发送异常报警到控制台 + Webhook"""
        try:
            from verkeep_verify.alerts import AlertLevel

            messages = "; ".join(msg for _, msg in anomalies)
            has_substitution = any(t == "model_substitution" for t, _ in anomalies)
            level = AlertLevel.CRITICAL if has_substitution else AlertLevel.WARNING

            # quiet 模式下只走 webhook，避免污染 TUI；无 webhook 则写日志
            if self.quiet:
                if self.alert_manager.webhooks:
                    # 临时关掉控制台输出
                    old = self.alert_manager.console_enabled
                    self.alert_manager.console_enabled = False
                    try:
                        self.alert_manager.alert(
                            title="Verkeep Verify 代理监控异常",
                            message=messages,
                            level=level,
                            details={
                                "请求模型": requested_model,
                                "实际模型": actual_model,
                                "延迟": f"{latency_ms}ms",
                            },
                        )
                    finally:
                        self.alert_manager.console_enabled = old
                self._log(f"ALERT {requested_model}→{actual_model}: {messages}")
                return

            self.alert_manager.alert(
                title="Verkeep Verify 代理监控异常",
                message=messages,
                level=level,
                details={
                    "请求模型": requested_model,
                    "实际模型": actual_model,
                    "延迟": f"{latency_ms}ms",
                },
            )
        except Exception as e:
            self._log(f"alert failed: {e}")

    def _display_call_info(
        self,
        call_num: int,
        model: str,
        actual_model: str,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        content_preview: str,
        anomalies: list,
    ):
        line = (
            f"{call_num:4d} │ {str(model)[:20]:<20} │ "
            f"{'!' if anomalies else 'ok'} │ {latency_ms:>6}ms │ "
            f"{input_tokens:>4}→{output_tokens:<4} │ {content_preview[:30]}"
        )
        if self.quiet:
            self._log(line)
            for _, msg in anomalies:
                self._log(f"       ! {msg}")
            return

        if latency_ms < 2000:
            latency_color = "green"
        elif latency_ms < 5000:
            latency_color = "yellow"
        else:
            latency_color = "red"

        marker = "⚠" if anomalies else ("🎯" if actual_model and actual_model != model else "✓")
        model_color = "yellow" if anomalies else "green"

        console.print(
            f"[dim]{call_num:4d}[/dim] │ "
            f"[{model_color}]{str(model)[:20]:<20}[/{model_color}] │ "
            f"{marker} │ "
            f"[{latency_color}]{latency_ms:>6}ms[/{latency_color}] │ "
            f"[dim]{input_tokens:>4}→{output_tokens:<4}[/dim] │ "
            f"[dim]{content_preview[:30]}[/dim]"
        )
        for _, msg in anomalies:
            console.print(f"       [yellow]⚠ {msg}[/yellow]")

    async def health_check(self, request: web.Request) -> web.Response:
        return web.Response(body=json.dumps({"status": "ok", "target": self.target_url}))

    async def get_stats(self, request: web.Request) -> web.Response:
        stats = dict(self.stats)
        stats["models_seen"] = list(stats["models_seen"])
        stats["avg_latency_ms"] = (
            stats["total_latency_ms"] // stats["successful_requests"]
            if stats["successful_requests"] > 0 else 0
        )
        return web.Response(body=json.dumps(stats))


def start_proxy_server(host: str = "127.0.0.1", port: int = 8080):
    """启动代理服务器（同步入口）"""
    cfg = ConfigManager().load()
    target_url = cfg.get("base_url", "https://api.openai.com")
    api_key = cfg.get("api_key")

    if not target_url:
        console.print("[red]✗ 请先配置目标 API: verkeep-verify config set base_url <url>[/red]")
        return

    server = ProxyServer(target_url, api_key)

    try:
        asyncio.run(server.start(host=host, port=port))
    except KeyboardInterrupt:
        console.print("\n[yellow]代理服务器已停止[/yellow]")
