"""
Auto 任务默认融合：在需要时写入 blindtest_inferences（不碰 resolved_model）。

隐私：只落 task/turn/request/model/probability 元数据；transcript 正文仅内存算特征。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from verkee_verify.blindtest.corpus import DEFAULT_BLINDTEST_DIR
from verkee_verify.storage.database import Database

DEFAULT_MODEL_PATH = DEFAULT_BLINDTEST_DIR / "model.json"


def _model_version(clf) -> str:
    return f"{getattr(clf, 'backend', 'unknown')}-v1"


def _has_pending_infer_events(db: Database, task_id: str) -> bool:
    """Mirror cursor_usage pending-infer bucket without importing that module."""
    events = db.get_cursor_events_for_task(task_id)
    if not events:
        return False
    for ev in events:
        resolved = ev.get("resolved_model")
        selected = ev.get("selected_model")
        if resolved and resolved not in ("", "default"):
            continue
        if selected and selected not in ("", "default"):
            continue
        if ev.get("route_kind") == "auto":
            return True
    return False

def ensure_task_inferences(
    db: Database,
    task_id: str,
    *,
    force: bool = False,
    model_path: Optional[Path] = None,
    projects_dir: Optional[Path] = None,
) -> int:
    """若训练模型存在且任务有 pending-infer，则运行盲测并写入推断表。

    Returns:
        写入/更新的 turn 数；跳过或失败时返回 0。
    """
    path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    if not path.is_file():
        return 0

    try:
        from verkee_verify.monitor.blindtest_view import get_inferred_view
        from verkee_verify.blindtest.classifier import BlindModelClassifier
        from verkee_verify.blindtest.corpus import load_turns_for_task
        from verkee_verify.blindtest.features import extract_features
    except ImportError:
        return 0

    try:
        clf = BlindModelClassifier.load(path)
    except Exception:
        return 0

    version = _model_version(clf)
    if not force:
        existing = get_inferred_view(db, task_id)
        if existing and existing.model_version == version:
            return 0
        if not _has_pending_infer_events(db, task_id):
            return 0

    try:
        turns = load_turns_for_task(task_id, projects_dir=projects_dir)
    except Exception:
        return 0
    if not turns:
        return 0

    full_task_id = turns[0].conversation_id
    # Align missing transcript request_ids to task events (timestamp order).
    event_rids = [
        e.get("request_id")
        for e in sorted(
            db.get_cursor_events_for_task(full_task_id),
            key=lambda x: x.get("timestamp") or "",
        )
        if e.get("request_id")
    ]
    for i, turn in enumerate(turns):
        if not turn.request_id and i < len(event_rids):
            turn.request_id = event_rids[i]

    written = 0
    for turn in turns:
        try:
            result = clf.predict_turn(extract_features(turn))
            db.save_blindtest_inference(
                {
                    "task_id": full_task_id,
                    "turn_index": turn.turn_index,
                    "request_id": turn.request_id,
                    "inferred_model": result.inferred_model,
                    "probability": result.probability,
                    "model_version": version,
                }
            )
            written += 1
        except Exception:
            continue
    return written
