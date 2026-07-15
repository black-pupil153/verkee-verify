"""盲测分类器测试 — 合成两种风格迥异的假模型"""

import random

import pytest

from ai_verify.blindtest.classifier import (
    BlindModelClassifier,
    InferenceResult,
    TrainReport,
)
from ai_verify.blindtest.corpus import CorpusSample
from ai_verify.blindtest.features import TurnRecord, extract_features

CN_WORDS = ["首先", "然后", "读取文件", "修改代码", "运行测试", "检查结果", "这个函数", "需要注意"]
EN_WORDS = ["first", "let's", "read the file", "update code", "run tests", "check output", "this function"]


def _make_turn_a(rng: random.Random, conv: str, idx: int) -> TurnRecord:
    """假模型 A：中文、重列表、并行工具调用多、ttft 快。"""
    lines = ["我来处理这个任务。"]
    for _ in range(rng.randint(3, 6)):
        lines.append(f"- {rng.choice(CN_WORDS)}{rng.choice(CN_WORDS)}，{rng.choice(CN_WORDS)}。")
    n_batches = rng.randint(1, 3)
    batches = [["Read", "Grep", "Glob"][: rng.randint(2, 3)] for _ in range(n_batches)]
    return TurnRecord(
        conversation_id=conv,
        turn_index=idx,
        assistant_texts=["\n".join(lines)],
        tool_batches=batches,
        ttft_ms=1000 + rng.random() * 500,
    )


def _make_turn_b(rng: random.Random, conv: str, idx: int) -> TurnRecord:
    """假模型 B：英文长段落、无列表、串行单工具、ttft 慢。"""
    sentences = []
    for _ in range(rng.randint(4, 8)):
        sentences.append(
            " ".join(rng.choice(EN_WORDS) for _ in range(rng.randint(6, 12))) + "."
        )
    batches = [["Shell"] for _ in range(rng.randint(0, 2))]
    return TurnRecord(
        conversation_id=conv,
        turn_index=idx,
        assistant_texts=[" ".join(sentences)],
        tool_batches=batches,
        ttft_ms=8000 + rng.random() * 3000,
    )


def _build_synthetic_corpus(n_convs_per_class: int = 4, turns_per_conv: int = 5):
    rng = random.Random(42)
    samples = []
    for c in range(n_convs_per_class):
        for i in range(turns_per_conv):
            turn = _make_turn_a(rng, f"conv-a{c}", i)
            samples.append(
                CorpusSample(
                    conversation_id=turn.conversation_id,
                    turn_index=i,
                    request_id=None,
                    label="model-alpha",
                    label_source="test",
                    ttft_ms=turn.ttft_ms,
                    features=extract_features(turn),
                )
            )
            turn = _make_turn_b(rng, f"conv-b{c}", i)
            samples.append(
                CorpusSample(
                    conversation_id=turn.conversation_id,
                    turn_index=i,
                    request_id=None,
                    label="model-beta",
                    label_source="test",
                    ttft_ms=turn.ttft_ms,
                    features=extract_features(turn),
                )
            )
    return samples


def test_classifier_separates_two_styles():
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    report = clf.train(samples)

    assert isinstance(report, TrainReport)
    assert report.class_counts == {"model-alpha": 20, "model-beta": 20}
    assert report.cv_accuracy is not None
    assert report.cv_accuracy >= 0.9
    assert report.n_conversations == 8

    rng = random.Random(7)
    res_a = clf.predict_turn(extract_features(_make_turn_a(rng, "new-a", 0)))
    res_b = clf.predict_turn(extract_features(_make_turn_b(rng, "new-b", 0)))
    assert res_a.inferred_model == "model-alpha"
    assert res_b.inferred_model == "model-beta"
    assert res_a.probability >= 0.7
    assert res_b.probability >= 0.7


def test_threshold_produces_none():
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    clf.train(samples)
    rng = random.Random(3)
    feats = extract_features(_make_turn_a(rng, "x", 0))
    res = clf.predict_turn(feats)
    assert res.inferred_model == "model-alpha"

    # 阈值抬高到刚好超过实际概率 → 必须输出 None
    clf.threshold = min(res.probability + 1e-6, 1.0 + 1e-6)
    res2 = clf.predict_turn(feats)
    assert res2.inferred_model is None
    assert res2.probability == res.probability
    assert len(res2.top_candidates) == 2


def test_predict_accepts_turn_record():
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    clf.train(samples)
    rng = random.Random(9)
    res = clf.predict_turn(_make_turn_a(rng, "x", 0))
    assert isinstance(res, InferenceResult)
    assert res.features_used > 0


def test_save_load_roundtrip(tmp_path):
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    clf.train(samples)
    path = tmp_path / "model.json"
    clf.save(path)

    loaded = BlindModelClassifier.load(path)
    assert loaded.classes == clf.classes
    assert loaded.temperature == clf.temperature

    rng = random.Random(11)
    feats = extract_features(_make_turn_b(rng, "x", 0))
    r1 = clf.predict_turn(feats)
    r2 = loaded.predict_turn(feats)
    assert r1.inferred_model == r2.inferred_model
    assert abs(r1.probability - r2.probability) < 1e-9


def test_train_rejects_single_class():
    samples = [s for s in _build_synthetic_corpus() if s.label == "model-alpha"]
    clf = BlindModelClassifier()
    with pytest.raises(ValueError, match="2 classes"):
        clf.train(samples)


