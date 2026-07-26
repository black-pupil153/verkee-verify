"""Cursor 报告与质量关联测试"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from verkeep_verify.monitor.cursor_usage import (
    CursorUsageImporter,
    aggregate_period,
    cursor_usage_insights,
    get_model_scores,
    period_to_since,
    render_task_score_table,
)
from verkeep_verify.providers.cursor import CursorPaths
from verkeep_verify.report import load_cursor_period, render_cursor_section
from verkeep_verify.storage.database import Database

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


def test_period_to_since():
    assert period_to_since("weekly") == "7d"
    assert period_to_since("daily") == "1d"


def test_cursor_usage_insights_detects_divergence():
    from verkeep_verify.monitor.cursor_usage import PeriodUsageReport

    period = PeriodUsageReport(
        since_label="7d",
        task_count=2,
        request_shares={"grok-4.5": {"pct": 75, "count": 3}},
        output_shares={"claude-fable-5": {"pct": 64, "count": 10}},
    )
    insights = cursor_usage_insights(period)
    assert any("请求主力" in line for line in insights)


def test_get_model_scores_fuzzy(tmp_path):
    db = Database(db_path=tmp_path / "scores.db")
    db.save_score_snapshot(
        {
            "id": "s1",
            "timestamp": datetime.utcnow().isoformat(),
            "model": "claude-fable-5-thinking",
            "base_url": "http://x",
            "intelligence_score": 88,
            "deviation": 3,
        }
    )
    scores = get_model_scores(db, ["claude-fable-5"])
    assert scores["claude-fable-5"]["intelligence_score"] == 88


def test_render_cursor_section(cursor_env, monkeypatch):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    importer.import_all(since=datetime.now() - timedelta(days=30), full=True)

    monkeypatch.setattr(
        "verkeep_verify.report.load_cursor_period",
        lambda period, db=None, refresh=True, limit=50: aggregate_period(
            db or Database(db_path=db.db_path),
            since=datetime.now() - timedelta(days=30),
            limit=10,
        ),
    )
    assert render_cursor_section("weekly", db=db, refresh=False) is True


def test_render_task_score_table(cursor_env):
    paths, db = cursor_env
    importer = CursorUsageImporter(db=db, paths=paths)
    importer.import_all(since=datetime.now() - timedelta(days=30), full=True)
    from verkeep_verify.monitor.cursor_usage import aggregate_task

    report = aggregate_task(db, "task-906dea0f")
    table = render_task_score_table(report, db)
    assert table is not None
