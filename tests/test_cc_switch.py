"""CC Switch 配置读取测试"""

from verkeep_verify.providers.cc_switch import (
    ProviderConfig,
    _extract_from_env,
    resolve_provider,
)


def test_extract_from_env_anthropic():
    env = {
        "ANTHROPIC_BASE_URL": "https://api.siliconflow.cn",
        "ANTHROPIC_AUTH_TOKEN": "sk-test-key-123456",
        "ANTHROPIC_MODEL": "Pro/zai-org/GLM-5",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "Pro/zai-org/GLM-5",
    }
    p = _extract_from_env(env, name="SiliconFlow", source="cc-switch", provider_id="abc")
    assert p is not None
    assert p.base_url == "https://api.siliconflow.cn"
    assert p.api_key == "sk-test-key-123456"
    assert p.model == "Pro/zai-org/GLM-5"
    assert p.extra_env is not None
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" in p.extra_env


def test_extract_requires_url_and_key():
    assert _extract_from_env({"ANTHROPIC_BASE_URL": "https://x"}, "a", "t") is None
    assert _extract_from_env({"ANTHROPIC_AUTH_TOKEN": "sk"}, "a", "t") is None


def test_masked_hides_key():
    p = ProviderConfig(
        name="x",
        base_url="https://x",
        api_key="sk-abcdefghijklmnop",
        source="t",
    )
    m = p.masked()
    assert "..." in m["api_key"]
    assert m["api_key"].startswith("sk-abc")


def test_resolve_provider_reads_local_cc_switch_if_present():
    # 本机若装了 CC Switch，应能读到；否则跳过
    p = resolve_provider(prefer="cc-switch")
    if p is None:
        return
    assert p.base_url
    assert p.api_key
    assert p.source == "cc-switch"
