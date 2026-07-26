"""盲测 inventory：APP-12 扩量缺口盘点。"""

from __future__ import annotations

from verkee_verify.blindtest.corpus import Corpus, CorpusSample
from verkee_verify.blindtest.inventory import DEFAULT_EXPAND_TARGETS, build_inventory
from verkee_verify.blindtest.splits import SplitRegistry, create_split


def _sample(cid: str, label: str, turn: int = 0) -> CorpusSample:
    return CorpusSample(
        conversation_id=cid,
        turn_index=turn,
        request_id=None,
        label=label,
        label_source="hook",
        ttft_ms=None,
        features={"text_len": 10.0},
    )


def test_build_inventory_reports_long_and_target_gaps():
    samples = []
    # composer: 2 short convs only
    for i in range(2):
        samples.append(_sample(f"composer-{i}", "composer-2.5-fast", 0))
    # sol: 1 long (>=5) + 1 short
    for t in range(5):
        samples.append(_sample("sol-long", "gpt-5.6-sol-medium", t))
    samples.append(_sample("sol-short", "gpt-5.6-sol-medium", 0))
    # terra: none
    # grok filler
    for t in range(3):
        samples.append(_sample("grok-1", "grok-4.5", t))

    corpus = Corpus(samples=samples, built_at="t", stats={})
    report = build_inventory(corpus, long_min_turns=5, target_long_per_class=5)

    by = {c.label: c for c in report.classes}
    assert by["composer-2.5-fast"].conversations == 2
    assert by["composer-2.5-fast"].long_conversations == 0
    assert by["gpt-5.6-sol-medium"].long_conversations == 1
    assert by["gpt-5.6-sol-medium"].samples == 6
    assert "gpt-5.6-terra-medium" not in by or by["gpt-5.6-terra-medium"].samples == 0

    gap_text = "\n".join(report.gaps)
    assert "composer-2.5-fast: need 5 more long conversations" in gap_text
    assert "gpt-5.6-sol-medium: need 4 more long conversations" in gap_text
    assert "gpt-5.6-terra-medium: need 5 more long conversations" in gap_text
    assert "n_test=0 < target 30" in gap_text
    assert report.to_dict()["ready"] is False
    assert list(DEFAULT_EXPAND_TARGETS) == report.expand_targets


def test_build_inventory_with_split_counts_test_coverage():
    samples = []
    for model, prefix, n_conv in (
        ("composer-2.5-fast", "c", 6),
        ("gpt-5.6-sol-medium", "s", 6),
        ("gpt-5.6-terra-medium", "t", 6),
    ):
        for i in range(n_conv):
            # 2 turns each so samples accumulate toward n_test
            samples.append(_sample(f"{prefix}{i}", model, 0))
            samples.append(_sample(f"{prefix}{i}", model, 1))

    corpus = Corpus(samples=samples, built_at="t", stats={})
    split = create_split(corpus, name="probe", seed=42, ratios=(0.5, 0.2, 0.3))
    report = build_inventory(
        corpus,
        split=split,
        long_min_turns=5,
        target_long_per_class=5,
        target_test_convs_per_class=3,
        target_n_test=30,
    )

    assert report.split_name == "probe"
    assert report.n_test == sum(c.test_samples for c in report.classes)
    assert report.n_test > 0
    # Still gaps: no long sessions and likely n_test < 30
    assert any("long conversations" in g for g in report.gaps)
    payload = report.to_dict()
    assert "classes" in payload
    assert payload["n_test"] == report.n_test
