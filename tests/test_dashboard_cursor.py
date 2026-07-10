"""Cursor 看板与周期聚合测试"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_verify.dashboard_cursor import build_view
from ai_verify.monitor.cursor_usage import (
    CursorUsageImporter,
    aggregate_period,
)
from ai_verify.providers.cursor import CursorPaths
from ai_verify.storage.database import Database

FIXTURE_LOG = Path(__file__).parent / "fixtures" / "cursor" / "structured_log_sample.log"


@pytest.fixture
def cursor_env(tmp_path):
    db_path = tmp_path / "ai-code-tracking.db"
    with sqlite3.connect(db_path) as conn:
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

    logs_dir = tmp_path / "logs"
    log_dest = logs_dir / "session" / "exthost" / "anysphere.cursor-always-local"
    log_dest.mkdir(parents=True)
    log_dest.joinpath("Cursor Structured Logs.log").write_text(
        FIXTURE_LOG.read_text(encoding="utf-8"), encoding="utf-8"
    )

    paths = CursorPaths(
        ai_tracking_db=db_path,
        global_state_db=None,
        logs_dir=logs_dir,
        projects_dir=tmp_path / "projects",
    )
    db = Database(db_path=tmp_path / "ai_verify.db")
    return paths, db


def test_aggregate_period(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    importer.import_all(since=datetime.now() - timedelta(days=30), full=True)

    period = aggregate_period(db, since=datetime.now() - timedelta(days=30), limit=10)
    assert period.task_count >= 1
    assert period.total_requests >= 2
    assert period.latest_report is not None


def test_build_view_renders(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    importer.import_all(since=datetime.now() - timedelta(days=30), full=True)

    period = aggregate_period(db, since=datetime.now() - timedelta(days=30))
    view = build_view(period)
    assert view is not None
