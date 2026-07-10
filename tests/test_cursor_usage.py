"""Cursor 导入与聚合测试"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_verify.monitor.cursor_usage import (
    CursorUsageImporter,
    aggregate_task,
    merge_turn,
    parse_since,
)
from ai_verify.providers.cursor import CursorPaths
from ai_verify.storage.database import Database

FIXTURE_LOG = (
    Path(__file__).parent / "fixtures" / "cursor" / "structured_log_sample.log"
)
FIXTURE_DB_SCRIPT = (
    Path(__file__).parent / "fixtures" / "cursor" / "create_ai_tracking_sample.py"
)


@pytest.fixture
def tracking_db(tmp_path):
    db = tmp_path / "ai-code-tracking.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE ai_code_hashes (
                hash TEXT PRIMARY KEY, source TEXT, fileExtension TEXT, fileName TEXT,
                requestId TEXT, conversationId TEXT, timestamp TEXT, model TEXT, createdAt TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO ai_code_hashes
            (hash, source, fileExtension, fileName, requestId, conversationId, timestamp, model, createdAt)
            VALUES (?, 'ai', '.py', 'f.py', ?, ?, '2026-07-03', ?, '2026-07-03')
            """,
            [
                ("h1", "req-a", "task-906dea0f", "claude-fable-5"),
                ("h2", "req-a", "task-906dea0f", "claude-fable-5"),
                ("h3", "req-b", "task-906dea0f", "grok-4.5"),
            ],
        )
        conn.commit()
    return db


