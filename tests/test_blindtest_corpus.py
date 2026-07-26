"""盲测语料构建测试 — 合成 transcripts + structured logs + tracking db"""

import json
import sqlite3
from datetime import datetime

import pytest

from verkeep_verify.blindtest.corpus import (
    LabelIndex,
    build_corpus,
    extract_turns,
    load_corpus,
    parse_user_timestamp,
    save_corpus,
    task_fingerprint,
)


def _write_transcript(projects_dir, conv_id, turns):
    """turns: list of (user_text, [assistant_message, ...])
    assistant_message: {"text": str} or {"tools": [names]}"""
    task_dir = projects_dir / "proj-a" / "agent-transcripts" / conv_id
    task_dir.mkdir(parents=True)
    path = task_dir / f"{conv_id}.jsonl"
    lines = []
    for user_text, assistant_msgs in turns:
        lines.append(
            json.dumps(
                {
                    "role": "user",
                    "message": {"content": [{"type": "text", "text": user_text}]},
                }
            )
        )
        for msg in assistant_msgs:
            content = []
            if "text" in msg:
                content.append({"type": "text", "text": msg["text"]})
            for name in msg.get("tools", []):
                content.append({"type": "tool_use", "name": name, "input": {}})
            lines.append(
                json.dumps({"role": "assistant", "message": {"content": content}})
            )
        lines.append(json.dumps({"type": "turn_ended", "status": "completed"}))
    path.write_text("\n".join(lines))
    return path


def _write_structured_log(logs_dir, events):
    """events: (ts_str, message, request_id, conv_id, model, ttft)"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for ts, message, rid, cid, model, ttft in events:
        metadata = {"requestId": rid, "composerId": cid, "modelName": model}
        if message == "agent.turn.outcome":
            metadata = {
                "request_id": rid,
                "conversation_id": cid,
                "model_intent": model,
                "outcome": "success",
                "ttft_ms": str(ttft),
            }
        payload = json.dumps({"message": message, "metadata": metadata})
        lines.append(f"{ts} [info] {payload}")
    (logs_dir / "structured.log").write_text("\n".join(lines))


def _write_tracking_db(path, rows):
    """rows: (requestId, conversationId, model)"""
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE ai_code_hashes (
            hash TEXT, source TEXT, fileExtension TEXT, fileName TEXT,
            requestId TEXT, conversationId TEXT, timestamp INTEGER,
            model TEXT, createdAt INTEGER
        )"""
    )
    for rid, cid, model in rows:
        conn.execute(
            "INSERT INTO ai_code_hashes (requestId, conversationId, model) VALUES (?, ?, ?)",
            (rid, cid, model),
        )
    conn.commit()
    conn.close()


def test_parse_user_timestamp():
    ts = parse_user_timestamp(
        "<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nhello"
    )
    assert ts == datetime(2026, 7, 3, 10, 12)
    pm = parse_user_timestamp("<timestamp>Thursday, Jul 9, 2026, 11:12 PM (UTC+8)</timestamp>")
    assert pm == datetime(2026, 7, 9, 23, 12)
    assert parse_user_timestamp("no timestamp here") is None


def test_extract_turns_segmentation(tmp_path):
    path = _write_transcript(
        tmp_path,
        "conv-1",
        [
            ("<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nq1",
             [{"text": "回答一", "tools": ["Read", "Grep"]}, {"tools": ["Shell"]}]),
            ("q2 no timestamp", [{"text": "回答二"}]),
        ],
    )
    turns = extract_turns(path, "conv-1")
    assert len(turns) == 2
    assert turns[0].user_timestamp == datetime(2026, 7, 3, 10, 12)
    assert turns[0].assistant_texts == ["回答一"]
    assert turns[0].tool_batches == [["Read", "Grep"], ["Shell"]]
    assert turns[1].user_timestamp is None
    assert turns[1].assistant_texts == ["回答二"]


