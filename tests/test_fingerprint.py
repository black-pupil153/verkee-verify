"""指纹识别模块测试"""

from ai_verify.monitor.fingerprint import FingerprintDetector
from ai_verify.monitor.probes import get_probe_pool


def test_probe_pool_is_large_and_bilingual():
    pool = get_probe_pool()
    assert len(pool) >= 60
    texts = " ".join(p["text"] for p in pool)
    # 含中文与英文
    assert any("\u4e00" <= ch <= "\u9fff" for ch in texts)
    assert any(ch.isascii() and ch.isalpha() for ch in texts)


def test_probe_pool_has_no_redteam_phrases():
    pool = get_probe_pool()
    joined = " ".join(p["text"].lower() for p in pool)
    assert "system prompt" not in joined
    assert "word for word" not in joined


def test_detect_claimed_family():
    fp = FingerprintDetector()
    assert fp._detect_claimed_family("claude-sonnet-4.6") == "Claude"
    assert fp._detect_claimed_family("gpt-4o") == "GPT"
    assert fp._detect_claimed_family("qwen-max") == "Qwen"
    assert fp._detect_claimed_family("deepseek-chat") == "DeepSeek"


def test_identify_with_mock_client():
    fp = FingerprintDetector()

    def claude_like(prompt, **kwargs):
        return "I'd be happy to help you with that. Here's what I think."

    result = fp.identify(client_factory=claude_like, model="claude-sonnet-4.6", num_probes=5)
    assert result["family"] == "Claude"
    assert result["match"] is True
    assert result["probes_used"] == 5


def test_identify_tolerates_simple_client_signature():
    fp = FingerprintDetector()

    # 只接受单参数的 client，_call 应回退兼容
    def simple_client(prompt):
        return "some neutral answer"

    result = fp.identify(client_factory=simple_client, model="gpt-4", num_probes=3)
    assert result["probes_used"] == 3


def test_ml_optional_does_not_crash_without_dependency():
    # use_full=True 但未安装 llm_fingerprinter 时应静默回退
    fp = FingerprintDetector(use_full_fingerprinter=True)
    assert fp.llm_fp is None or fp.llm_fp is True
