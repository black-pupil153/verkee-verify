"""Cursor 路径探测测试"""

from pathlib import Path

from ai_verify.providers.cursor import (
    discover_cursor_paths,
    probe_ai_tracking_schema,
    probe_structured_logs,
    read_conversation_summaries,
    run_doctor,
)


def test_discover_cursor_paths_defaults(tmp_path, monkeypatch):
    cursor_home = tmp_path / "cursor_home"
    ai_tracking = cursor_home / "ai-tracking" / "ai-code-tracking.db"
    ai_tracking.parent.mkdir(parents=True)
    ai_tracking.write_bytes(b"sqlite")

    app_support = tmp_path / "Library" / "Application Support" / "Cursor"
    logs = (
        app_support / "logs" / "session1" / "exthost" / "anysphere.cursor-always-local"
    )
    logs.mkdir(parents=True)
    (logs / "Cursor Structured Logs.log").write_text("line\n")
    (cursor_home / "projects").mkdir(parents=True)

    monkeypatch.setattr("ai_verify.providers.cursor._cursor_home", lambda: cursor_home)
    monkeypatch.setattr(
        "ai_verify.providers.cursor._cursor_app_support", lambda: app_support
    )

    paths = discover_cursor_paths()
    assert paths.ai_tracking_db == ai_tracking
    assert paths.logs_dir == app_support / "logs"
    assert paths.projects_dir == cursor_home / "projects"


def test_probe_ai_tracking_schema(tmp_path):
    db = tmp_path / "tracking.db"
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE ai_code_hashes (
                hash TEXT PRIMARY KEY, source TEXT, requestId TEXT,
                conversationId TEXT, model TEXT, timestamp TEXT, createdAt TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES ('h1','ai','r1','c1','m1','t','t')"
        )
        conn.commit()

    schema = probe_ai_tracking_schema(db)
    assert schema["readable"] is True
    assert schema["tables"]["ai_code_hashes"]["exists"] is True
    assert schema["ai_code_hash_count"] == 1


def test_read_conversation_summaries(tmp_path):
    db = tmp_path / "tracking.db"
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE conversation_summaries (
                conversationId TEXT PRIMARY KEY, model TEXT, mode TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES ('task-1', 'claude-fable-5', 'multitask')"
        )
        conn.commit()

    summaries = read_conversation_summaries(db)
    assert summaries["task-1"]["model"] == "claude-fable-5"
    assert summaries["task-1"]["mode"] == "multitask"


def test_probe_structured_logs(tmp_path):
    logs_dir = tmp_path / "logs"
    structured = (
        logs_dir
        / "20260709"
        / "exthost"
        / "anysphere.cursor-always-local"
        / "Cursor Structured Logs.log"
    )
    structured.parent.mkdir(parents=True)
    structured.write_text('{"message":"Composer state loaded"}\n')
    renderer = logs_dir / "20260709" / "renderer.log"
    renderer.parent.mkdir(parents=True, exist_ok=True)
    renderer.write_text("[buildRequestedModel] composerId=abc\n")
    traces = logs_dir / "20260709" / "exthost" / "cursor.requestTraces.log"
    traces.write_text("requestId=r1 composerId=c1 trace_id=t1\n")

    files = probe_structured_logs(logs_dir)
    assert len(files) == 3


def test_run_doctor_minimal(tmp_path, monkeypatch):
    cursor_home = tmp_path / "cursor_home"
    ai_tracking = cursor_home / "ai-tracking" / "ai-code-tracking.db"
    ai_tracking.parent.mkdir(parents=True)

    import sqlite3

    with sqlite3.connect(ai_tracking) as conn:
        conn.execute(
            "CREATE TABLE ai_code_hashes (hash TEXT PRIMARY KEY, source TEXT, model TEXT)"
        )
        conn.commit()

    app_support = tmp_path / "App" / "Cursor"
    logs = app_support / "logs"
    logs.mkdir(parents=True)

    monkeypatch.setattr("ai_verify.providers.cursor._cursor_home", lambda: cursor_home)
    monkeypatch.setattr(
        "ai_verify.providers.cursor._cursor_app_support", lambda: app_support
    )

    report = run_doctor(ai_verify_db=tmp_path / "missing.db")
    names = [c.name for c in report.checks]
    assert "ai-tracking.db" in names
    assert report.suggestion.startswith("ai-verify cursor import")