@pytest.fixture
def cursor_env(tmp_path, tracking_db, monkeypatch):
    monkeypatch.setattr(
        "ai_verify.monitor.cursor_usage.default_hook_event_paths",
        lambda: [],
    )

    logs_dir = tmp_path / "logs"
    log_dest = logs_dir / "session" / "exthost" / "anysphere.cursor-always-local"
    log_dest.mkdir(parents=True)
    log_dest.joinpath("Cursor Structured Logs.log").write_text(
        FIXTURE_LOG.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (logs_dir / "session" / "renderer.log").parent.mkdir(parents=True, exist_ok=True)

    projects = tmp_path / "cursor_home" / "projects" / "demo" / "agent-transcripts"
    task_dir = projects / "task-906dea0f"
    (task_dir / "subagents").mkdir(parents=True)
    (task_dir / "subagents" / "sub-1.jsonl").write_text("{}\n")

    paths = CursorPaths(
        ai_tracking_db=tracking_db,
        global_state_db=None,
        logs_dir=logs_dir,
        projects_dir=tmp_path / "cursor_home" / "projects",
    )
    db = Database(db_path=tmp_path / "ai_verify.db")
    return paths, db


def test_parse_since():
    dt = parse_since("7d")
    assert dt < datetime.now()
    assert dt > datetime.now() - timedelta(days=8)


def test_merge_turn_prefers_tracking():
    merged = merge_turn(
        "req-a",
        "task-1",
        {
            "selected_model": "grok-4.5",
            "catalog_model_id": "grok-4.5",
            "ai_tracking": {"model": "claude-fable-5", "count": 10},
            "outcome": "success",
        },
    )
    assert merged.resolved_model == "claude-fable-5"
    assert merged.confidence == "high"
    assert merged.event_source == "ai_tracking_db"


def test_merge_turn_auto_low_confidence():
    merged = merge_turn(
        "req-x",
        "task-1",
        {"selected_model": "default", "outcome": "success"},
    )
    assert merged.route_kind == "auto"
    assert merged.resolved_model is None
    assert merged.confidence == "low"


def test_merge_turn_tracking_default_not_resolved():
    merged = merge_turn(
        "req-x",
        "task-1",
        {
            "selected_model": "default",
            "ai_tracking": {"model": "default", "count": 875},
            "outcome": "success",
        },
    )
    assert merged.route_kind == "auto"
    assert merged.resolved_model is None
    assert merged.confidence == "low"
    assert merged.generated_units == 875


def test_aggregate_auto_opaque_bucket(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    importer.import_all(since=datetime.now() - timedelta(days=30), full=True)

    # Inject an auto event with default tracking
    db.save_cursor_model_event(
        {
            "id": "ev-auto-opaque",
            "task_id": "task-auto",
            "request_id": "req-opaque",
            "selected_model": "default",
            "resolved_model": None,
            "route_kind": "auto",
            "event_source": "ai_tracking_db",
            "confidence": "low",
            "generated_units": 100,
            "status": "success",
            "timestamp": "2026-07-03T10:00:00",
        }
    )
    db.save_cursor_task(
        {
            "task_id": "task-auto",
            "title": "Auto task",
            "mode": "agent",
            "route_kind": "auto",
            "request_count": 1,
            "code_unit_count": 100,
        }
    )

    report = aggregate_task(db, "task-auto")
    assert report is not None
    assert "auto-opaque" in report.output_shares
    assert report.output_shares["auto-opaque"]["count"] == 100
    assert report.resolved_requests == 0
    assert report.resolution_rate == 0.0


def test_import_and_aggregate(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    result = importer.import_all(since=datetime.now() - timedelta(days=30), full=True)
    assert result.events_upserted >= 2
    assert result.tasks_upserted >= 1

    report = aggregate_task(db, "task-906dea0f")
    assert report is not None
    assert report.request_count >= 2
    assert report.code_unit_count >= 3
    assert (
        "claude-fable-5" in report.output_shares or "grok-4.5" in report.output_shares
    )


def test_dedupe_import(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    r1 = importer.import_all(since=datetime.now() - timedelta(days=30), full=True)
    r2 = importer.import_all(since=datetime.now() - timedelta(days=30), full=False)
    assert r1.events_upserted >= 1
    # second incremental pass should not explode event count due to UNIQUE constraint
    total = db.get_cursor_events_for_task("task-906dea0f")
    assert len(total) == r1.events_upserted


def test_import_hook_events_and_dedupe(tmp_path):
    hook_path = tmp_path / "cursor-hook-probe.ndjson"
    hook_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "hook_event": "stop",
                        "received_at": "2026-07-09T10:00:00",
                        "payload": {
                            "conversation_id": "task-hook",
                            "generation_id": "req-hook",
                            "model": "claude-fable-5",
                            "model_id": "claude-fable-5-thinking",
                            "status": "success",
                        },
                    }
                ),
                json.dumps(
                    {
                        "hook_event": "afterAgentResponse",
                        "received_at": "2026-07-09T10:01:00",
                        "payload": {
                            "conversation_id": "task-hook",
                            "generation_id": "req-default",
                            "model": "default",
                        },
                    }
                ),
                json.dumps(
                    {
                        "hook_event": "subagentStop",
                        "received_at": "2026-07-09T10:02:00",
                        "payload": {
                            "subagent_id": "sub-hook",
                            "subagent_model": "grok-4.5",
                            "parent_conversation_id": "task-hook",
                            "status": "success",
                        },
                    }
                ),
                "{bad json",
            ]
        ),
        encoding="utf-8",
    )
    paths = CursorPaths(logs_dir=tmp_path / "logs", projects_dir=tmp_path / "projects")
    paths.logs_dir.mkdir()
    paths.projects_dir.mkdir()
    db = Database(db_path=tmp_path / "ai_verify.db")

    importer = CursorUsageImporter(db=db, paths=paths, hook_event_paths=[hook_path])
    result = importer.import_all(since=datetime.now() - timedelta(days=30), full=True)
    assert result.hook_events_seen == 3
    assert result.hook_events_resolved == 2

    task_events = db.get_cursor_events_for_task("task-hook")
    assert len(task_events) == 1
    assert task_events[0]["event_source"] == "hook"
    assert task_events[0]["resolved_model"] == "claude-fable-5-thinking"

    sub_events = db.get_cursor_events_for_task("sub-hook")
    assert len(sub_events) == 1
    assert sub_events[0]["parent_task_id"] == "task-hook"
    assert sub_events[0]["resolved_model"] == "grok-4.5"
    assert db.get_cursor_subagents("task-hook")[0]["task_id"] == "sub-hook"

    second = importer.import_all(since=datetime.now() - timedelta(days=30), full=False)
    assert second.hook_events_seen == 0
    assert len(db.get_cursor_events_for_task("task-hook")) == 1


