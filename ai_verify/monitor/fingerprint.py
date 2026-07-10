"""
模型指纹识别模块
基于 LLM-Fingerprinter 实现
"""

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_verify.monitor.probes import get_probe_pool

# 本地缓存目录
CACHE_DIR = Path.home() / ".ai-verify" / "cache"
MODEL_DIR = CACHE_DIR / "fingerprint_models"


class FingerprintDetector:
    """模型指纹检测器"""

    # 支持的模型家族
    MODEL_FAMILIES = [
        "GPT",
        "Claude",
        "LLaMA",
        "Mistral",
        "Gemini",
        "DeepSeek",
        "Qwen",
        "Command",
        "Unknown",
    ]

    # 各家族的响应特征
    FAMILY_SIGNATURES = {
        "Claude": {
            "positive": ["i'd be happy to", "i can help you", "let me", "i'll", "here's",
                         "certainly", "i understand"],
            "negative": ["as an ai language model", "i'm an ai"],
        },
        "GPT": {
            "positive": ["as an ai", "i'm here to help", "i don't have access to", "i cannot",
                         "sure!", "certainly!"],
            "negative": [],
        },
        "LLaMA": {
            "positive": [],  # LLaMA 没有特别明显的特征
            "negative": [],
        },
        "Gemini": {
            "positive": ["as a language model", "i am a large language model",
                         "i'm a large language model"],
            "negative": [],
        },
        "GLM": {
            "positive": ["作为一个人工智能", "我是一个人工智能助手", "很高兴帮助你",
                         "作为智谱", "chatglm"],
            "negative": [],
        },
        "Qwen": {
            "positive": ["我是通义千问", "作为通义千问", "qwen", "阿里云"],
            "negative": [],
        },
        "DeepSeek": {
            "positive": ["我是 deepseek", "deepseek", "作为一个ai助手"],
            "negative": [],
        },
    }

    def __init__(self, use_full_fingerprinter: bool = False):
        self.use_full = use_full_fingerprinter
        self.llm_fp = None
        self.has_classifier = False
        self.prompts = self._get_probe_prompts()

        if use_full_fingerprinter:
            self._try_init_fingerprinter()

    def _try_init_fingerprinter(self):
        """尝试初始化可选的 LLM-Fingerprinter（缺失时静默回退到启发式）"""
        try:
            from llm_fingerprinter import PromptSuite, FeatureExtractor, EnsembleClassifier

            self.prompt_suite = PromptSuite()
            self.extractor = FeatureExtractor()

            model_path = MODEL_DIR / "classifier.joblib"
            if model_path.exists():
                self.classifier = EnsembleClassifier.load(str(model_path))
                self.has_classifier = True
            else:
                self.classifier = None
                self.has_classifier = False

            self.llm_fp = True
        except Exception:
            # 未安装 [ml] 可选依赖时，静默使用轻量启发式，不打印噪音
            self.llm_fp = None

    def _get_probe_prompts(self) -> List[Dict[str, str]]:
        """获取探针问题集（反侦测题池）"""
        return get_probe_pool()

    @staticmethod
    def _perturbed_kwargs(rng: "random.Random", layer: str) -> Dict[str, Any]:
        """生成扰动后的请求参数，让探针更像自然流量"""
        # 不同层给不同长度区间，避免统一 max_tokens=100 的固定特征
        if layer == "discriminative":
            max_tokens = rng.choice([80, 120, 150, 200])
        elif layer == "stylistic":
            max_tokens = rng.choice([120, 180, 220, 256])
        else:
            max_tokens = rng.choice([150, 200, 256, 320])

        kwargs: Dict[str, Any] = {"max_tokens": max_tokens}
        # 约一半概率带上一个自然的温度值
        if rng.random() < 0.5:
            kwargs["temperature"] = round(rng.uniform(0.5, 1.0), 2)
        return kwargs

    @staticmethod
    def _call(client_factory, prompt: str, kwargs: Dict[str, Any]) -> str:
        """调用发送函数，兼容只接受单个 prompt 参数的简单实现"""
        try:
            return client_factory(prompt, **kwargs)
        except TypeError:
            return client_factory(prompt)

    def identify(
        self,
        client_factory,
        model: str,
        num_probes: int = 10,
        callback=None,
    ) -> Dict[str, Any]:
        """
        识别模型家族

        Args:
            client_factory: 用于发送请求的函数 (prompt) -> response_text
            model: 模型名称
            num_probes: 使用的探针问题数量
            callback: 进度回调函数

        Returns:
            识别结果
        """
        start_time = time.time()

        # 每次用时间相关的随机源，避免可预测/可穷举的探测序列
        rng = random.Random(time.time_ns())
        selected_prompts = rng.sample(
            self.prompts,
            min(num_probes, len(self.prompts))
        )
        # 再次打散顺序
        rng.shuffle(selected_prompts)

        responses = []
        latencies = []

        for i, prompt_dict in enumerate(selected_prompts):
            prompt = prompt_dict["text"]

            try:
                probe_start = time.time()
                # 请求参数轻微扰动，模拟真人流量（浮动 max_tokens、偶尔带温度）
                perturbed = self._perturbed_kwargs(rng, prompt_dict["layer"])
                response = self._call(client_factory, prompt, perturbed)
                latency = time.time() - probe_start

                responses.append({
                    "prompt": prompt,
                    "response": response,
                    "layer": prompt_dict["layer"],
                    "latency": latency,
                })
                latencies.append(latency)

                if callback:
                    callback(i + 1, len(selected_prompts))

            except Exception as e:
                responses.append({
                    "prompt": prompt,
                    "response": "",
                    "error": str(e),
                    "layer": prompt_dict["layer"],
                })

        # 分析响应，识别家族
        family, confidence, details = self._analyze_responses(responses, model)

        elapsed = time.time() - start_time

        return {
            "family": family,
            "confidence": confidence,
            "claimed_family": self._detect_claimed_family(model),
            "match": family == self._detect_claimed_family(model),
            "probes_used": len(responses),
            "avg_latency_ms": int(sum(latencies) / len(latencies) * 1000) if latencies else 0,
            "elapsed_seconds": round(elapsed, 2),
            "details": details,
        }

    def _analyze_responses(
        self,
        responses: List[Dict],
        model: str
    ) -> Tuple[str, float, Dict]:
        """分析响应，判断模型家族"""

        claimed_family = self._detect_claimed_family(model)

        # 基于特征的投票
        votes = {family: 0 for family in self.MODEL_FAMILIES}
        features = {
            "avg_response_length": 0,
            "style_hints": [],
            "behavior_patterns": [],
        }

        total_length = 0
        valid_responses = 0

        for r in responses:
            response_text = r.get("response", "")
            if not response_text:
                continue

            valid_responses += 1
            total_length += len(response_text)
            response_lower = response_text.lower()

            # 检查每个家族的特征
            for family, sigs in self.FAMILY_SIGNATURES.items():
                # 正面特征
                for pattern in sigs.get("positive", []):
                    if pattern in response_lower:
                        votes[family] += 2

                # 负面特征（出现则减少该家族的可能性）
                for pattern in sigs.get("negative", []):
                    if pattern in response_lower:
                        votes[family] -= 1

        features["avg_response_length"] = total_length / valid_responses if valid_responses > 0 else 0

        # 获取最高票数的家族
        max_votes = max(votes.values())
        if max_votes == 0:
            # 没有任何特征，使用声称的家族
            detected_family = claimed_family
            confidence = 0.65
        else:
            # 找到票数最高的家族
            detected_family = max(votes.keys(), key=lambda k: votes[k])

            # 计算置信度
            total_votes = sum(max(0, v) for v in votes.values())
            if total_votes > 0:
                confidence = max_votes / (total_votes + 2)  # 平滑
            else:
                confidence = 0.5

        # 如果置信度太低，相信声称的家族
        if confidence < 0.5:
            detected_family = claimed_family
            confidence = 0.65

        details = {
            "votes": {k: v for k, v in votes.items() if v != 0},
            "features": features,
            "valid_responses": valid_responses,
        }

        return detected_family, min(confidence, 0.95), details

    def _detect_claimed_family(self, model: str) -> str:
        """从模型名称检测声称的家族"""
        model_lower = model.lower()

        if "claude" in model_lower:
            return "Claude"
        elif "gpt" in model_lower:
            return "GPT"
        elif "llama" in model_lower:
            return "LLaMA"
        elif "mistral" in model_lower:
            return "Mistral"
        elif "gemini" in model_lower:
            return "Gemini"
        elif "deepseek" in model_lower:
            return "DeepSeek"
        elif "qwen" in model_lower:
            return "Qwen"
        elif "command" in model_lower:
            return "Command"
        else:
            return "Unknown"

    def quick_check(self, response: str) -> Dict[str, Any]:
        """快速检查单个响应的特征"""
        response_lower = response.lower()

        result = {
            "family_hints": [],
            "suspicious": False,
            "reason": None,
        }

        # 检查各家族特征
        for family, sigs in self.FAMILY_SIGNATURES.items():
            for pattern in sigs.get("positive", []):
                if pattern in response_lower:
                    result["family_hints"].append(family)
                    break

        # 检查可疑特征
        suspicious_patterns = [
            "i am not able to",
            "as an ai language model",
            "i apologize, but i cannot",
        ]

        for pattern in suspicious_patterns:
            if pattern in response_lower:
                result["suspicious"] = True
                result["reason"] = "检测到拒绝模式"
                break

        return result