def test_build_corpus_joins_labels(tmp_path):
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"

    # conv-a：两个 turn，structured log 直接给出 modelName
    _write_transcript(
        projects,
        "conv-a",
        [
            ("<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nq1",
             [{"text": "answer one", "tools": ["Read"]}]),
            ("<timestamp>Friday, Jul 3, 2026, 10:30 AM (UTC+8)</timestamp>\nq2",
             [{"text": "answer two"}]),
        ],
    )
    # conv-b：log 里 modelName=default，但 tracking db 有真实标签
    _write_transcript(
        projects,
        "conv-b",
        [
            ("<timestamp>Friday, Jul 3, 2026, 11:00 AM (UTC+8)</timestamp>\nq1",
             [{"text": "答案", "tools": ["Shell"]}]),
        ],
    )
    _write_structured_log(
        logs,
        [
            ("2026-07-03 10:12:20.000", "Starting stream request", "rid-a1", "conv-a", "model-x", None),
            ("2026-07-03 10:13:00.000", "agent.turn.outcome", "rid-a1", "conv-a", "model-x", 1500.0),
            ("2026-07-03 10:30:05.000", "Starting stream request", "rid-a2", "conv-a", "model-x", None),
            ("2026-07-03 11:00:10.000", "Starting stream request", "rid-b1", "conv-b", "default", None),
        ],
    )
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [("rid-b1", "conv-b", "model-y")])

    corpus = build_corpus(
        projects_dir=projects, logs_dir=logs, tracking_db=tracking
    )
    by_key = {(s.conversation_id, s.turn_index): s for s in corpus.samples}

    a0 = by_key[("conv-a", 0)]
    assert a0.label == "model-x"
    assert a0.label_source == "structured_log"
    assert a0.request_id == "rid-a1"
    assert a0.ttft_ms == 1500.0

    a1 = by_key[("conv-a", 1)]
    assert a1.label == "model-x"
    assert a1.request_id == "rid-a2"

    b0 = by_key[("conv-b", 0)]
    assert b0.label == "model-y"
    assert b0.label_source == "ai_code_hashes"

    assert corpus.stats["class_counts"] == {"model-x": 2, "model-y": 1}


