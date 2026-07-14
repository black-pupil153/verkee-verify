"""CLI --json contract for Cursor doctor / tasks / task (extension bridge)."""

from __future__ import annotations

import json

from click.testing import CliRunner

from ai_verify.cli import cursor_doctor, cursor_task, cursor_tasks
from ai_verify.monitor.cursor_usage import (
    TaskSummary,
    TaskUsageReport,
    task_report_to_dict,
    task_summary_to_dict,
)
from ai_verify.providers.cursor import DoctorCheck, DoctorReport
from ai_verify.storage.database import Database


def test_doctor_report_to_dict_lean():
    report = DoctorReport(
        checks=[
            DoctorCheck(
                name="ai-tracking.db", ok=True, detail="ok", extra={"tables": {}}
            ),
            DoctorCheck(
                name="proxy supplement",
                ok=False,
                detail="0 cursor-related api_calls",
                optional=True,
                severity="warning",
            ),
        ],
        collectable_fields=[("model", "hook", "hooks")],
        suggestion="install hooks",
    )
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "ai-tracking.db"
    assert payload["checks"][0]["extra_keys"] == ["tables"]
    assert payload["checks"][0]["optional"] is False
    assert "extra" not in payload["checks"][0]
    assert payload["checks"][1]["optional"] is True
    assert payload["checks"][1]["severity"] == "warning"
    assert payload["warnings"][0]["name"] == "proxy supplement"
    assert payload["collectable_fields"][0]["label"] == "model"


def test_doctor_report_required_failure_sets_ok_false():
    report = DoctorReport(
        checks=[
            DoctorCheck(name="ai-tracking.db", ok=False, detail="missing"),
            DoctorCheck(
                name="proxy supplement",
                ok=True,
                detail="12 cursor-related api_calls",
                optional=True,
                severity="info",
            ),
        ]
    )
    payload = report.to_dict()
    assert payload["ok"] is False
    assert payload["warnings"] == []


def test_task_report_to_dict_omits_per_request_by_default():
    report = TaskUsageReport(
        task_id="abc",
        title="t",
        route_kind="auto",
        coverage=0.75,
        pending_infer_count=1,
        factual_request_shares={"grok-4.5": {"pct": 100.0, "count": 2}},
        per_request=[{"request_id": "r1"}],
    )
    slim = task_report_to_dict(report)
    assert "per_request" not in slim
    assert slim["coverage"] == 0.75
    assert "disclaimer" in slim

    full = task_report_to_dict(report, include_per_request=True)
    assert full["per_request"] == [{"request_id": "r1"}]


def test_task_summary_to_dict():
    s = TaskSummary(task_id="x", title="y", model_request_shares={"a": 50.0})
    d = task_summary_to_dict(s)
    assert d["task_id"] == "x"
    assert d["model_request_shares"]["a"] == 50.0


def test_cursor_tasks_and_task_json(tmp_path, monkeypatch):
    db_path = tmp_path / "ai_verify.db"
    monkeypatch.setattr(
        "ai_verify.storage.database.Database",
        lambda *a, **k: Database(db_path=db_path),
    )

    db = Database(db_path=db_path)
    db.save_cursor_task(
        {
            "task_id": "task-json-1",
            "title": "JSON task",
            "mode": "agent",
            "route_kind": "auto",
            "started_at": "2026-07-13T10:00:00",
            "request_count": 1,
            "code_unit_count": 10,
            "subagent_count": 0,
        }
    )
    db.save_cursor_model_event(
        {
            "id": "ev-1",
            "task_id": "task-json-1",
            "request_id": "req-1",
            "selected_model": "default",
            "resolved_model": None,
            "route_kind": "auto",
            "event_source": "structured_log",
            "confidence": "low",
            "generated_units": 10,
            "status": "success",
            "timestamp": "2026-07-13T10:00:00",
        }
    )

    runner = CliRunner()
    result = runner.invoke(cursor_tasks, ["--json", "--since", "30d", "--limit", "5"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] >= 1
    assert any(t["task_id"] == "task-json-1" for t in payload["tasks"])

    result2 = runner.invoke(cursor_task, ["task-json-1", "--json"])
    assert result2.exit_code == 0, result2.output
    report = json.loads(result2.output)
    assert report["task_id"] == "task-json-1"
    assert "disclaimer" in report
    assert "per_request" not in report


def test_cursor_doctor_json(monkeypatch):
    fake = DoctorReport(
        checks=[DoctorCheck(name="probe", ok=True, detail="ok")],
        suggestion="",
    )
    import ai_verify.providers.cursor as cursor_mod

    monkeypatch.setattr(cursor_mod, "run_doctor", lambda *a, **k: fake)

    runner = CliRunner()
    result = runner.invoke(cursor_doctor, ["--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "probe"
