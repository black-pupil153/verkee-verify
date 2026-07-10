"""
盲测推断视图 — 独立于 TaskUsageReport，绝不污染事实占比。

设计原则：
- 只读 blindtest_inferences 表，不运行在线推断
- 过滤到最新 model_version（按 created_at 排序取最大）
- 输出 InferredView，与 TaskUsageReport 完全解耦
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_verify.storage.database import Database


@dataclass
class PerTurnInference:
    turn_index: int
    inferred_model: Optional[str]  # None = abstained (below threshold)
    probability: float
    top_candidates: List[Any] = field(default_factory=list)
    request_id: Optional[str] = None


@dataclass
class InferredView:
    """盲测推断独立视图 — 不混入 TaskUsageReport。"""

    task_id: str
    per_turn: List[PerTurnInference] = field(default_factory=list)
    # 仅统计 inferred_model 非 None 的 turns
    inferred_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    abstained: int = 0  # inferred_model=None 的 turn 数
    model_version: Optional[str] = None
    trained_at: Optional[str] = None  # 当前版本最新 created_at


def _latest_model_version(rows: List[Dict[str, Any]]) -> Optional[str]:
    """找出 created_at 最新的 model_version。"""
    if not rows:
        return None
    by_version: Dict[str, str] = {}
    for row in rows:
        mv = row.get("model_version") or ""
        ca = str(row.get("created_at") or "")
        prev = by_version.get(mv, "")
        if ca > prev:
            by_version[mv] = ca
    if not by_version:
        return None
    # 返回拥有最大 created_at 的 model_version
    return max(by_version.items(), key=lambda x: x[1])[0]


def get_inferred_view(db: Database, task_id: str) -> Optional[InferredView]:
    """
    从 blindtest_inferences 加载最新版本的推断结果，构建独立视图。

    - 做 prefix match（DB 层已处理）
    - 过滤到 latest model_version（created_at 最大者）
    - 返回 None 表示无任何推断记录
    """
    rows = db.get_blindtest_inferences(task_id)
    if not rows:
        return None

    # 解析真实 task_id（DB prefix match 可能返回多个 task，取第一行）
    real_task_id = rows[0].get("task_id", task_id)

    latest_version = _latest_model_version(rows)
    if not latest_version:
        return None

    filtered = [r for r in rows if (r.get("model_version") or "") == latest_version]

    # 排序 by turn_index
    filtered.sort(key=lambda r: int(r.get("turn_index") or 0))

    per_turn: List[PerTurnInference] = []
    model_counts: Dict[str, int] = defaultdict(int)
    abstained = 0
    latest_created_at: Optional[str] = None

    for row in filtered:
        turn_idx = int(row.get("turn_index") or 0)
        inferred = row.get("inferred_model")
        prob = float(row.get("probability") or 0.0)
        rid = row.get("request_id")
        ca = str(row.get("created_at") or "")
        if latest_created_at is None or ca > latest_created_at:
            latest_created_at = ca

        per_turn.append(
            PerTurnInference(
                turn_index=turn_idx,
                inferred_model=inferred,
                probability=prob,
                request_id=rid,
            )
        )
        if inferred:
            model_counts[inferred] += 1
        else:
            abstained += 1

    total_decided = sum(model_counts.values()) or 1
    inferred_shares = {
        m: {"pct": c / total_decided * 100, "count": c}
        for m, c in sorted(model_counts.items(), key=lambda x: -x[1])
    }

    return InferredView(
        task_id=real_task_id,
        per_turn=per_turn,
        inferred_shares=inferred_shares,
        abstained=abstained,
        model_version=latest_version,
        trained_at=latest_created_at,
    )
