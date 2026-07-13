"""Cursor hook NDJSON event reader."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


@dataclass
class HookEvent:
    hook_event: Optional[str] = None
    received_at: Optional[str] = None
    conversation_id: Optional[str] = None
    generation_id: Optional[str] = None
    model: Optional[str] = None
    model_id: Optional[str] = None
    model_params: Optional[Dict[str, Any]] = None
    subagent_id: Optional[str] = None
    subagent_model: Optional[str] = None
    parent_conversation_id: Optional[str] = None
    status: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    task: Optional[str] = None
    transcript_path: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def default_hook_event_paths() -> List[Path]:
    home = Path.home() / ".ai-verify"
    return [home / "cursor-events.ndjson", home / "cursor-hook-probe.ndjson"]


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_cursor_id(value: Any) -> Optional[str]:
    """Sanitize Cursor/hook IDs that may include quotes or embedded newlines.

    Real Cursor hook payloads have been observed with values like:
    ``'call_SNF...\\nfc_014b...'`` — keep the first line only.
    """
    text = _str_or_none(value)
    if text is None:
        return None
    # Strip one layer of surrounding quotes if the whole value was quoted.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    # Cursor sometimes concatenates tool-call id + function-call id with a newline.
    for sep in ("\n", "\r", "\\n", "\\r"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return text or None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_hook_event(obj: Dict[str, Any]) -> Optional[HookEvent]:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        payload = obj

    hook_event = _str_or_none(obj.get("hook_event") or payload.get("hook_event"))
    received_at = _str_or_none(obj.get("received_at") or payload.get("received_at"))
    model_params = payload.get("model_params")
    if model_params is not None and not isinstance(model_params, dict):
        model_params = None

    return HookEvent(
        hook_event=hook_event,
        received_at=received_at,
        conversation_id=normalize_cursor_id(
            payload.get("conversation_id") or payload.get("conversationId")
        ),
        generation_id=normalize_cursor_id(
            payload.get("generation_id")
            or payload.get("generationId")
            or payload.get("request_id")
            or payload.get("requestId")
        ),
        model=_str_or_none(payload.get("model")),
        model_id=_str_or_none(payload.get("model_id") or payload.get("modelId")),
        model_params=model_params,
        subagent_id=normalize_cursor_id(
            payload.get("subagent_id") or payload.get("subagentId")
        ),
        subagent_model=_str_or_none(
            payload.get("subagent_model") or payload.get("subagentModel")
        ),
        parent_conversation_id=normalize_cursor_id(
            payload.get("parent_conversation_id") or payload.get("parentConversationId")
        ),
        status=_str_or_none(payload.get("status")),
        input_tokens=_int_or_none(
            payload.get("input_tokens") or payload.get("inputTokens")
        ),
        output_tokens=_int_or_none(
            payload.get("output_tokens") or payload.get("outputTokens")
        ),
        duration_ms=_int_or_none(
            payload.get("duration_ms") or payload.get("durationMs")
        ),
        task=_str_or_none(payload.get("task")),
        transcript_path=_str_or_none(
            payload.get("transcript_path") or payload.get("transcriptPath")
        ),
        raw=obj,
    )


def iter_hook_events(path: Path, start_offset: int = 0) -> Iterator[HookEvent]:
    """Yield parseable hook events from an NDJSON file, skipping bad lines."""
    if not path.is_file():
        return

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(start_offset)
        while True:
            line = fh.readline()
            if not line:
                break
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            event = _parse_hook_event(obj)
            if event:
                yield event


def read_hook_events(path: Path, start_offset: int = 0) -> Tuple[List[HookEvent], int]:
    events = list(iter_hook_events(path, start_offset=start_offset))
    try:
        new_offset = path.stat().st_size
    except OSError:
        new_offset = start_offset
    return events, new_offset
