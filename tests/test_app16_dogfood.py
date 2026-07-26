"""APP-16 dogfood acceptance fixtures: synthetic Auto sessions (not cloud GT).

Adds richer Auto/subagent mix data so the unified-composition checklist can
regress without inventing Cursor routing ground truth.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from verkeep_verify.cli import cursor_task, cursor_tasks
from verkeep_verify.monitor.cursor_usage import (
    UNKNOWN_MIX_LABEL,
    aggregate_task,
    list_tasks,
)
from verkeep_verify.storage.database import Database


def _seed_auto_session_with_subagent(db: Database) -> str:
    """Root Auto task: 1 confirmed + 1 estimated + 1 unknown; child shares request_id."""
    root = "app16-auto-root"
    child = "app16-auto-child"
    db.save_cursor_task(
        {
            "task_id": root,
            "title": "APP-16 synthetic Auto dogfood",
            "mode": "agent",
            "route_kind": "auto",
            "request_count": 3,
            "subagent_count": 1,
            "started_at": "2026-07-21T02:00:00",
            "ended_at": "2026-07-21T02:10:00",
        }
    )
    db.save_cursor_task(
        {
            "task_id": child,
            "title": "subagent",
            "mode": "agent",
            "route_kind": "specific",
            "parent_task_id": root,
            "request_count": 1,
            "started_at": "2026-07-21T02:03:00",
        }
    )
    # Confirmed factual
    db.save_cursor_model_event(
        {
            "id": "app16-ev-c",
            "task_id": root,
            "request_id": "req-shared",
            "selected_model": "grok-4.5",
            "resolved_model": "grok-4.5",
            "route_kind": "specific",
            "event_source": "hook",
            "confidence": "high",
            "generated_units": 10,
            "status": "success",
            "timestamp": "2026-07-21T02:00:00",
        }
    )
    # Auto opaque → estimated via blindtest
    db.save_cursor_model_event(
        {
            "id": "app16-ev-e",
            "task_id": root,
            "request_id": "req-est",
            "selected_model": "default",
            "resolved_model": None,
            "route_kind": "auto",
            "event_source": "ai_tracking_db",
            "confidence": "low",
            "generated_units": 5,
            "status": "success",
            "timestamp": "2026-07-21T02:01:00",
        }
    )
    db.save_blindtest_inference(
        {
            "task_id": root,
            "turn_index": 0,
            "request_id": "req-est",
            "inferred_model": "composer-2.5-fast",
            "probability": 0.88,
            "model_version": "app16-fixture",
        }
    )
    # Auto opaque → still unknown (no inference / abstain)
    db.save_cursor_model_event(
        {
            "id": "app16-ev-u",
            "task_id": root,
            "request_id": "req-unk",
            "selected_model": "default",
            "resolved_model": None,
            "route_kind": "auto",
            "event_source": "ai_tracking_db",
            "confidence": "low",
            "generated_units": 3,
            "status": "unknown",
            "timestamp": "2026-07-21T02:02:00",
        }
    )
    # Child reuses parent request_id — must not overwrite parent's call
    db.save_cursor_model_event(
        {
            "id": "app16-ev-child",
            "task_id": child,
            "parent_task_id": root,
            "request_id": "req-shared",
            "selected_model": "claude-fable-5",
            "resolved_model": "claude-fable-5",
            "route_kind": "specific",
            "event_source": "hook",
            "confidence": "high",
            "generated_units": 2,
            "status": "success",
            "timestamp": "2026-07-21T02:03:00",
        }
    )
    return root


def test_app16_auto_fixture_mix_and_list_parity(tmp_path, monkeypatch):
    db_path = tmp_path / "ai_verify.db"
    db = Database(db_path=db_path)
    root = _seed_auto_session_with_subagent(db)

    report = aggregate_task(db, root, auto_infer=False)
    assert report is not None
    mix = report.model_mix_v2
    assert mix["total_calls"] == 4  # 3 root + 1 child
    assert mix["subagent_calls"] == 1
    assert mix["confirmed_count"] == 2
    assert mix["estimated_count"] == 1
    assert mix["unknown_count"] == 1
    assert mix["composition"] == "partial"
    assert UNKNOWN_MIX_LABEL in mix["models"]
    assert abs(sum(m["pct"] for m in mix["models"].values()) - 100.0) < 0.01
    # Shared request_id kept both parent and child
    assert mix["models"]["grok-4.5"]["call_count"] == 1
    assert mix["models"]["claude-fable-5"]["call_count"] == 1
    assert mix["models"]["composer-2.5-fast"]["estimated_count"] == 1

    summaries = list_tasks(db, limit=10)
    summary = next(s for s in summaries if s.task_id == root)
    assert summary.request_count == report.request_count == mix["total_calls"]

    import verkeep_verify.storage.database as db_mod

    monkeypatch.setattr(
        db_mod, "Database", lambda *a, **k: Database(db_path=db_path)
    )

    runner = CliRunner()
    human = runner.invoke(cursor_task, [root])
    assert human.exit_code == 0, human.output
    assert "本会话模型构成" in human.output
    assert "事实轨" not in human.output
    assert "推断轨" not in human.output
    assert "已确认" not in human.output
    assert "部分结果为估算" in human.output
    assert UNKNOWN_MIX_LABEL in human.output

    verbose = runner.invoke(cursor_task, [root, "--verbose"])
    assert verbose.exit_code == 0, verbose.output
    assert "来源拆分" in verbose.output or "确认" in verbose.output

    listed = runner.invoke(cursor_tasks, ["--json", "--since", "30d", "--limit", "20"])
    assert listed.exit_code == 0, listed.output
    payload = json.loads(listed.output)
    row = next(t for t in payload["tasks"] if t["task_id"] == root)
    detail = runner.invoke(cursor_task, [root, "--json"])
    assert detail.exit_code == 0, detail.output
    d = json.loads(detail.output)
    assert row["request_count"] == d["request_count"] == d["model_mix_v2"]["total_calls"]
