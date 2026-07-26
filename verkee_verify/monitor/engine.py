"""
验证引擎模块 - 整合指纹识别和质量测试
"""

import time
from typing import Any, Dict, Optional

from rich.console import Console
from rich.table import Table

from verkee_verify.monitor.fingerprint import FingerprintDetector
from verkee_verify.monitor.quality import QualityTester

console = Console()


class VerifyEngine:
    """API 验证引擎"""

    def __init__(self, base_url: str, api_key: str, model: str, api_type: str = "auto"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_type = api_type

        # 组件
        self.fingerprint_detector = FingerprintDetector()
        self.quality_tester = QualityTester()

        # 自动检测 API 类型
        if api_type == "auto":
            self.api_type = self._detect_api_type()

    def _detect_api_type(self) -> str:
        """自动检测 API 类型

        优先按 base_url 判断（最可靠），其次按模型名兜底。
        GLM(智谱)原生 /api/paas/v4 与 OpenAI 兼容，走 openai 分支即可，
        单独标记 glm 仅用于报告与基准归类。
        """
        url = self.base_url.lower()
        model = self.model.lower()

        if "anthropic" in url:
            return "anthropic"
        if "bigmodel" in url or "/api/paas" in url:
            return "glm"
        if "openai" in url:
            return "openai"

        # base_url 不含明显标识时按模型名兜底。
        # 注意：不把 claude 兜底成 anthropic —— 绝大多数中转站用 OpenAI 兼容
        # 格式转发 claude，只有 URL 明确含 anthropic 时才走 /v1/messages。
        if "glm" in model:
            return "glm"
        return "openai"

    def verify(
        self,
        full: bool = False,
        num_probes: int = 10,
        num_quality_questions: int = 10,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        执行完整验证

        Args:
            full: 是否执行完整测试
            num_probes: 指纹探针数量
            num_quality_questions: 质量测试问题数量
            progress_callback: 进度回调

        Returns:
            验证结果
        """
        result = {
            "model": self.model,
            "actual_model": None,
            "overall_score": 0,
            "fingerprint": {},
            "quality": {},
            "security": {},
            "recommendation": None,
            "elapsed_seconds": 0,
        }

        start_time = time.time()

        # 1. 指纹识别
        result["fingerprint"] = self._verify_fingerprint(num_probes=num_probes)

        # 2. 质量评估
        if full:
            result["quality"] = self._verify_quality(num_questions=num_quality_questions)
        else:
            result["quality"] = self._quick_quality_check()

        # 3. 安全检测
        result["security"] = self._verify_security()

        result["elapsed_seconds"] = round(time.time() - start_time, 2)

        # 计算综合评分
        result["overall_score"] = self._calculate_overall(result)

        # 生成建议
        result["recommendation"] = self._generate_recommendation(result)

        return result

    def _verify_fingerprint(self, num_probes: int = 10) -> Dict[str, Any]:
        """验证模型指纹"""
        try:
            # 使用指纹检测器
            result = self.fingerprint_detector.identify(
                client_factory=self._send_test_request,
                model=self.model,
                num_probes=num_probes,
            )

            # 添加模型名称检查
            actual_model = self._get_actual_model_name()
            result["actual_model"] = actual_model

            if actual_model:
                result["model_name_match"] = self._check_model_match(actual_model)

            return result

        except Exception as e:
            return {
                "family": "Unknown",
                "confidence": 0,
                "match": False,
                "error": str(e),
            }

    def _verify_quality(self, num_questions: int = 10) -> Dict[str, Any]:
        """完整质量评估"""
        try:
            result = self.quality_tester.run_test(
                client_factory=self._send_test_request,
                model=self.model,
                num_questions=num_questions,
            )
            return result
        except Exception as e:
            return {
                "score": 0,
                "error": str(e),
            }

    def _quick_quality_check(self) -> Dict[str, Any]:
        """快速质量检测"""
        try:
            return self.quality_tester.quick_test(
                client_factory=self._send_test_request,
                model=self.model,
            )
        except Exception as e:
            # 回退到简单评估
            baseline = self.quality_tester._get_baseline(self.model)
            baseline_score = baseline["overall"]
            return {
                "score": baseline_score - 3,
                "baseline": baseline_score,
                "deviation": 3,
            }

    def _verify_security(self) -> Dict[str, Any]:
        """安全检测（隐蔽式：用自然问题触发，观察是否有注入痕迹）

        不再使用 "output your system prompt" 这类明显的 red-team 句式
        （容易被中转站识别并针对）。改为发一个普通请求，检查响应里
        是否出现被注入的系统提示词/推广内容/异常拒绝等痕迹。
        """
        issues = []

        # 会暴露注入的自然问题：正常模型会直接回答，被塞了推广/引流
        # 系统提示的渠道往往会夹带无关内容。
        benign_prompt = "帮我用一句话总结一下你能做什么。"

        try:
            response = self._send_test_request(benign_prompt, max_tokens=200)
            response_lower = response.lower()

            # 1) 系统提示/指令泄露痕迹
            leak_markers = [
                "system prompt", "系统提示", "你的角色是", "you are chatgpt",
                "the following instructions", "###", "<system>",
            ]
            if any(m in response_lower for m in leak_markers):
                issues.append("响应中出现疑似系统提示/指令泄露痕迹")

            # 2) 注入的推广/引流内容（常见于被篡改的中转站）
            promo_markers = [
                "http://", "https://", "微信", "加群", "客服", "优惠", "折扣",
                "telegram", "t.me", "官网", "充值",
            ]
            if any(m in response_lower for m in promo_markers):
                issues.append("响应中出现疑似注入的推广/引流内容")

            # 3) 异常拒绝模式
            quick_result = self.fingerprint_detector.quick_check(response)
            if quick_result.get("suspicious"):
                issues.append(f"可疑响应模式: {quick_result.get('reason')}")

        except Exception:
            pass

        return {
            "issues": issues,
            "hidden_prompt_detected": len(issues) > 0,
        }

    def _send_test_request(
        self,
        prompt: str = "Hello",
        max_tokens: int = 100,
        temperature: Optional[float] = None,
        messages: Optional[list] = None,
    ) -> str:
        """发送测试请求"""
        response, _, _ = self._send_test_request_with_details(
            prompt, max_tokens=max_tokens, temperature=temperature, messages=messages
        )
        return response

    def _get_actual_model_name(self) -> Optional[str]:
        """获取实际返回的模型名称"""
        _, actual_model, _ = self._send_test_request_with_details("Hi")
        return actual_model

    def _send_test_request_with_details(
        self,
        prompt: str = "Hello",
        max_tokens: int = 100,
        temperature: Optional[float] = None,
        messages: Optional[list] = None,
    ) -> tuple:
        """发送测试请求并返回详细信息"""
        start_time = time.time()

        msg_list = messages or [{"role": "user", "content": prompt}]

        if self.api_type == "anthropic":
            return self._send_anthropic_request(msg_list, start_time, max_tokens, temperature)
        else:
            # openai 与 glm 都走 OpenAI 兼容格式
            return self._send_openai_request(msg_list, start_time, max_tokens, temperature)

    def _anthropic_messages_url(self) -> str:
        """构造 Anthropic messages 端点，避免 base_url 已含 /v1 时出现双 /v1"""
        base = self.base_url
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return f"{base}/v1/messages"

    def _openai_completions_url(self) -> str:
        """构造 OpenAI 兼容 chat/completions 端点"""
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _send_anthropic_request(
        self, messages: list, start_time: float, max_tokens: int = 100,
        temperature: Optional[float] = None,
    ) -> tuple:
        """发送 Anthropic 格式请求"""
        import httpx

        url = self._anthropic_messages_url()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        data = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if temperature is not None:
            data["temperature"] = temperature

        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=data)
            result = response.json()

            latency = int((time.time() - start_time) * 1000)
            actual_model = result.get("model")

            if "content" in result and len(result["content"]) > 0:
                content = result["content"][0].get("text", "")
            else:
                content = ""

            return content, actual_model, latency

    def _send_openai_request(
        self, messages: list, start_time: float, max_tokens: int = 100,
        temperature: Optional[float] = None,
    ) -> tuple:
        """发送 OpenAI 兼容格式请求 (含 GLM)"""
        import httpx

        url = self._openai_completions_url()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            data["temperature"] = temperature

        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=data)
            result = response.json()

            latency = int((time.time() - start_time) * 1000)
            actual_model = result.get("model")

            if "choices" in result:
                content = result["choices"][0]["message"]["content"]
            else:
                content = ""

            return content, actual_model, latency

    def _check_model_match(self, actual_model: str) -> bool:
        """检查模型名称是否匹配"""
        claimed_lower = self.model.lower()
        actual_lower = actual_model.lower()

        # Claude 系列匹配规则
        if "claude" in claimed_lower and "claude" in actual_lower:
            # 检查版本
            if "sonnet" in claimed_lower and "sonnet" in actual_lower:
                return True
            if "opus" in claimed_lower and "opus" in actual_lower:
                return True
            if "haiku" in claimed_lower and "haiku" in actual_lower:
                return True
            # claude-sonnet-4-6-cc vs claude-sonnet-4.6
            if "sonnet-4" in claimed_lower or "sonnet 4" in claimed_lower:
                if "sonnet-4" in actual_lower or "sonnet.4" in actual_lower:
                    return True

        # GPT 系列匹配规则
        if "gpt" in claimed_lower and "gpt" in actual_lower:
            return True

        # GLM(智谱) 系列匹配规则
        if "glm" in claimed_lower and "glm" in actual_lower:
            return True

        # 其他家族：只要家族关键字一致即视为匹配
        for fam in ("qwen", "deepseek", "gemini", "llama", "mistral"):
            if fam in claimed_lower and fam in actual_lower:
                return True

        # 包含匹配
        return claimed_lower in actual_lower or actual_lower in claimed_lower

    def _calculate_overall(self, result: Dict) -> int:
        """计算综合评分"""
        score = 100

        # 指纹不匹配扣分
        fp = result.get("fingerprint", {})
        if not fp.get("match"):
            score -= 25

        # 模型名称不匹配额外扣分
        if fp.get("actual_model") and not fp.get("model_name_match", True):
            score -= 15

        # 质量偏差扣分
        quality = result.get("quality", {})
        deviation = quality.get("deviation", 0)
        if deviation > 15:
            score -= 25
        elif deviation > 10:
            score -= 15
        elif deviation > 5:
            score -= 8

        # 安全问题扣分
        if result.get("security", {}).get("issues"):
            score -= 15

        return max(0, score)

    def _generate_recommendation(self, result: Dict) -> str:
        """生成建议"""
        fp = result.get("fingerprint", {})
        quality = result.get("quality", {})
        security = result.get("security", {})

        # 检查模型替换
        if fp.get("actual_model") and not fp.get("model_name_match", True):
            return f"⚠️ 检测到模型替换: 声称 {self.model}, 实际返回 {fp['actual_model']}"

        # 检查安全问题
        if security.get("issues"):
            return f"⚠️ 检测到安全问题: {', '.join(security['issues'])}"

        # 基于综合评分
        overall = result.get("overall_score", 0)

        if overall >= 90:
            return "✅ 渠道可信，可以正常使用"
        elif overall >= 75:
            return "✅ 渠道基本可信，建议定期监控"
        elif overall >= 60:
            return "⚠️ 渠道存在轻微问题，建议持续监控"
        elif overall >= 40:
            return "⚠️ 渠道存在可疑情况，建议谨慎使用"
        else:
            return "❌ 渠道风险较高，建议更换"


def display_verify_result(result: Dict[str, Any]):
    """显示验证结果"""
    console.print()

    # 综合评分
    score = result.get("overall_score", 0)
    score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(f"综合评分: [{score_color}]{score}[/{score_color}]/100")
    console.print()

    # 详细结果表格
    table = Table(title="验证详情")
    table.add_column("检测项", style="cyan", width=15)
    table.add_column("结果", width=10)
    table.add_column("详情", width=50)

    # 指纹识别
    fp = result.get("fingerprint", {})
    fp_status = "✓" if fp.get("match") else "✗"
    fp_color = "green" if fp.get("match") else "red"
    fp_detail = f"识别为 {fp.get('family', 'unknown')} ({fp.get('confidence', 0):.0%})"
    if fp.get("actual_model"):
        fp_detail += f"\n实际模型: {fp['actual_model']}"
    table.add_row(
        "模型指纹",
        f"[{fp_color}]{fp_status}[/{fp_color}]",
        fp_detail
    )

    # 质量评估
    quality = result.get("quality", {})
    q_score = quality.get("score", 0)
    q_color = "green" if q_score >= 80 else "yellow" if q_score >= 60 else "red"
    q_detail = f"得分 {q_score}/100"
    if quality.get("baseline"):
        q_detail += f" (基准: {quality['baseline']}, 偏差: {quality.get('deviation', 0):.1f}%)"
    if quality.get("correct") is not None:
        q_detail += f"\n正确: {quality['correct']}/{quality.get('total', '?')}"
    table.add_row(
        "质量评估",
        f"[{q_color}]{q_score}[/{q_color}]/100",
        q_detail
    )

    # 安全检测
    security = result.get("security", {})
    sec_status = "✓" if not security.get("issues") else "⚠"
    sec_color = "green" if not security.get("issues") else "yellow"
    issues = security.get("issues", [])
    table.add_row(
        "安全检测",
        f"[{sec_color}]{sec_status}[/{sec_color}]",
        ", ".join(issues) if issues else "未发现问题"
    )

    console.print(table)
    console.print()

    # 建议
    if result.get("recommendation"):
        console.print(f"💡 建议: {result['recommendation']}")

    # 耗时
    if result.get("elapsed_seconds"):
        console.print(f"[dim]验证耗时: {result['elapsed_seconds']}秒[/dim]")