def test_train_rejects_tiny_corpus():
    samples = _build_synthetic_corpus()[:2]
    clf = BlindModelClassifier()
    with pytest.raises(ValueError, match="too few"):
        clf.train(samples)


def test_pure_python_nb_fallback(monkeypatch):
    """强制 sklearn 不可用，验证纯 Python NB 后备可用。"""
    import ai_verify.blindtest.classifier as mod

    monkeypatch.setattr(mod, "_sklearn_available", lambda: False)
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    report = clf.train(samples)
    assert report.backend == "gaussian_nb"
    assert report.cv_accuracy is not None
    assert report.cv_accuracy >= 0.8

    rng = random.Random(5)
    res = clf.predict_turn(extract_features(_make_turn_a(rng, "x", 0)))
    assert res.inferred_model == "model-alpha"


def test_calibration_probability_range():
    """校准后的概率应该在合法范围且 top 候选按概率降序。"""
    samples = _build_synthetic_corpus()
    clf = BlindModelClassifier()
    clf.train(samples)
    rng = random.Random(13)
    res = clf.predict_turn(extract_features(_make_turn_b(rng, "x", 0)))
    probs = [p for _, p in res.top_candidates]
    assert probs == sorted(probs, reverse=True)
    assert abs(sum(probs) - 1.0) < 1e-3
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_near_pair_gate_abstains_on_small_margin():
    from ai_verify.blindtest.classifier import (
        ABSTAIN_NEAR_MARGIN,
        ABSTAIN_THRESHOLD,
        near_pair_margin_too_small,
        near_pair_swap_stats,
        select_inferred_model,
    )

    sol = "gpt-5.6-sol-medium"
    terra = "gpt-5.6-terra-medium"
    ranked_close = [(sol, 0.42), (terra, 0.40), ("grok-4.5", 0.18)]
    ranked_wide = [(sol, 0.55), (terra, 0.30), ("grok-4.5", 0.15)]

    assert near_pair_margin_too_small(ranked_close, near_margin=0.12)
    assert not near_pair_margin_too_small(ranked_wide, near_margin=0.12)

    inferred, reason = select_inferred_model(
        ranked_close, threshold=0.3, near_margin=0.12
    )
    assert inferred is None
    assert reason == ABSTAIN_NEAR_MARGIN

    inferred2, reason2 = select_inferred_model(
        ranked_wide, threshold=0.3, near_margin=0.12
    )
    assert inferred2 == sol
    assert reason2 is None

    # 大 margin 但低于 τ → threshold 弃权
    inferred3, reason3 = select_inferred_model(
        ranked_wide, threshold=0.7, near_margin=0.12
    )
    assert inferred3 is None
    assert reason3 == ABSTAIN_THRESHOLD

    # forced 忽略门控
    forced, fr = select_inferred_model(
        ranked_close, threshold=0.7, near_margin=0.12, forced=True
    )
    assert forced == sol and fr is None

    stats = near_pair_swap_stats(
        [sol, terra, sol, "grok-4.5"],
        [terra, terra, sol, "grok-4.5"],
    )
    assert stats["near_pair_n"] == 3
    assert stats["near_pair_swaps"] == 1
    assert abs(stats["near_pair_swap_rate"] - 1 / 3) < 1e-9

    # composer 同时属于多对：→terra 仍算近亲 swap
    composer = "composer-2.5-fast"
    multi = near_pair_swap_stats([composer, composer], [sol, terra])
    assert multi["near_pair_n"] == 2
    assert multi["near_pair_swaps"] == 2


def test_predict_turn_near_gate_and_persist(tmp_path):
    from ai_verify.blindtest.classifier import ABSTAIN_NEAR_MARGIN

    samples = _build_synthetic_corpus()
    # 把合成类名映射成近亲对，便于门控命中
    for s in samples:
        s.label = (
            "gpt-5.6-sol-medium"
            if s.label == "model-alpha"
            else "gpt-5.6-terra-medium"
        )
    clf = BlindModelClassifier(threshold=0.01, near_margin=0.12)
    clf.train(samples)

    # 人为构造接近的 top2：直接改 _predict_proba
    orig = clf._predict_proba

    def close_probs(_vec):
        # classes order after train is sorted
        out = [0.0] * len(clf.classes)
        i_sol = clf.classes.index("gpt-5.6-sol-medium")
        i_terra = clf.classes.index("gpt-5.6-terra-medium")
        out[i_sol] = 0.41
        out[i_terra] = 0.39
        # leftover on any remaining class
        for i in range(len(out)):
            if out[i] == 0.0:
                out[i] = 0.20 / max(1, len(out) - 2)
                break
        return out

    clf._predict_proba = close_probs  # type: ignore[method-assign]
    rng = random.Random(1)
    res = clf.predict_turn(extract_features(_make_turn_a(rng, "x", 0)))
    assert res.inferred_model is None
    assert res.abstain_reason == ABSTAIN_NEAR_MARGIN
    assert res.probability == 0.41

    clf._predict_proba = orig  # type: ignore[method-assign]
    path = tmp_path / "model.json"
    clf.near_margin = 0.15
    clf.save(path)
    loaded = BlindModelClassifier.load(path)
    assert loaded.near_margin == 0.15

