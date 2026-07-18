"""Cursor 路径探测测试"""

from pathlib import Path

from ai_verify.providers.cursor import (
    discover_cursor_paths,
    header_display_title,
    load_composer_headers,
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
    proxy = next(c for c in report.checks if c.name == "proxy supplement")
    assert proxy.optional is True
    assert proxy.ok is False
    assert proxy.severity == "warning"
    # Optional proxy must not decide overall health.
    required = [c for c in report.checks if not c.optional]
    assert report.required_ok == all(c.ok for c in required)
    assert report.to_dict()["ok"] == report.required_ok
    assert any(w["name"] == "proxy supplement" for w in report.to_dict()["warnings"])
    assert report.suggestion.startswith("ai-verify cursor import")


def test_run_doctor_optional_proxy_does_not_fail_when_core_ok(tmp_path, monkeypatch):
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
    logs = app_support / "logs" / "20260714T120000"
    logs.mkdir(parents=True)
    (logs / "window1" / "renderer.log").parent.mkdir(parents=True)
    (logs / "window1" / "renderer.log").write_text('{"type":"test"}\n')

    state_db = app_support / "User" / "globalStorage" / "state.vscdb"
    state_db.parent.mkdir(parents=True)
    with sqlite3.connect(state_db) as conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composer.composerHeaders", "{}"),
        )
        conn.commit()

    projects = cursor_home / "projects" / "demo" / "agent-transcripts" / "task-1"
    projects.mkdir(parents=True)
    (projects / "transcript.jsonl").write_text("{}\n")

    monkeypatch.setattr("ai_verify.providers.cursor._cursor_home", lambda: cursor_home)
    monkeypatch.setattr(
        "ai_verify.providers.cursor._cursor_app_support", lambda: app_support
    )

    report = run_doctor(ai_verify_db=tmp_path / "missing.db")
    payload = report.to_dict()
    assert payload["ok"] is True
    assert any(w["name"] == "proxy supplement" for w in payload["warnings"])
    assert all(
        c["ok"] or c.get("optional") for c in payload["checks"]
    )


def test_header_display_title_prefers_name():
    assert header_display_title({"name": "Auto title", "subtitle": "first msg"}) == (
        "Auto title"
    )
    assert header_display_title({"subtitle": " only sub "}) == "only sub"
    assert header_display_title({}) is None
    assert header_display_title(None) is None


def test_load_composer_headers_merges_table_over_json(tmp_path):
    """Table-gated composerHeaders wins for Agent/Glass sessions missing from JSON."""
    import json
    import sqlite3

    state_db = tmp_path / "state.vscdb"
    legacy = {
        "allComposers": [
            {
                "composerId": "legacy-1",
                "subtitle": "old subtitle",
                "lastUpdatedAt": 100,
            },
            {
                "composerId": "shared-1",
                "subtitle": "stale subtitle",
                "lastUpdatedAt": 100,
            },
        ]
    }
    with sqlite3.connect(state_db) as conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composer.composerHeaders", json.dumps(legacy)),
        )
        conn.execute(
            """
            CREATE TABLE composerHeaders (
                composerId TEXT PRIMARY KEY,
                workspaceId TEXT,
                createdAt INTEGER,
                lastUpdatedAt INTEGER,
                isArchived INTEGER,
                isSubagent INTEGER,
                recency INTEGER,
                checkpointAt INTEGER,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO composerHeaders
            (composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,
             isSubagent, recency, checkpointAt, value)
            VALUES (?, ?, ?, ?, 0, 0, ?, NULL, ?)
            """,
            (
                "glass-1",
                "ws",
                200,
                200,
                200,
                json.dumps(
                    {
                        "composerId": "glass-1",
                        "name": "A3 sidebar dogfood tasks",
                        "subtitle": "Edited settings.json",
                        "lastUpdatedAt": 200,
                        "unifiedMode": "agent",
                    }
                ),
            ),
        )
        conn.execute(
            """
            INSERT INTO composerHeaders
            (composerId, workspaceId, createdAt, lastUpdatedAt, isArchived,
             isSubagent, recency, checkpointAt, value)
            VALUES (?, ?, ?, ?, 0, 0, ?, NULL, ?)
            """,
            (
                "shared-1",
                "ws",
                300,
                300,
                300,
                json.dumps(
                    {
                        "composerId": "shared-1",
                        "name": "Fresh auto name",
                        "subtitle": "activity",
                        "lastUpdatedAt": 300,
                    }
                ),
            ),
        )
        conn.commit()

    headers = load_composer_headers(state_db)
    assert "legacy-1" in headers
    assert headers["glass-1"]["name"] == "A3 sidebar dogfood tasks"
    assert headers["shared-1"]["name"] == "Fresh auto name"
    assert header_display_title(headers["glass-1"]) == "A3 sidebar dogfood tasks"
