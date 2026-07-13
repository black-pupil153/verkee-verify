"""
盲测 train/val/test 划分 registry + 密封标签。

约定：
- 按 conversation_id 划分，防止同会话 turn 泄漏到多折
- 默认 60/20/20，seed 可复现
- test 会话永不进入训练；训练进程不得读取密封标签文件
- 评估时再加载密封标签与预测比对
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from ai_verify.blindtest.corpus import (
    DEFAULT_BLINDTEST_DIR,
    Corpus,
    CorpusSample,
)

DEFAULT_RATIOS = (0.6, 0.2, 0.2)
DEFAULT_SPLIT_NAME = "default"
SPLITS_SUBDIR = "splits"


@dataclass
class SplitRegistry:
    name: str
    seed: int
    ratios: Tuple[float, float, float]
    train_ids: List[str]
    val_ids: List[str]
    test_ids: List[str]
    created_at: str
    n_conversations: int = 0
    notes: List[str] = field(default_factory=list)

    def ids_for(self, parts: Union[str, Sequence[str]]) -> Set[str]:
        if isinstance(parts, str):
            parts = [parts]
        out: Set[str] = set()
        for part in parts:
            key = part.lower()
            if key == "train":
                out.update(self.train_ids)
            elif key == "val":
                out.update(self.val_ids)
            elif key == "test":
                out.update(self.test_ids)
            else:
                raise ValueError(f"unknown split part: {part!r}")
        return out

    def part_of(self, conversation_id: str) -> Optional[str]:
        if conversation_id in self.train_ids:
            return "train"
        if conversation_id in self.val_ids:
            return "val"
        if conversation_id in self.test_ids:
            return "test"
        return None


@dataclass
class SealedLabel:
    conversation_id: str
    turn_index: int
    label: str
    label_source: Optional[str] = None
    request_id: Optional[str] = None


def splits_dir(blindtest_dir: Optional[Path] = None) -> Path:
    return (blindtest_dir or DEFAULT_BLINDTEST_DIR) / SPLITS_SUBDIR


def split_registry_path(
    name: str = DEFAULT_SPLIT_NAME, blindtest_dir: Optional[Path] = None
) -> Path:
    return splits_dir(blindtest_dir) / f"{name}.json"


def sealed_labels_path(
    name: str = DEFAULT_SPLIT_NAME, blindtest_dir: Optional[Path] = None
) -> Path:
    return splits_dir(blindtest_dir) / f"{name}.sealed.json"


def _primary_label(samples: Sequence[CorpusSample]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for s in samples:
        if not s.label:
            continue
        counts[s.label] = counts.get(s.label, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda x: x[1])[0]


def _assign_buckets(
    conversation_ids: Sequence[str],
    ratios: Tuple[float, float, float],
    rng: random.Random,
) -> Tuple[List[str], List[str], List[str]]:
    """将会话列表按比例划入 train/val/test（可复现）。"""
    ids = list(conversation_ids)
    rng.shuffle(ids)
    n = len(ids)
    if n == 0:
        return [], [], []
    if n == 1:
        return ids, [], []
    if n == 2:
        return [ids[0]], [ids[1]], []

    n_test = max(1, int(round(n * ratios[2])))
    n_val = max(1, int(round(n * ratios[1])))
    # 保证 train 至少 1
    while n_test + n_val >= n:
        if n_val > 1:
            n_val -= 1
        elif n_test > 1:
            n_test -= 1
        else:
            break
    n_train = n - n_val - n_test
    if n_train < 1:
        n_train = 1
        if n_val > 1:
            n_val -= 1
        elif n_test > 1:
            n_test -= 1

    train = ids[:n_train]
    val = ids[n_train : n_train + n_val]
    test = ids[n_train + n_val :]
    return train, val, test


def create_split(
    corpus: Corpus,
    *,
    name: str = DEFAULT_SPLIT_NAME,
    seed: int = 42,
    ratios: Tuple[float, float, float] = DEFAULT_RATIOS,
    labeled_only: bool = True,
) -> SplitRegistry:
    """按 conversation_id 创建可复现划分；尽量按主标签分层。"""
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError(f"ratios must sum to 1.0, got {ratios}")
    if any(r < 0 for r in ratios):
        raise ValueError(f"ratios must be non-negative, got {ratios}")

    by_conv: Dict[str, List[CorpusSample]] = {}
    for s in corpus.samples:
        if labeled_only and not s.label:
            continue
        by_conv.setdefault(s.conversation_id, []).append(s)

    if not by_conv:
        raise ValueError("no conversations available for split")

    # 分层：按会话主标签分桶，再在桶内按比例划分
    strata: Dict[str, List[str]] = {}
    for cid, samples in by_conv.items():
        key = _primary_label(samples) or "_unlabeled"
        strata.setdefault(key, []).append(cid)

    rng = random.Random(seed)
    train_ids: List[str] = []
    val_ids: List[str] = []
    test_ids: List[str] = []
    notes: List[str] = []

    for stratum, cids in sorted(strata.items()):
        t, v, te = _assign_buckets(cids, ratios, rng)
        train_ids.extend(t)
        val_ids.extend(v)
        test_ids.extend(te)
        if len(cids) < 3:
            notes.append(
                f"stratum {stratum}: {len(cids)} conv(s); "
                f"train={len(t)} val={len(v)} test={len(te)}"
            )

    train_ids = sorted(train_ids)
    val_ids = sorted(val_ids)
    test_ids = sorted(test_ids)

    # 硬约束：test ∩ train = ∅
    overlap = set(test_ids) & set(train_ids)
    if overlap:
        raise RuntimeError(f"test/train overlap: {sorted(overlap)[:5]}")
    overlap_v = set(test_ids) & set(val_ids)
    if overlap_v:
        raise RuntimeError(f"test/val overlap: {sorted(overlap_v)[:5]}")

    return SplitRegistry(
        name=name,
        seed=seed,
        ratios=ratios,
        train_ids=train_ids,
        val_ids=val_ids,
        test_ids=test_ids,
        created_at=datetime.now().isoformat(),
        n_conversations=len(by_conv),
        notes=notes,
    )


def extract_sealed_labels(
    corpus: Corpus, split: SplitRegistry
) -> List[SealedLabel]:
    """从语料提取 test 会话的标签（仅用于写密封文件 / 评估）。"""
    test_ids = set(split.test_ids)
    sealed: List[SealedLabel] = []
    for s in corpus.samples:
        if s.conversation_id not in test_ids or not s.label:
            continue
        sealed.append(
            SealedLabel(
                conversation_id=s.conversation_id,
                turn_index=s.turn_index,
                label=s.label,
                label_source=s.label_source,
                request_id=s.request_id,
            )
        )
    return sealed


def save_split(
    split: SplitRegistry,
    sealed: Sequence[SealedLabel],
    *,
    blindtest_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """落盘 registry + 密封标签。训练路径只应读 registry，不读 sealed。"""
    out = splits_dir(blindtest_dir)
    out.mkdir(parents=True, exist_ok=True)
    reg_path = split_registry_path(split.name, blindtest_dir)
    sealed_path = sealed_labels_path(split.name, blindtest_dir)

    payload = asdict(split)
    payload["ratios"] = list(split.ratios)
    reg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    sealed_payload = {
        "split_name": split.name,
        "sealed_at": datetime.now().isoformat(),
        "n_labels": len(sealed),
        "labels": [asdict(x) for x in sealed],
    }
    sealed_path.write_text(
        json.dumps(sealed_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return reg_path, sealed_path


def load_split(
    name: str = DEFAULT_SPLIT_NAME, blindtest_dir: Optional[Path] = None
) -> SplitRegistry:
    path = split_registry_path(name, blindtest_dir)
    if not path.is_file():
        raise FileNotFoundError(f"split registry not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ratios = payload.get("ratios", list(DEFAULT_RATIOS))
    return SplitRegistry(
        name=payload["name"],
        seed=int(payload["seed"]),
        ratios=(float(ratios[0]), float(ratios[1]), float(ratios[2])),
        train_ids=list(payload.get("train_ids", [])),
        val_ids=list(payload.get("val_ids", [])),
        test_ids=list(payload.get("test_ids", [])),
        created_at=payload.get("created_at", ""),
        n_conversations=int(payload.get("n_conversations", 0)),
        notes=list(payload.get("notes", [])),
    )


def load_sealed_labels(
    name: str = DEFAULT_SPLIT_NAME, blindtest_dir: Optional[Path] = None
) -> Dict[Tuple[str, int], SealedLabel]:
    """评估专用：加载密封标签。训练进程不应调用此函数。"""
    path = sealed_labels_path(name, blindtest_dir)
    if not path.is_file():
        raise FileNotFoundError(f"sealed labels not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[Tuple[str, int], SealedLabel] = {}
    for item in payload.get("labels", []):
        lab = SealedLabel(
            conversation_id=item["conversation_id"],
            turn_index=int(item["turn_index"]),
            label=item["label"],
            label_source=item.get("label_source"),
            request_id=item.get("request_id"),
        )
        out[(lab.conversation_id, lab.turn_index)] = lab
    return out


def filter_samples(
    samples: Iterable[CorpusSample],
    split: SplitRegistry,
    parts: Union[str, Sequence[str]],
    *,
    labeled_only: bool = True,
) -> List[CorpusSample]:
    ids = split.ids_for(parts)
    out = []
    for s in samples:
        if s.conversation_id not in ids:
            continue
        if labeled_only and not s.label:
            continue
        out.append(s)
    return out


def strip_test_labels(
    corpus: Corpus, split: SplitRegistry
) -> Corpus:
    """返回副本：test 会话样本的 label 置空（训练进程内存密封）。"""
    test_ids = set(split.test_ids)
    samples: List[CorpusSample] = []
    for s in corpus.samples:
        if s.conversation_id in test_ids:
            samples.append(
                CorpusSample(
                    conversation_id=s.conversation_id,
                    turn_index=s.turn_index,
                    request_id=s.request_id,
                    label=None,
                    label_source=None,
                    ttft_ms=s.ttft_ms,
                    features=dict(s.features),
                    duration_ms=s.duration_ms,
                )
            )
        else:
            samples.append(s)
    return Corpus(
        samples=samples,
        built_at=corpus.built_at,
        stats=dict(corpus.stats),
    )


def assert_no_test_labels(samples: Sequence[CorpusSample], split: SplitRegistry) -> None:
    """训练前硬检查：test 会话不得带标签。"""
    test_ids = set(split.test_ids)
    leaked = [
        (s.conversation_id, s.turn_index)
        for s in samples
        if s.conversation_id in test_ids and s.label
    ]
    if leaked:
        raise RuntimeError(
            f"sealed-label violation: {len(leaked)} test sample(s) still labeled "
            f"(e.g. {leaked[0]})"
        )
