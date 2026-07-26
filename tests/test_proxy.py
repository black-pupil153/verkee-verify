"""代理服务器测试（不依赖真实网络）"""

from verkee_verify.proxy.server import ProxyServer


def _server():
    return ProxyServer(target_url="https://api.example.com", api_key="sk-test")


def test_parse_sse_openai_stream():
    raw = (
        b'data: {"model":"gpt-4","choices":[{"delta":{"content":"Hello"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    content, model, usage = ProxyServer._parse_sse(raw)
    assert content == "Hello world"
    assert model == "gpt-4"


def test_parse_sse_anthropic_stream():
    raw = (
        b'data: {"type":"message_start","message":{"model":"claude-sonnet-4.6"}}\n\n'
        b'data: {"type":"content_block_delta","delta":{"text":"Hi"}}\n\n'
        b'data: {"type":"content_block_delta","delta":{"text":" there"}}\n\n'
    )
    content, model, usage = ProxyServer._parse_sse(raw)
    assert content == "Hi there"
    assert model == "claude-sonnet-4.6"


def test_extract_from_json_openai():
    data = {
        "model": "gpt-4",
        "choices": [{"message": {"content": "answer"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    content, model, usage = ProxyServer._extract_from_json(data)
    assert content == "answer"
    assert model == "gpt-4"
    assert usage["prompt_tokens"] == 5


def test_extract_from_json_anthropic():
    data = {
        "model": "claude-sonnet-4.6",
        "content": [{"text": "hello "}, {"text": "world"}],
    }
    content, model, _ = ProxyServer._extract_from_json(data)
    assert content == "hello world"
    assert model == "claude-sonnet-4.6"


def test_filter_headers_drops_hop_by_hop():
    headers = {
        "Content-Length": "10",
        "Transfer-Encoding": "chunked",
        "Content-Type": "application/json",
        "X-Custom": "keep",
    }
    filtered = ProxyServer._filter_headers(headers)
    assert "Content-Length" not in filtered
    assert "Transfer-Encoding" not in filtered
    assert filtered["Content-Type"] == "application/json"
    assert filtered["X-Custom"] == "keep"


def test_detect_anomalies_model_substitution():
    srv = _server()
    # gpt-4 vs gpt-3.5-turbo：家族同为 GPT，_check_model_match 会放行；
    # 用完全不同家族验证偷换检测
    anomalies = srv._detect_anomalies("gpt-4", "claude-sonnet-4.6", "ok response here", 100)
    types = [a[0] for a in anomalies]
    assert "model_substitution" in types


def test_detect_anomalies_short_response():
    srv = _server()
    anomalies = srv._detect_anomalies("gpt-4", "gpt-4", "", 100)
    types = [a[0] for a in anomalies]
    assert "short_response" in types


def test_detect_anomalies_high_latency():
    srv = _server()
    anomalies = srv._detect_anomalies("gpt-4", "gpt-4", "a normal answer", 999999)
    types = [a[0] for a in anomalies]
    assert "high_latency" in types