def test_hook_model_id_outranks_structured_log(tmp_path):
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"
    _write_transcript(
        projects,
        "conv-h",
        [
            (
                "<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nq1",
                [{"text": "```python\ndef hello_world():\n    return 1\n```"}],
            )
        ],
    )
    _write_structured_log(
        logs,
        [
            (
                "2026-07-03 10:12:20.000",
                "Starting stream request",
                "rid-h1",
                "conv-h",
                "model-from-log",
                None,
            )
        ],
    )
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [("rid-h1", "conv-h", "model-from-hash")])
    hook_path = tmp_path / "hooks.ndjson"
    hook_path.write_text(
        json.dumps(
            {
                "hook_event": "stop",
                "received_at": "2026-07-03T10:12:25",
                "payload": {
                    "conversation_id": "conv-h",
                    "generation_id": "rid-h1",
                    "model": "default",
                    "model_id": "hook-claude",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus = build_corpus(
        projects_dir=projects,
        logs_dir=logs,
        tracking_db=tracking,
        hook_event_paths=[hook_path],
    )
    assert len(corpus.samples) == 1
    sample = corpus.samples[0]
    assert sample.label == "hook-claude"
    assert sample.label_source == "hook"
    assert sample.features.get("code_present") == 1.0


def test_build_corpus_hook_aware_timestamp_with_naive_logs(tmp_path):
    """hook received_at 带时区时不得与 structured log naive ts 混排崩溃。"""
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"
    _write_transcript(
        projects,
        "conv-tz",
        [
            (
                "<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nq",
                [{"text": "answer with ```python\nprint(1)\n```"}],
            )
        ],
    )
    _write_structured_log(
        logs,
        [
            (
                "2026-07-03 10:12:05.000",
                "Starting stream request",
                "rid-tz1",
                "conv-tz",
                "default",
                None,
            )
        ],
    )
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [("rid-tz1", "conv-tz", "model-from-hash")])
    hook_path = tmp_path / "hooks.ndjson"
    hook_path.write_text(
        json.dumps(
            {
                "hook_event": "stop",
                "received_at": "2026-07-03T02:12:25+00:00",
                "payload": {
                    "conversation_id": "conv-tz",
                    "generation_id": "rid-tz1",
                    "model": "default",
                    "model_id": "hook-aware",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    corpus = build_corpus(
        projects_dir=projects,
        logs_dir=logs,
        tracking_db=tracking,
        hook_event_paths=[hook_path],
    )
    assert len(corpus.samples) == 1
    assert corpus.samples[0].label == "hook-aware"
    assert corpus.samples[0].label_source == "hook"


def test_build_corpus_drops_unlabeled_by_default(tmp_path):
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"
    _write_transcript(
        projects,
        "conv-c",
        [("<timestamp>Friday, Jul 3, 2026, 09:00 AM (UTC+8)</timestamp>\nq",
          [{"text": "auto answer"}])],
    )
    # default 且无 tracking 标签 → 无法打标
    _write_structured_log(
        logs,
        [("2026-07-03 09:00:05.000", "Starting stream request", "rid-c1", "conv-c", "default", None)],
    )
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [])

    corpus = build_corpus(projects_dir=projects, logs_dir=logs, tracking_db=tracking)
    assert corpus.samples == []

    corpus2 = build_corpus(
        projects_dir=projects, logs_dir=logs, tracking_db=tracking, include_unlabeled=True
    )
    assert len(corpus2.samples) == 1
    assert corpus2.samples[0].label is None
    # 无标签样本仍应对齐到 request（供 infer 使用 ttft）
    assert corpus2.samples[0].request_id == "rid-c1"


def test_corpus_save_load_roundtrip(tmp_path):
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"
    _write_transcript(
        projects,
        "conv-a",
        [("<timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>\nq",
          [{"text": "hello world"}])],
    )
    _write_structured_log(
        logs,
        [("2026-07-03 10:12:05.000", "Starting stream request", "rid-1", "conv-a", "model-x", None)],
    )
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [])
    corpus = build_corpus(projects_dir=projects, logs_dir=logs, tracking_db=tracking)

    out_dir = tmp_path / "blindtest"
    save_corpus(corpus, out_dir)
    loaded = load_corpus(out_dir)
    assert len(loaded.samples) == len(corpus.samples)
    assert loaded.samples[0].label == "model-x"
    assert loaded.samples[0].features == corpus.samples[0].features


def test_task_fingerprint_collision_skips_ambiguous():
    idx = LabelIndex()
    prompt = "You are generating ground-truth Cursor usage for Verkeep Verify blindtest (APP-12). " + (
        "x" * 40
    )
    fp = task_fingerprint(prompt)
    assert fp
    idx.set_task_model(fp, "composer-2.5-fast")
    idx.set_task_model(fp, "gpt-5.6-sol-medium")
    assert fp in idx.task_models_ambiguous
    assert fp not in idx.task_models


def test_conversation_overrides_win_over_mislabel(tmp_path):
    projects = tmp_path / "projects"
    logs = tmp_path / "logs"
    _write_transcript(
        projects,
        "subagent-a",
        [
            (
                "You are generating ground-truth Cursor usage for Verkeep Verify blindtest (APP-12). "
                + ("explain inventory gaps " * 8),
                [{"text": "answer"}],
            )
        ],
    )
    _write_structured_log(logs, [])
    tracking = tmp_path / "tracking.db"
    _write_tracking_db(tracking, [])
    corpus = build_corpus(
        projects_dir=projects,
        logs_dir=logs,
        tracking_db=tracking,
        conversation_overrides={"subagent-a": "composer-2.5-fast"},
    )
    assert len(corpus.samples) == 1
    assert corpus.samples[0].label == "composer-2.5-fast"
    assert corpus.samples[0].label_source == "launch_override"
