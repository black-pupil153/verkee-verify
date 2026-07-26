"""
盲测推断视图测试

覆盖：
- get_inferred_view 基本行为
- 双版本过滤（取最新 model_version）
- 推断占比计算、abstained 计数
- 事实 output_shares 不受推断记录影响
- CLI cursor task --inferred smoke test
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from verkee_verify.cli import cursor_task
from verkee_verify.monitor.blindtest_view import InferredView, get_inferred_view
from verkee_verify.monitor.cursor_usage import aggregate_task
from verkee_verify.storage.database import Database


# ─── helpers ────────────────────────────────────────────────────────────────


def _seed_inferences(db: Database, task_id: str, rows: list[dict]) -> None:
    """直接写入 blindtest_inferences。"""
    import sqlite3

    with sqlite3.connect(db.db_path) as conn:
        for row in rows:
            conn.execute(
                """
                INSERT INTO blindtest_inferences
                    (task_id, turn_index, request_id, inferred_model,
                     probability, model_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, turn_index, model_version) DO UPDATE SET
                    request_id=excluded.request_id,
                    inferred_model=excluded.inferred_model,
                    probability=excluded.probability,
                    created_at=excluded.created_at
                """,
                (
                    row["task_id"],
                    row.get("turn_index", 0),
                    row.get("request_id"),
                    row.get("inferred_model"),
                    row.get("probability", 0.9),
                    row["model_version"],
                    row.get("created_at", "2026-01-01T00:00:00"),
                ),
            )
        conn.commit()


def _seed_factual_events(db: Database, task_id: str) -> None:
    """注入一些事实 cursor_model_events（无 resolved_model = auto-opaque）。"""
    db.save_cursor_task(
        {
            "task_id": task_id,
            "title": "test task",
            "mode": "agent",
            "route_kind": "auto",
            "started_at": "2026-07-01T10:00:00",
            "request_count": 2,
            "code_unit_count": 100,
            "subagent_count": 0,
        }
    )
    for i, rid in enumerate(["req-a", "req-b"]):
        db.save_cursor_model_event(
            {
                "id": f"ev-{i}",
                "task_id": task_id,
                "request_id": rid,
                "selected_model": "default",
                "resolved_model": None,
                "route_kind": "auto",
                "event_source": "structured_log",
                "confidence": "low",
                "generated_units": 50,
                "status": "success",
                "timestamp": f"2026-07-01T10:0{i}:00",
            }
        )


# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return Database(db_path=tmp_path / "ai_verify.db")


TASK_ID = "469c3074-aaaa-bbbb-cccc-000000000000"
SHORT_TASK = "469c3074"

STALE_VERSION = "vsklearn_lr"
CURRENT_VERSION = "sklearn_lr-v1"


# ─── tests ───────────────────────────────────────────────────────────────────


def test_no_inferences_returns_none(db):
    assert get_inferred_view(db, TASK_ID) is None
    assert get_inferred_view(db, SHORT_TASK) is None


def test_basic_inferred_view(db):
    """Single-version: shares and abstained computed correctly."""
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "claude-fable-5",
                "probability": 0.92,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:00",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 1,
                "inferred_model": "grok-4.5",
                "probability": 0.85,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:01",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 2,
                "inferred_model": None,  # abstained
                "probability": 0.60,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:02",
            },
        ],
    )

    view = get_inferred_view(db, TASK_ID)
    assert view is not None
    assert isinstance(view, InferredView)
    assert view.model_version == CURRENT_VERSION
    assert view.abstained == 1
    assert len(view.per_turn) == 3

    # shares only over decided turns (2 total)
    assert "claude-fable-5" in view.inferred_shares
    assert "grok-4.5" in view.inferred_shares
    assert abs(view.inferred_shares["claude-fable-5"]["pct"] - 50.0) < 0.01
    assert abs(view.inferred_shares["grok-4.5"]["pct"] - 50.0) < 0.01


def test_latest_version_filter(db):
    """Stale version rows must be ignored; only the newest model_version counts."""
    # Seed stale rows (earlier created_at)
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "stale-model",
                "probability": 0.95,
                "model_version": STALE_VERSION,
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 1,
                "inferred_model": "stale-model",
                "probability": 0.95,
                "model_version": STALE_VERSION,
                "created_at": "2026-01-01T00:00:01",
            },
        ],
    )
    # Seed current rows (later created_at)
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "claude-fable-5",
                "probability": 0.91,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T09:00:00",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 1,
                "inferred_model": "grok-4.5",
                "probability": 0.88,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T09:00:01",
            },
        ],
    )

    view = get_inferred_view(db, TASK_ID)
    assert view is not None
    assert view.model_version == CURRENT_VERSION
    # stale-model should NOT appear
    assert "stale-model" not in view.inferred_shares
    assert "claude-fable-5" in view.inferred_shares
    assert "grok-4.5" in view.inferred_shares
    assert len(view.per_turn) == 2


def test_prefix_match(db):
    """get_inferred_view should work with a short prefix of the task_id."""
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "claude-fable-5",
                "probability": 0.88,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:00",
            }
        ],
    )
    view = get_inferred_view(db, SHORT_TASK)
    assert view is not None
    assert "claude-fable-5" in view.inferred_shares


def test_factual_shares_unchanged_by_inferences(db):
    """
    Presence of blindtest_inferences must NOT alter aggregate_task's
    factual request_shares / output_shares.
    """
    _seed_factual_events(db, TASK_ID)

    # Get factual report before adding inferences
    report_before = aggregate_task(db, TASK_ID)
    assert report_before is not None
    shares_before = dict(report_before.output_shares)

    # Now add inferences
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "claude-fable-5",
                "probability": 0.92,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:00",
            },
        ],
    )

    report_after = aggregate_task(db, TASK_ID)
    assert report_after is not None
    shares_after = dict(report_after.output_shares)

    # Factual shares must be identical
    assert shares_before == shares_after
    # claude-fable-5 must NOT appear in factual output_shares (it was auto-opaque)
    assert "claude-fable-5" not in shares_after


def test_all_abstained(db):
    """When all turns abstain, inferred_shares is empty."""
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": None,
                "probability": 0.55,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:00",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 1,
                "inferred_model": None,
                "probability": 0.60,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:01",
            },
        ],
    )
    view = get_inferred_view(db, TASK_ID)
    assert view is not None
    assert view.abstained == 2
    assert view.inferred_shares == {}


def test_cli_cursor_task_inferred_smoke(db, tmp_path, monkeypatch):
    """CLI cursor task --inferred renders without crashing (seeded inferences)."""
    _seed_factual_events(db, TASK_ID)
    _seed_inferences(
        db,
        TASK_ID,
        [
            {
                "task_id": TASK_ID,
                "turn_index": 0,
                "inferred_model": "claude-fable-5",
                "probability": 0.91,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:00",
            },
            {
                "task_id": TASK_ID,
                "turn_index": 1,
                "inferred_model": None,  # abstained
                "probability": 0.62,
                "model_version": CURRENT_VERSION,
                "created_at": "2026-07-09T10:00:01",
            },
        ],
    )

    # Patch Database to return our tmp db regardless of db_path arg
    import verkee_verify.storage.database as db_module

    original_cls = db_module.Database

    class _PatchedDB(Database):
        def __init__(self, db_path=None):
            super().__init__(db_path=db.db_path)

    monkeypatch.setattr(db_module, "Database", _PatchedDB)

    runner = CliRunner()
    result = runner.invoke(cursor_task, [TASK_ID, "--inferred"])

    assert result.exit_code == 0, result.output
    assert "盲测推断" in result.output
    assert "claude-fable-5" in result.output
    assert "低置信" in result.output
    assert "逐 turn" in result.output


def test_cli_cursor_task_inferred_no_model_no_record(db, monkeypatch):
    """--inferred with no stored inferences and no model file prints graceful message."""
    _seed_factual_events(db, TASK_ID)

    import verkee_verify.storage.database as db_module

    class _PatchedDB(Database):
        def __init__(self, db_path=None):
            super().__init__(db_path=db.db_path)

    monkeypatch.setattr(db_module, "Database", _PatchedDB)

    runner = CliRunner()
    result = runner.invoke(cursor_task, [TASK_ID, "--inferred"])

    assert result.exit_code == 0
    # Should print a graceful message (either "先运行" or "盲测")
    assert "blindtest" in result.output.lower() or "盲测" in result.output
