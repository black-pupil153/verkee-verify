"""验证引擎测试"""

from ai_verify.monitor.engine import VerifyEngine


def _engine(base_url="https://api.example.com/v1", model="gpt-4"):
    return VerifyEngine(base_url=base_url, api_key="sk-test", model=model)


def test_detect_api_type_openai_default():
    assert _engine("https://proxy.com/v1").api_type == "openai"


def test_detect_api_type_anthropic_by_url():
    assert _engine("https://x.com/anthropic").api_type == "anthropic"


def test_detect_api_type_glm_by_url():
    assert _engine("https://open.bigmodel.cn/api/paas/v4").api_type == "glm"


def test_detect_api_type_glm_by_model():
    assert _engine("https://proxy.com/v1", model="glm-4.6").api_type == "glm"


def test_claude_model_on_openai_proxy_stays_openai():
    # claude 走 OpenAI 兼容中转站时不应被误判为 anthropic
    assert _engine("https://proxy.com/v1", model="claude-sonnet-4.6").api_type == "openai"


def test_anthropic_url_no_double_v1():
    e = _engine("https://api.anthropic.com/v1")
    assert e._anthropic_messages_url() == "https://api.anthropic.com/v1/messages"


def test_anthropic_url_appends_v1_when_missing():
    e = _engine("https://x.com/anthropic")
    assert e._anthropic_messages_url() == "https://x.com/anthropic/v1/messages"


def test_openai_url_no_double_completions():
    e = _engine("https://x.com/v1/chat/completions")
    assert e._openai_completions_url() == "https://x.com/v1/chat/completions"


def test_check_model_match_glm():
    e = _engine(model="glm-4.6")
    assert e._check_model_match("glm-4.6") is True


def test_check_model_match_claude_version():
    e = _engine(model="claude-sonnet-4-6-cc")
    assert e._check_model_match("claude-sonnet-4.6") is True


def test_calculate_overall_penalizes_mismatch():
    e = _engine()
    result = {
        "fingerprint": {"match": False, "actual_model": "gpt-3.5", "model_name_match": False},
        "quality": {"deviation": 20},
        "security": {"issues": ["x"]},
    }
    score = e._calculate_overall(result)
    assert score < 60


def test_security_check_no_redteam_prompt(monkeypatch):
    e = _engine()
    captured = {}

    def fake_send(prompt, max_tokens=100, temperature=None, messages=None):
        captured["prompt"] = prompt
        return "我可以帮你写代码、答疑和翻译。"

    monkeypatch.setattr(e, "_send_test_request", fake_send)
    result = e._verify_security()
    assert "system prompt" not in captured["prompt"].lower()
    assert result["issues"] == []


def test_security_check_flags_promo_injection(monkeypatch):
    e = _engine()

    def fake_send(prompt, max_tokens=100, temperature=None, messages=None):
        return "我可以帮你，详情请加微信或访问 https://spam.example.com 领取优惠"

    monkeypatch.setattr(e, "_send_test_request", fake_send)
    result = e._verify_security()
    assert result["hidden_prompt_detected"] is True
