"""Tests for default Auto fusion (ensure_task_inferences) and title fallback."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from verkeep_verify.blindtest.classifier import BlindModelClassifier
from verkeep_verify.blindtest.corpus import Corpus, CorpusSample
from verkeep_verify.monitor.blindtest_infer import ensure_task_inferences
from verkeep_verify.monitor.cursor_usage import CursorUsageImporter, aggregate_task
from verkeep_verify.providers.cursor import CursorPaths, read_conversation_summaries
from verkeep_verify.storage.database import Database


def _train_tiny_model(path: Path) -> None:
    samples = []
    for i, label in enumerate(["model-a", "model-a", "model-b", "model-b"]):
        samples.append(
            CorpusSample(
                conversation_id=f"conv-{label}",
                turn_index=i,
                request_id=f"rid-{i}",
                label=label,
                label_source="test",
                ttft_ms=100.0,
                features={
                    "text_len": float(10 + i),
                    "tool_count": float(i % 2),
                    "code_present": 1.0 if label == "model-a" else 0.0,
                },
            )
        )
    corpus = Corpus(samples=samples, built_at="2026-07-13T00:00:00")
    clf = BlindModelClassifier(threshold=0.5)
    clf.train(corpus)
    clf.save(path)


def _write_transcript(projects_dir: Path, conv_id: str, texts: list[str]) -> None:
    task_dir = projects_dir / "proj" / "agent-transcripts" / conv_id
    task_dir.mkdir(parents=True)
    lines = []
    for text in texts:
        lines.append(
            json.dumps(
                {
                    "role": "user",
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\n{text}",
                            }
                        ]
                    },
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "role": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": f"answer for {text} ```python\nprint(1)\n```"}]
                    },
                }
            )
        )
        lines.append(json.dumps({"type": "turn_ended", "status": "completed"}))
    (task_dir / f"{conv_id}.jsonl").write_text("\n".join(lines), encoding="utf-8")


def test_ensure_task_inferences_writes_without_touching_resolved(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    conv = "task-ensure-001"
    _write_transcript(projects, conv, ["q1", "q2"])
    monkeypatch.setattr(
        "verkeep_verify.blindtest.corpus.discover_transcript_files",
        lambda projects_dir=None: [
            (conv, projects / "proj" / "agent-transcripts" / conv / f"{conv}.jsonl")
        ],
    )

    model_path = tmp_path / "model.json"
    _train_tiny_model(model_path)

    db = Database(db_path=tmp_path / "ai_verify.db")
    db.save_cursor_task(
        {
            "task_id": conv,
            "title": "ensure",
            "mode": "agent",
            "route_kind": "auto",
            "request_count": 2,
        }
    )
    for i, rid in enumerate(["req-e1", "req-e2"]):
        db.save_cursor_model_event(
            {
                "id": f"ev-e{i}",
                "task_id": conv,
                "request_id": rid,
                "selected_model": "default",
                "resolved_model": None,
                "route_kind": "auto",
                "event_source": "structured_log",
                "confidence": "low",
                "generated_units": 10,
                "status": "success",
                "timestamp": f"2026-07-03T10:1{i}:00",
            }
        )

    written = ensure_task_inferences(
        db, conv, model_path=model_path, projects_dir=projects, force=True
    )
    assert written == 2
    rows = db.get_blindtest_inferences(conv)
    assert len(rows) == 2
    assert all(r.get("inferred_model") for r in rows)

    # resolved_model unchanged
    events = db.get_cursor_events_for_task(conv)
    assert all(not e.get("resolved_model") for e in events)

    report = aggregate_task(db, conv, auto_infer=False)
    assert report is not None
    assert report.coverage == 1.0
    assert report.pending_infer_count == 0
    assert "pending-infer" not in report.request_shares
    assert report.factual_request_shares == {}
    assert report.inferred_request_shares


def test_aggregate_task_auto_infer_hook(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    conv = "task-auto-hook-002"
    _write_transcript(projects, conv, ["hello"])
    monkeypatch.setattr(
        "verkeep_verify.blindtest.corpus.discover_transcript_files",
        lambda projects_dir=None: [
            (conv, projects / "proj" / "agent-transcripts" / conv / f"{conv}.jsonl")
        ],
    )
    model_path = tmp_path / "model.json"
    _train_tiny_model(model_path)
    monkeypatch.setattr(
        "verkeep_verify.monitor.blindtest_infer.DEFAULT_MODEL_PATH", model_path
    )

    db = Database(db_path=tmp_path / "ai_verify.db")
    db.save_cursor_task(
        {
            "task_id": conv,
            "title": "auto hook",
            "mode": "agent",
            "route_kind": "auto",
            "request_count": 1,
        }
    )
    db.save_cursor_model_event(
        {
            "id": "ev-ah",
            "task_id": conv,
            "request_id": "req-ah",
            "selected_model": "default",
            "resolved_model": None,
            "route_kind": "auto",
            "event_source": "structured_log",
            "confidence": "low",
            "generated_units": 5,
            "status": "success",
            "timestamp": "2026-07-03T10:12:00",
        }
    )

    report = aggregate_task(db, conv)  # auto_infer default True
    assert report is not None
    assert report.coverage == 1.0
    assert db.get_blindtest_inferences(conv)


def test_read_conversation_summaries_title(tmp_path):
    db = tmp_path / "tracking.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE conversation_summaries (
                conversationId TEXT PRIMARY KEY,
                title TEXT, tldr TEXT, model TEXT, mode TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES "
            "('task-t', 'My Title', 'short tldr', 'claude-fable-5', 'agent')"
        )
        conn.commit()
    summaries = read_conversation_summaries(db)
    assert summaries["task-t"]["title"] == "My Title"
    assert summaries["task-t"]["tldr"] == "short tldr"


def test_import_title_from_conversation_summary(tmp_path):
    tracking = tmp_path / "ai-code-tracking.db"
    with sqlite3.connect(tracking) as conn:
        conn.executescript(
            """
            CREATE TABLE ai_code_hashes (
                hash TEXT PRIMARY KEY, requestId TEXT, conversationId TEXT,
                timestamp TEXT, model TEXT, createdAt TEXT
            );
            CREATE TABLE conversation_summaries (
                conversationId TEXT PRIMARY KEY,
                title TEXT, tldr TEXT, model TEXT, mode TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES "
            "('h1', 'req-1', 'task-title-fb', '2026-07-09', 'default', '2026-07-09')"
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES "
            "('task-title-fb', 'Summary Title', NULL, 'claude-sonnet-4', 'agent')"
        )
        conn.commit()
    paths = CursorPaths(ai_tracking_db=tracking, logs_dir=tmp_path / "logs")
    paths.logs_dir.mkdir()
    db = Database(db_path=tmp_path / "ai_verify.db")
    CursorUsageImporter(db=db, paths=paths, hook_event_paths=[]).import_all(
        since=datetime.now() - timedelta(days=30), full=True
    )
    task = db.get_cursor_task("task-title-fb")
    assert task["title"] == "Summary Title"
