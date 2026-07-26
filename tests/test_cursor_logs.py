"""Cursor 日志解析测试"""

from pathlib import Path

from verkee_verify.cursor_logs import parse_log_line, read_log_events

FIXTURE = Path(__file__).parent / "fixtures" / "cursor" / "structured_log_sample.log"


def test_parse_composer_state_loaded():
    line = (
        '2026-07-09 09:45:13.533 [info] {"message":"Composer state loaded",'
        '"metadata":{"requestId":"rid-1","composerId":"task-1","modelName":"grok-4.5","unifiedMode":"agent"}}'
    )
    ev = parse_log_line(line)
    assert ev is not None
    assert ev.event_type == "composer_state"
    assert ev.task_id == "task-1"
    assert ev.request_id == "rid-1"
    assert ev.selected_model == "grok-4.5"
    assert ev.unified_mode == "agent"


def test_parse_turn_outcome():
    line = (
        '2026-07-09 09:47:42.145 [info] {"message":"agent.turn.outcome",'
        '"metadata":{"model_intent":"grok-4.5","request_id":"rid-1",'
        '"conversation_id":"task-1","outcome":"success","ttft_ms":"20107.5"}}'
    )
    ev = parse_log_line(line)
    assert ev is not None
    assert ev.event_type == "turn_outcome"
    assert ev.outcome == "success"
    assert ev.ttft_ms == 20107.5


def test_parse_turn_outcome_multitask_trace():
    line = (
        '2026-07-09 09:47:42.145 [info] {"message":"agent.turn.outcome",'
        '"metadata":{"model_intent":"default","trace_id":"trace-1",'
        '"conversation_id":"task-1","request_id":"rid-1","outcome":"success",'
        '"unifiedMode":"multitask"}}'
    )
    ev = parse_log_line(line)
    assert ev is not None
    assert ev.extra["trace_id"] == "trace-1"


def test_parse_request_trace_line():
    line = (
        "2026-07-09 09:47:40.000 [info] requestId=rid-1 "
        "composerId=task-1 trace_id=trace-1"
    )
    ev = parse_log_line(line, source="/tmp/cursor.requestTraces.log")
    assert ev is not None
    assert ev.event_type == "request_trace"
    assert ev.task_id == "task-1"
    assert ev.request_id == "rid-1"
    assert ev.extra["trace_id"] == "trace-1"


def test_parse_build_requested_model():
    line = (
        "2026-07-03 10:11:02.448 [info] [buildRequestedModel] composerId=task-1 "
        "catalogModelId=claude-fable-5 composerModelName=claude-fable-5 selectedModelIds=claude-fable-5"
    )
    ev = parse_log_line(line)
    assert ev is not None
    assert ev.event_type == "build_requested_model"
    assert ev.catalog_model_id == "claude-fable-5"


def test_read_fixture_log():
    events, offset = read_log_events(FIXTURE)
    types = {e.event_type for e in events}
    assert "composer_state" in types
    assert "turn_outcome" in types
    assert "build_requested_model" in types
    assert offset >= FIXTURE.stat().st_size
