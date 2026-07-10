"""
Cursor structured log + renderer.log 解析器（只读元数据）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

LOG_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[[^\]]+\] ")
BUILD_REQUESTED_MODEL_RE = re.compile(
    r"\[buildRequestedModel\]\s+"
    r"composerId=(?P<composerId>\S+)\s+"
    r"catalogModelId=(?P<catalogModelId>\S+)\s+"
    r"(?:idSource=\S+\s+)?"
    r"composerModelName=(?P<composerModelName>\S+)\s+"
    r"selectedModelIds=(?P<selectedModelIds>\S+)"
)
REQUEST_TRACE_KV_RE = re.compile(r"(\w+)=([\w-]+)")


@dataclass
class LogEvent:
    """统一日志事件。"""

    event_type: str
    task_id: Optional[str] = None
    request_id: Optional[str] = None
    selected_model: Optional[str] = None
    catalog_model_id: Optional[str] = None
    unified_mode: Optional[str] = None
    outcome: Optional[str] = None
    model_intent: Optional[str] = None
    ttft_ms: Optional[float] = None
    error_text: Optional[str] = None
    timestamp: Optional[datetime] = None
    raw_message: Optional[str] = None
    source_file: Optional[str] = None
    line_offset: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


def _parse_log_timestamp(line: str) -> Optional[datetime]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def _extract_json_payload(line: str) -> Optional[Dict[str, Any]]:
    idx = line.find("{")
    if idx < 0:
        return None
    try:
        return json.loads(line[idx:])
    except json.JSONDecodeError:
        return None


def _parse_structured_json(
    payload: Dict[str, Any], line: str, source: str, offset: int
) -> Optional[LogEvent]:
    message = payload.get("message", "")
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    ts = _parse_log_timestamp(line)
    request_id = metadata.get("requestId") or metadata.get("request_id")
    task_id = (
        metadata.get("composerId")
        or metadata.get("conversation_id")
        or metadata.get("conversationId")
    )

    if message == "Composer state loaded":
        return LogEvent(
            event_type="composer_state",
            task_id=str(task_id) if task_id else None,
            request_id=str(request_id) if request_id else None,
            selected_model=metadata.get("modelName"),
            unified_mode=metadata.get("unifiedMode"),
            timestamp=ts,
            raw_message=message,
            source_file=source,
            line_offset=offset,
            extra={"trace_id": metadata.get("trace_id") or metadata.get("traceId")},
        )

    if message == "Starting stream request":
        return LogEvent(
            event_type="stream_start",
            task_id=str(task_id) if task_id else None,
            request_id=str(request_id) if request_id else None,
            selected_model=metadata.get("modelName"),
            unified_mode=metadata.get("unifiedMode"),
            timestamp=ts,
            raw_message=message,
            source_file=source,
            line_offset=offset,
            extra={
                "conversation_length": metadata.get("conversationLength"),
                "trace_id": metadata.get("trace_id") or metadata.get("traceId"),
            },
        )

    if message == "agent.turn.outcome":
        ttft = metadata.get("ttft_ms")
        try:
            ttft_val = float(ttft) if ttft is not None else None
        except (TypeError, ValueError):
            ttft_val = None
        return LogEvent(
            event_type="turn_outcome",
            task_id=str(task_id) if task_id else None,
            request_id=str(request_id) if request_id else None,
            selected_model=metadata.get("model_intent"),
            model_intent=metadata.get("model_intent"),
            unified_mode=metadata.get("unifiedMode"),
            outcome=metadata.get("outcome"),
            ttft_ms=ttft_val,
            error_text=metadata.get("error_text"),
            timestamp=ts,
            raw_message=message,
            source_file=source,
            line_offset=offset,
            extra={"trace_id": metadata.get("trace_id") or metadata.get("traceId")},
        )

    return None


def _parse_request_trace_line(
    line: str, source: str, offset: int
) -> Optional[LogEvent]:
    if "cursor.requestTraces.log" not in source:
        return None
    fields = dict(REQUEST_TRACE_KV_RE.findall(line))
    request_id = fields.get("requestId") or fields.get("request_id")
    task_id = fields.get("composerId") or fields.get("composer_id")
    trace_id = fields.get("trace_id") or fields.get("traceId")
    if not (request_id and task_id and trace_id):
        return None
    return LogEvent(
        event_type="request_trace",
        task_id=task_id,
        request_id=request_id,
        timestamp=_parse_log_timestamp(line),
        raw_message="cursor.requestTraces",
        source_file=source,
        line_offset=offset,
        extra={"trace_id": trace_id},
    )


def _parse_renderer_line(line: str, source: str, offset: int) -> Optional[LogEvent]:
    if "[buildRequestedModel]" not in line:
        return None
    m = BUILD_REQUESTED_MODEL_RE.search(line)
    if not m:
        return None
    return LogEvent(
        event_type="build_requested_model",
        task_id=m.group("composerId"),
        catalog_model_id=m.group("catalogModelId"),
        selected_model=m.group("composerModelName"),
        timestamp=_parse_log_timestamp(line),
        raw_message="[buildRequestedModel]",
        source_file=source,
        line_offset=offset,
        extra={"selected_model_ids": m.group("selectedModelIds")},
    )


def parse_log_line(line: str, source: str = "", offset: int = 0) -> Optional[LogEvent]:
    """解析单行 structured log 或 renderer.log。"""
    line = line.rstrip("\n")
    if not line.strip():
        return None

    trace_event = _parse_request_trace_line(line, source, offset)
    if trace_event:
        return trace_event

    if "[buildRequestedModel]" in line:
        return _parse_renderer_line(line, source, offset)

    payload = _extract_json_payload(line)
    if payload:
        return _parse_structured_json(payload, line, source, offset)
    return None


def iter_log_events(
    path: Path,
    start_offset: int = 0,
) -> Iterator[LogEvent]:
    """从指定字节偏移流式读取日志事件。"""
    offset = start_offset
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(start_offset)
        while True:
            line_start = fh.tell()
            line = fh.readline()
            if not line:
                break
            event = parse_log_line(line, source=str(path), offset=line_start)
            if event:
                yield event


def read_log_events(
    path: Path,
    start_offset: int = 0,
) -> tuple[List[LogEvent], int]:
    """读取日志事件并返回新偏移。"""
    try:
        if (
            path.name == "cursor.requestTraces.log"
            and path.stat().st_size > 50 * 1024 * 1024
        ):
            return [], path.stat().st_size
    except OSError:
        return [], start_offset
    events = list(iter_log_events(path, start_offset=start_offset))
    try:
        new_offset = path.stat().st_size
    except OSError:
        new_offset = start_offset
    return events, new_offset
