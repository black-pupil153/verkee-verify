"""Create minimal ai-tracking sample DB for tests."""

import sqlite3
from pathlib import Path

FIXTURE_DB = Path(__file__).parent / "ai_tracking_sample.db"


def _create_fixture_db() -> None:
    conn = sqlite3.connect(FIXTURE_DB)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_code_hashes (
            hash TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            fileExtension TEXT,
            fileName TEXT,
            requestId TEXT,
            conversationId TEXT,
            timestamp TEXT,
            model TEXT,
            createdAt TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            conversationId TEXT PRIMARY KEY,
            title TEXT,
            tldr TEXT,
            overview TEXT,
            summaryBullets TEXT,
            model TEXT,
            mode TEXT,
            updatedAt TEXT
        );
        """
    )
    rows = [
        ("h1", "ai", ".py", "a.py", "req-a", "task-906dea0f", "2026-07-03", "claude-fable-5", "2026-07-03"),
        ("h2", "ai", ".py", "b.py", "req-a", "task-906dea0f", "2026-07-03", "claude-fable-5", "2026-07-03"),
        ("h3", "ai", ".py", "c.py", "req-b", "task-906dea0f", "2026-07-09", "grok-4.5", "2026-07-09"),
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO ai_code_hashes
        (hash, source, fileExtension, fileName, requestId, conversationId, timestamp, model, createdAt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    _create_fixture_db()
