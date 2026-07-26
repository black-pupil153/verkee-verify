"""Cursor Hooks install/merge/analyze tests."""

import json
from pathlib import Path

import pytest

from verkeep_verify.cursor_hooks import (
    analyze_probe_ndjson,
    hook_script_path,
    merge_hooks,
    install_hooks,
    is_our_hook_command,
    uninstall_hooks,
)


def test_merge_hooks_preserves_existing(tmp_path, monkeypatch):
    hooks_json = tmp_path / "hooks.json"
    hooks_json.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "beforeShellExecution": [{"command": "/usr/bin/my-guard.sh"}],
                    "stop": [{"command": "/other/stop.sh"}],
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "verkeep_verify.cursor_hooks.hook_script_path",
        lambda: tmp_path / "hooks" / "cursor-track.sh",
    )

    existing = json.loads(hooks_json.read_text())
    merged, added, already = merge_hooks(existing)

    assert "beforeShellExecution" in merged["hooks"]
    assert merged["hooks"]["beforeShellExecution"] == [
        {"command": "/usr/bin/my-guard.sh"}
    ]
    assert any(
        is_our_hook_command(e.get("command"))
        for e in merged["hooks"]["stop"]
    )
    assert any(e.get("command") == "/other/stop.sh" for e in merged["hooks"]["stop"])
    assert "stop" in added or "stop" in already


def test_install_and_uninstall_hooks(tmp_path, monkeypatch):
    cursor_dir = tmp_path / "cursor_config"
    cursor_dir.mkdir()
    hooks_json = cursor_dir / "hooks.json"
    hooks_json.write_text(
        json.dumps({"version": 1, "hooks": {"beforeShellExecution": [{"command": "x"}]}}),
        encoding="utf-8",
    )

    script_dir = tmp_path / "verkeep-verify" / "hooks"
    monkeypatch.setattr("verkeep_verify.cursor_hooks.cursor_hooks_json_path", lambda: hooks_json)
    monkeypatch.setattr(
        "verkeep_verify.cursor_hooks.hook_script_path",
        lambda: script_dir / "cursor-track.sh",
    )
    monkeypatch.setattr(
        "verkeep_verify.cursor_hooks.verify_home",
        lambda: tmp_path / "verkeep-verify",
    )

    result = install_hooks(hooks_json=hooks_json, script_out=script_dir / "cursor-track.sh")
    assert result.script_path.is_file()
    doc = json.loads(hooks_json.read_text())
    assert "stop" in doc["hooks"]
    assert "beforeShellExecution" in doc["hooks"]

    _, backup, removed = uninstall_hooks(hooks_json=hooks_json)
    doc2 = json.loads(hooks_json.read_text())
    assert not any(
        is_our_hook_command(e.get("command"))
        for entries in doc2.get("hooks", {}).values()
        for e in entries
    )
    assert "beforeShellExecution" in doc2["hooks"]
    assert removed
    assert backup and backup.is_file()


def test_analyze_probe_ndjson(tmp_path):
    ndjson = tmp_path / "cursor-hook-probe.ndjson"
    ndjson.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "hook_event": "stop",
                        "received_at": "2026-07-09T00:00:00Z",
                        "payload": {"model": "default", "model_id": "default"},
                    }
                ),
                json.dumps(
                    {
                        "hook_event": "subagentStop",
                        "received_at": "2026-07-09T00:01:00Z",
                        "payload": {"subagent_model": "claude-sonnet-4"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    result = analyze_probe_ndjson(ndjson)
    assert result.total_events == 2
    assert result.event_counts["stop"] == 1
    assert result.provides_resolved_model is True
    assert "claude-sonnet-4" in result.model_values["subagentStop"]


def test_analyze_all_default(tmp_path):
    ndjson = tmp_path / "probe.ndjson"
    ndjson.write_text(
        json.dumps(
            {
                "hook_event": "afterAgentResponse",
                "payload": {"model": "default"},
            }
        ),
        encoding="utf-8",
    )
    result = analyze_probe_ndjson(ndjson)
    assert result.provides_resolved_model is False


def test_normalize_cursor_id_strips_quotes_and_newline():
    from verkeep_verify.cursor_hook_events import normalize_cursor_id

    raw = "'call_SNFbIpOhES8G3CWx9LnrzQg7\nfc_014b39426f78f4ba016a505a00d948819fb65f20c819420394'"
    assert normalize_cursor_id(raw) == "call_SNFbIpOhES8G3CWx9LnrzQg7"
    assert normalize_cursor_id("task-ok") == "task-ok"
    assert normalize_cursor_id(None) is None
