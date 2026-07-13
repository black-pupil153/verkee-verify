"""盲测 Phase 1：split registry、密封标签、forced/selective 评估。"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from ai_verify.blindtest.classifier import BlindModelClassifier
from ai_verify.blindtest.corpus import Corpus, CorpusSample, exclude_conversations
from ai_verify.blindtest.eval import (
    evaluate_classifier,
    expected_calibration_error,
    new_run_dir,
    save_run_artifacts,
)
from ai_verify.blindtest.features import TurnRecord, extract_features
from ai_verify.blindtest.splits import (
    assert_no_test_labels,
    create_split,
    extract_sealed_labels,
    filter_samples,
    load_sealed_labels,
    load_split,
    save_split,
    strip_test_labels,
)

CN_WORDS = ["首先", "然后", "读取文件", "修改代码", "运行测试", "检查结果"]
EN_WORDS = ["first", "let's", "read the file", "update code", "run tests"]


def _make_turn_a(rng: random.Random, conv: str, idx: int) -> TurnRecord:
    lines = ["我来处理这个任务。"]
    for _ in range(rng.randint(3, 6)):
        lines.append(f"- {rng.choice(CN_WORDS)}{rng.choice(CN_WORDS)}。")
    batches = [["Read", "Grep"][: rng.randint(1, 2)] for _ in range(rng.randint(1, 3))]
    return TurnRecord(
        conversation_id=conv,
        turn_index=idx,
        assistant_texts=["\n".join(lines)],
        tool_batches=batches,
        ttft_ms=1000 + rng.random() * 500,
    )


def _make_turn_b(rng: random.Random, conv: str, idx: int) -> TurnRecord:
    sentences = [
        " ".join(rng.choice(EN_WORDS) for _ in range(rng.randint(6, 12))) + "."
        for _ in range(rng.randint(4, 8))
    ]
    batches = [["Shell"] for _ in range(rng.randint(0, 2))]
    return TurnRecord(
        conversation_id=conv,
        turn_index=idx,
        assistant_texts=[" ".join(sentences)],
        tool_batches=batches,
        ttft_ms=8000 + rng.random() * 3000,
    )


def _build_corpus(n_convs_per_class: int = 5, turns_per_conv: int = 4) -> Corpus:
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
    return Corpus(samples=samples, built_at="test", stats={"samples": len(samples)})


def test_create_split_no_train_test_overlap():
    corpus = _build_corpus()
    split = create_split(corpus, name="t1", seed=7, ratios=(0.6, 0.2, 0.2))
    assert set(split.train_ids).isdisjoint(split.test_ids)
    assert set(split.val_ids).isdisjoint(split.test_ids)
    assert set(split.train_ids).isdisjoint(split.val_ids)
    all_ids = set(split.train_ids) | set(split.val_ids) | set(split.test_ids)
    labeled_convs = {s.conversation_id for s in corpus.samples if s.label}
    assert all_ids == labeled_convs
    assert len(split.test_ids) >= 1
    assert len(split.train_ids) >= 1


def test_split_reproducible_with_seed():
    corpus = _build_corpus()
    a = create_split(corpus, name="r", seed=123)
    b = create_split(corpus, name="r", seed=123)
    assert a.train_ids == b.train_ids
    assert a.val_ids == b.val_ids
    assert a.test_ids == b.test_ids
    c = create_split(corpus, name="r", seed=999)
    assert (a.train_ids, a.test_ids) != (c.train_ids, c.test_ids)


def test_sealed_labels_roundtrip(tmp_path: Path):
    corpus = _build_corpus()
    split = create_split(corpus, name="seal", seed=42)
    sealed = extract_sealed_labels(corpus, split)
    assert sealed
    save_split(split, sealed, blindtest_dir=tmp_path)

    loaded = load_split("seal", blindtest_dir=tmp_path)
    assert loaded.test_ids == split.test_ids
    sealed_map = load_sealed_labels("seal", blindtest_dir=tmp_path)
    assert len(sealed_map) == len(sealed)
    for lab in sealed:
        assert sealed_map[(lab.conversation_id, lab.turn_index)].label == lab.label


def test_strip_test_labels_and_assert():
    corpus = _build_corpus()
    split = create_split(corpus, name="x", seed=1)
    open_c = strip_test_labels(corpus, split)
    for s in open_c.samples:
        if s.conversation_id in split.test_ids:
            assert s.label is None
        else:
            assert s.label is not None
    assert_no_test_labels(open_c.samples, split)
    with pytest.raises(RuntimeError, match="sealed-label"):
        assert_no_test_labels(corpus.samples, split)


def test_exclude_conversations():
    corpus = _build_corpus()
    ban = {"conv-a0", "conv-b0"}
    out = exclude_conversations(corpus, ban)
    assert all(s.conversation_id not in ban for s in out.samples)
    assert out.stats["excluded_conversations"] == 2


def test_train_with_split_never_sees_test_labels(tmp_path: Path):
    corpus = _build_corpus()
    split = create_split(corpus, name="tr", seed=42)
    sealed = extract_sealed_labels(corpus, split)
    save_split(split, sealed, blindtest_dir=tmp_path)

    open_c = strip_test_labels(corpus, split)
    clf = BlindModelClassifier(threshold=0.5)
    report = clf.train(open_c, split=split, split_name="tr")

    assert report.split_name == "tr"
    assert report.cv_accuracy is None  # 不以 LOCO 充当盲评
    assert report.n_train is not None and report.n_train > 0
    assert "T fit on val only" in " ".join(report.notes)
    # 训练样本不应包含 test 会话
    train_ids = {s.conversation_id for s in filter_samples(open_c.samples, split, "train")}
    assert train_ids.isdisjoint(set(split.test_ids))


def test_eval_forced_vs_selective(tmp_path: Path):
    corpus = _build_corpus()
    split = create_split(corpus, name="ev", seed=42)
    sealed_list = extract_sealed_labels(corpus, split)
    save_split(split, sealed_list, blindtest_dir=tmp_path)
    sealed = load_sealed_labels("ev", blindtest_dir=tmp_path)

    open_c = strip_test_labels(corpus, split)
    clf = BlindModelClassifier(threshold=0.99)  # 高阈值 → selective 大量弃权
    clf.train(open_c, split=split, split_name="ev")

    test_samples = filter_samples(open_c.samples, split, "test", labeled_only=False)
    test_samples = [
        s for s in test_samples if (s.conversation_id, s.turn_index) in sealed
    ]

    forced = evaluate_classifier(
        clf, test_samples, forced=True, sealed=sealed, split_name="ev"
    )
    selective = evaluate_classifier(
        clf, test_samples, forced=False, tau=0.99, sealed=sealed, split_name="ev"
    )
    sweep = evaluate_classifier(
        clf,
        test_samples,
        forced=False,
        tau=0.7,
        sweep=True,
        sealed=sealed,
        split_name="ev",
    )

    assert forced.mode == "forced"
    assert forced.coverage == 1.0
    assert forced.abstained == 0
    assert forced.accuracy is not None
    assert selective.mode == "selective"
    assert selective.abstained >= 0
    assert len(sweep.tau_sweep) == 5
    assert forced.confusion_matrix
    assert forced.macro_f1 is not None
    # ECE / Brier 在有预测时有值
    assert forced.ece is not None
    assert forced.brier is not None


def test_train_rejects_leaked_test_labels():
    corpus = _build_corpus()
    split = create_split(corpus, name="leak", seed=3)
    clf = BlindModelClassifier()
    # 未剥标签的语料传入 split 路径：classifier 内部会 strip，不应崩溃
    report = clf.train(corpus, split=split, split_name="leak")
    assert report.n_train is not None


def test_run_artifacts_no_prompt_text(tmp_path: Path, monkeypatch):
    from ai_verify.blindtest.splits import SealedLabel

    monkeypatch.setattr(
        "ai_verify.blindtest.eval.DEFAULT_BLINDTEST_DIR", tmp_path
    )
    corpus = _build_corpus()
    split = create_split(corpus, name="run", seed=1)
    open_c = strip_test_labels(corpus, split)
    clf = BlindModelClassifier(threshold=0.5)
    train_report = clf.train(open_c, split=split, split_name="run")

    sealed = {
        (s.conversation_id, s.turn_index): SealedLabel(
            conversation_id=s.conversation_id,
            turn_index=s.turn_index,
            label=s.label,
        )
        for s in corpus.samples
        if s.conversation_id in split.test_ids and s.label
    }
    test_samples = filter_samples(open_c.samples, split, "test", labeled_only=False)
    eval_report = evaluate_classifier(
        clf, test_samples, forced=True, sealed=sealed, split_name="run"
    )

    run_dir = new_run_dir(blindtest_dir=tmp_path)
    save_run_artifacts(
        run_dir, train_report=train_report, eval_reports=[eval_report], meta={"k": 1}
    )
    blob = (run_dir / "train_report.json").read_text(encoding="utf-8")
    blob += (run_dir / "eval_report.json").read_text(encoding="utf-8")
    assert "assistant_texts" not in blob
    assert "我来处理这个任务" not in blob
    assert json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))["k"] == 1


def test_ece_basic():
    confs = [0.9, 0.9, 0.1, 0.1]
    hits = [True, True, False, False]
    ece = expected_calibration_error(confs, hits, n_bins=2)
    assert ece is not None
    assert abs(ece - 0.1) < 1e-9  # |1.0-0.9|*0.5 + |0.0-0.1|*0.5

    # 单 bin：avg_conf == avg_acc → ECE = 0
    perfect = expected_calibration_error([0.5, 0.5], [True, False], n_bins=1)
    assert perfect is not None
    assert abs(perfect) < 1e-9
