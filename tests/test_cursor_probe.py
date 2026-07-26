"""Cursor probe scanner tests."""

import json
from pathlib import Path

from verkeep_verify.cursor_probe import discover_probe_log_files, run_probe
from verkeep_verify.providers.cursor import CursorPaths


def test_discover_probe_log_files(tmp_path):
    logs = tmp_path / "logs" / "20260709"
    exthost = logs / "exthost" / "anysphere.cursor-always-local"
    exthost.mkdir(parents=True)
    (exthost / "Cursor Structured Logs.log").write_text("line\n", encoding="utf-8")
    (exthost / "cursor.requestTraces.log").write_text("{}\n", encoding="utf-8")
    (logs / "renderer.log").write_text("x\n", encoding="utf-8")

    files = discover_probe_log_files(logs)
    names = {f.name for f in files}
    assert "cursor.requestTraces.log" in names
    assert any("Structured Logs" in n for n in names)


def test_run_probe_extracts_model_fields(tmp_path):
    logs = tmp_path / "logs" / "session"
    exthost = logs / "exthost" / "anysphere.cursor-always-local"
    exthost.mkdir(parents=True)
    log_path = exthost / "Cursor Structured Logs.log"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "conversationId": "469c3074-abcd",
                        "requestId": "req-001",
                        "modelName": "default",
                        "model_intent": "default",
                    }
                ),
                json.dumps(
                    {
                        "conversationId": "469c3074-abcd",
                        "requestId": "req-002",
                        "modelName": "claude-sonnet-4",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    paths = CursorPaths(logs_dir=logs)
    report = run_probe(task_id="469c3074", paths=paths, limit=50)
    assert report.files_scanned >= 1
    values = {h.value for h in report.model_hits}
    assert "default" in values
    assert "claude-sonnet-4" in values
    request_ids = {h.request_id for h in report.model_hits}
    assert "req-001" in request_ids or "req-002" in request_ids