def test_hook_fills_default_tracking_model(tmp_path):
    tracking = tmp_path / "ai-code-tracking.db"
    with sqlite3.connect(tracking) as conn:
        conn.execute(
            """
            CREATE TABLE ai_code_hashes (
                hash TEXT PRIMARY KEY, requestId TEXT, conversationId TEXT,
                timestamp TEXT, model TEXT, createdAt TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES ('h1', 'req-1', 'task-1', '2026-07-09', 'default', '2026-07-09')"
        )
        conn.commit()
    hook_path = tmp_path / "cursor-events.ndjson"
    hook_path.write_text(
        json.dumps(
            {
                "hook_event": "stop",
                "received_at": "2026-07-09T10:00:00",
                "payload": {
                    "conversation_id": "task-1",
                    "generation_id": "req-1",
                    "model_id": "claude-fable-5",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths = CursorPaths(ai_tracking_db=tracking, logs_dir=tmp_path / "logs")
    paths.logs_dir.mkdir()
    db = Database(db_path=tmp_path / "ai_verify.db")

    CursorUsageImporter(db=db, paths=paths, hook_event_paths=[hook_path]).import_all(
        since=datetime.now() - timedelta(days=30), full=True
    )
    event = db.get_cursor_events_for_task("task-1")[0]
    assert event["resolved_model"] == "claude-fable-5"
    assert event["event_source"] == "hook"
    assert event["generated_units"] == 1


def test_conversation_summary_fallback(tmp_path):
    tracking = tmp_path / "ai-code-tracking.db"
    with sqlite3.connect(tracking) as conn:
        conn.executescript(
            """
            CREATE TABLE ai_code_hashes (
                hash TEXT PRIMARY KEY, requestId TEXT, conversationId TEXT,
                timestamp TEXT, model TEXT, createdAt TEXT
            );
            CREATE TABLE conversation_summaries (
                conversationId TEXT PRIMARY KEY, model TEXT, mode TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES ('h1', 'req-1', 'task-summary', '2026-07-09', 'default', '2026-07-09')"
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES ('task-summary', 'claude-sonnet-4', 'multitask')"
        )
        conn.commit()
    paths = CursorPaths(ai_tracking_db=tracking, logs_dir=tmp_path / "logs")
    paths.logs_dir.mkdir()
    db = Database(db_path=tmp_path / "ai_verify.db")

    CursorUsageImporter(db=db, paths=paths, hook_event_paths=[]).import_all(
        since=datetime.now() - timedelta(days=30), full=True
    )
    event = db.get_cursor_events_for_task("task-summary")[0]
    task = db.get_cursor_task("task-summary")
    assert event["resolved_model"] == "claude-sonnet-4"
    assert event["event_source"] == "conversation_summary"
    assert event["confidence"] == "medium"
    assert task["mode"] == "multitask"


def test_timeline_catalog_assignment(tmp_path):
    logs_dir = tmp_path / "logs" / "session"
    logs_dir.mkdir(parents=True)
    (logs_dir / "renderer.log").write_text(
        "\n".join(
            [
                "2026-07-09 10:00:00.000 [info] [buildRequestedModel] composerId=task-time catalogModelId=claude-fable-5 composerModelName=default selectedModelIds=default",
                "2026-07-09 10:05:00.000 [info] [buildRequestedModel] composerId=task-time catalogModelId=grok-4.5 composerModelName=default selectedModelIds=default",
            ]
        ),
        encoding="utf-8",
    )
    structured = logs_dir / "exthost" / "anysphere.cursor-always-local"
    structured.mkdir(parents=True)
    (structured / "Cursor Structured Logs.log").write_text(
        "\n".join(
            [
                '2026-07-09 10:01:00.000 [info] {"message":"agent.turn.outcome","metadata":{"model_intent":"default","request_id":"req-before","conversation_id":"task-time","outcome":"success"}}',
                '2026-07-09 10:06:00.000 [info] {"message":"agent.turn.outcome","metadata":{"model_intent":"default","request_id":"req-after","conversation_id":"task-time","outcome":"success"}}',
            ]
        ),
        encoding="utf-8",
    )
    paths = CursorPaths(logs_dir=tmp_path / "logs")
    db = Database(db_path=tmp_path / "ai_verify.db")

    CursorUsageImporter(db=db, paths=paths, hook_event_paths=[]).import_all(
        since=datetime.now() - timedelta(days=30), full=True
    )
    by_request = {
        e["request_id"]: e for e in db.get_cursor_events_for_task("task-time")
    }
    assert by_request["req-before"]["resolved_model"] == "claude-fable-5"
    assert by_request["req-after"]["resolved_model"] == "grok-4.5"


def test_request_trace_join_and_multitask_mode(tmp_path):
    logs_dir = (
        tmp_path / "logs" / "session" / "exthost" / "anysphere.cursor-always-local"
    )
    logs_dir.mkdir(parents=True)
    (logs_dir / "cursor.requestTraces.log").write_text(
        "2026-07-09 10:00:00.000 [info] requestId=req-trace composerId=task-trace trace_id=trace-1\n",
        encoding="utf-8",
    )
    (logs_dir / "Cursor Structured Logs.log").write_text(
        '2026-07-09 10:01:00.000 [info] {"message":"agent.turn.outcome","metadata":{"model_intent":"default","trace_id":"trace-1","outcome":"success","unifiedMode":"multitask"}}\n',
        encoding="utf-8",
    )
    paths = CursorPaths(logs_dir=tmp_path / "logs")
    db = Database(db_path=tmp_path / "ai_verify.db")

    CursorUsageImporter(db=db, paths=paths, hook_event_paths=[]).import_all(
        since=datetime.now() - timedelta(days=30), full=True
    )
    events = db.get_cursor_events_for_task("task-trace")
    task = db.get_cursor_task("task-trace")
    assert len(events) == 1
    assert events[0]["request_id"] == "req-trace"
    assert task["mode"] == "multitask"
