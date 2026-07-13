"""盲测特征提取测试"""

import json

from ai_verify.blindtest.features import TurnRecord, extract_features


def _make_turn(**kwargs) -> TurnRecord:
    defaults = dict(conversation_id="conv-1", turn_index=0)
    defaults.update(kwargs)
    return TurnRecord(**defaults)


def test_extract_features_deterministic():
    turn = _make_turn(
        assistant_texts=["先读取文件，然后修改代码。\n- 第一步\n- 第二步"],
        tool_batches=[["Read", "Grep"], ["StrReplace"]],
        ttft_ms=1234.5,
    )
    f1 = extract_features(turn)
    f2 = extract_features(turn)
    assert f1 == f2
    assert all(isinstance(v, float) for v in f1.values())


def test_cjk_vs_latin_ratio():
    cjk = extract_features(_make_turn(assistant_texts=["这是一段纯中文的回复内容测试。"]))
    latin = extract_features(_make_turn(assistant_texts=["This is a pure English reply."]))
    assert cjk["txt_cjk_ratio"] > 0.8
    assert cjk["txt_latin_ratio"] < 0.1
    assert latin["txt_latin_ratio"] > 0.7
    assert latin["txt_cjk_ratio"] == 0.0


def test_list_vs_paragraph_structure():
    listy = extract_features(
        _make_turn(assistant_texts=["- item one\n- item two\n- item three\n- item four"])
    )
    para = extract_features(
        _make_turn(assistant_texts=["A single long paragraph without any list markers at all."])
    )
    assert listy["txt_bullet_line_ratio"] > 0.9
    assert para["txt_bullet_line_ratio"] == 0.0


def test_markdown_density():
    feats = extract_features(
        _make_turn(assistant_texts=["## Header\n**bold** text with `code`\n```\nfence\n```"])
    )
    assert feats["txt_header_line_ratio"] > 0
    assert feats["txt_bold_per_kb"] > 0
    assert feats["txt_inline_code_per_kb"] > 0
    assert feats["txt_fence_count"] == 2.0


def test_behavior_features():
    turn = _make_turn(
        assistant_texts=["text1", "text2"],
        tool_batches=[["Read", "Read", "Grep"], ["Shell"]],
        thinking_texts=["let me think about this"],
    )
    feats = extract_features(turn)
    assert feats["beh_max_batch_size"] == 3.0
    assert feats["beh_parallel_batch_ratio"] == 0.5
    assert feats["beh_distinct_tools"] == 3.0
    assert feats["beh_think_chars_log"] > 0

    no_tools = extract_features(_make_turn(assistant_texts=["hi"]))
    assert no_tools["beh_max_batch_size"] == 0.0


def test_latency_features():
    with_ttft = extract_features(_make_turn(assistant_texts=["x"], ttft_ms=2000.0))
    without = extract_features(_make_turn(assistant_texts=["x"]))
    assert with_ttft["lat_ttft_present"] == 1.0
    assert with_ttft["lat_ttft_log"] > 7
    assert "lat_ttft_present" not in without


def test_duration_and_out_chars_latency():
    turn = _make_turn(assistant_texts=["hello world"], duration_ms=3500.0)
    feats = extract_features(turn)
    assert feats["lat_duration_present"] == 1.0
    assert feats["lat_duration_log"] > 8
    assert feats["lat_out_chars_log"] > 0


def test_feature_channel_filter():
    from ai_verify.blindtest.features import (
        filter_features_by_channels,
        parse_channels,
    )

    turn = _make_turn(
        assistant_texts=["```\ndef foo():\n  return 1\n```\n- item"],
        tool_batches=[["Read"]],
        ttft_ms=1000.0,
        duration_ms=2000.0,
    )
    feats = extract_features(turn)
    text_only = filter_features_by_channels(feats, ["text"])
    assert all(k.startswith(("txt_", "ng3_", "open_")) for k in text_only)
    assert not any(k.startswith("lat_") for k in text_only)
    assert parse_channels(ablate=["latency"]) == ("text", "code", "behavior")


def test_empty_turn():
    feats = extract_features(_make_turn())
    assert feats["txt_chars_log"] == 0.0
    assert feats["beh_tools_total_log"] == 0.0


def test_code_style_features_hashed_not_raw():
    code = (
        "```python\n"
        "def fetch_user_data(user_id):\n"
        "    # load profile\n"
        "    return UserProfile(userId=user_id)\n"
        "```"
    )
    feats = extract_features(_make_turn(assistant_texts=[code]))
    assert feats["code_present"] == 1.0
    assert feats["code_chars_log"] > 0
    assert feats["code_snake_ratio"] > 0
    assert feats["code_comment_line_ratio"] > 0
    assert feats["txt_code_char_ratio"] > 0
    # Privacy: feature keys/values must not embed source identifiers or raw code.
    blob = json.dumps(feats)
    assert "fetch_user_data" not in blob
    assert "UserProfile" not in blob
    assert "load profile" not in blob
    assert any(k.startswith("code_id_h") for k in feats)


def test_code_style_deterministic():
    text = "```js\nfunction getUserName() {\n  return user_name;\n}\n```"
    t = _make_turn(assistant_texts=[text])
    assert extract_features(t) == extract_features(t)


def test_text_extra_features():
    feats = extract_features(
        _make_turn(assistant_texts=["这可能有问题？ Perhaps we should check."])
    )
    assert feats["txt_qmark_per_kb"] > 0
    assert feats["txt_hedge_per_kb"] > 0
