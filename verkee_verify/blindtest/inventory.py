"""
盲测语料盘点 — 对照 APP-12 / Cheap GT 扩量目标报告缺口。

不读取 prompt/response 正文；只汇总样本数、会话数与长会话计数。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from verkee_verify.blindtest.corpus import Corpus, CorpusSample
from verkee_verify.blindtest.splits import SplitRegistry, _primary_label

# APP-12 优先扩量的便宜类（不含 fable；路线图要求不继续消耗 fable）
DEFAULT_EXPAND_TARGETS = (
    "composer-2.5-fast",
    "gpt-5.6-sol-medium",
    "gpt-5.6-terra-medium",
)


@dataclass
class ClassInventory:
    label: str
    samples: int = 0
    conversations: int = 0
    long_conversations: int = 0
    turn_counts: List[int] = field(default_factory=list)
    label_sources: Dict[str, int] = field(default_factory=dict)
    test_samples: int = 0
    test_conversations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InventoryReport:
    n_samples: int
    n_conversations: int
    n_labeled: int
    long_min_turns: int
    classes: List[ClassInventory]
    label_sources: Dict[str, int]
    expand_targets: List[str]
    target_long_per_class: int
    target_test_convs_per_class: int
    target_n_test: int
    split_name: Optional[str] = None
    n_test: int = 0
    gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "n_conversations": self.n_conversations,
            "n_labeled": self.n_labeled,
            "long_min_turns": self.long_min_turns,
            "classes": [c.to_dict() for c in self.classes],
            "label_sources": self.label_sources,
            "expand_targets": self.expand_targets,
            "target_long_per_class": self.target_long_per_class,
            "target_test_convs_per_class": self.target_test_convs_per_class,
            "target_n_test": self.target_n_test,
            "split_name": self.split_name,
            "n_test": self.n_test,
            "gaps": self.gaps,
            "ready": not self.gaps,
        }


def _conversation_map(
    samples: Sequence[CorpusSample], *, labeled_only: bool = True
) -> Dict[str, List[CorpusSample]]:
    by_conv: Dict[str, List[CorpusSample]] = {}
    for s in samples:
        if labeled_only and not s.label:
            continue
        by_conv.setdefault(s.conversation_id, []).append(s)
    return by_conv


def build_inventory(
    corpus: Corpus,
    *,
    split: Optional[SplitRegistry] = None,
    expand_targets: Optional[Sequence[str]] = None,
    long_min_turns: int = 5,
    target_long_per_class: int = 5,
    target_test_convs_per_class: int = 3,
    target_n_test: int = 30,
) -> InventoryReport:
    """汇总语料与可选 split，对照扩量验收目标列出缺口。"""
    targets = list(expand_targets or DEFAULT_EXPAND_TARGETS)
    by_conv = _conversation_map(corpus.samples, labeled_only=True)
    source_total: Counter[str] = Counter()

    test_ids: Set[str] = set(split.test_ids) if split is not None else set()

    class_map: Dict[str, ClassInventory] = {}
    for cid, samples in by_conv.items():
        label = _primary_label(samples) or "_unlabeled"
        inv = class_map.setdefault(label, ClassInventory(label=label))
        inv.samples += len(samples)
        inv.conversations += 1
        turns = len(samples)
        inv.turn_counts.append(turns)
        if turns >= long_min_turns:
            inv.long_conversations += 1
        src_counts: Counter[str] = Counter(
            s.label_source for s in samples if s.label_source
        )
        for src, n in src_counts.items():
            inv.label_sources[src] = inv.label_sources.get(src, 0) + n
            source_total[src] += n
        if cid in test_ids:
            inv.test_conversations += 1
            inv.test_samples += len(samples)

    for inv in class_map.values():
        inv.turn_counts = sorted(inv.turn_counts, reverse=True)

    classes = sorted(
        class_map.values(), key=lambda c: (-c.samples, c.label)
    )

    n_test = sum(c.test_samples for c in classes)
    gaps: List[str] = []
    for label in targets:
        inv = class_map.get(label) or ClassInventory(label=label)
        need_long = max(0, target_long_per_class - inv.long_conversations)
        if need_long:
            gaps.append(
                f"{label}: need {need_long} more long conversations "
                f"(≥{long_min_turns} turns; have {inv.long_conversations})"
            )
        if split is not None:
            need_test = max(0, target_test_convs_per_class - inv.test_conversations)
            if need_test:
                gaps.append(
                    f"{label}: need {need_test} more test conversations "
                    f"(have {inv.test_conversations})"
                )

    if n_test < target_n_test:
        gaps.append(f"n_test={n_test} < target {target_n_test}")

    return InventoryReport(
        n_samples=len(corpus.samples),
        n_conversations=len(by_conv),
        n_labeled=sum(1 for s in corpus.samples if s.label),
        long_min_turns=long_min_turns,
        classes=classes,
        label_sources=dict(source_total),
        expand_targets=targets,
        target_long_per_class=target_long_per_class,
        target_test_convs_per_class=target_test_convs_per_class,
        target_n_test=target_n_test,
        split_name=split.name if split else None,
        n_test=n_test,
        gaps=gaps,
    )
