"""
Cursor Auto Usage — 导入编排、合并、聚合统计。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rich.table import Table

from verkee_verify.cursor_hook_events import default_hook_event_paths, read_hook_events
from verkee_verify.cursor_logs import read_log_events
from verkee_verify.providers.cursor import (
    CursorPaths,
    _file_inode,
    discover_cursor_paths,
    header_display_title,
    load_composer_headers,
    probe_structured_logs,
    read_ai_code_hashes,
    read_conversation_summaries,
    scan_subagent_relations,
)
from verkee_verify.storage.database import Database


def parse_since(since: str) -> datetime:
    """解析 --since 参数（如 7d, 30d, 24h）。"""
    unit = since[-1]
    value = int(since[:-1])
    if unit == "h":
        delta = timedelta(hours=value)
    elif unit == "d":
        delta = timedelta(days=value)
    elif unit == "w":
        delta = timedelta(weeks=value)
    else:
        delta = timedelta(days=7)
    return datetime.now() - delta


def _route_kind(selected: Optional[str]) -> str:
    if selected in (None, "", "default"):
        return "auto"
    return "specific"


def _is_real_model(model: Optional[str]) -> bool:
    return bool(model and model not in ("", "default"))


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class CursorModelEvent:
    task_id: str
    request_id: Optional[str]
    parent_task_id: Optional[str] = None
    selected_model: Optional[str] = None
    resolved_model: Optional[str] = None
    route_kind: str = "unknown"
    event_source: str = "structured_log"
    confidence: str = "low"
    generated_units: int = 0
    ttft_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    status: str = "unknown"
    error_text: Optional[str] = None
    unified_mode: Optional[str] = None
    timestamp: Optional[str] = None


def _hook_resolved_model(hook: Optional[Dict[str, Any]]) -> Optional[str]:
    """Prefer normalized model_id over display model slug from hook payloads."""
    if not hook:
        return None
    for key in ("model_id", "model"):
        if _is_real_model(hook.get(key)):
            return hook[key]
    return None


def merge_turn(
    request_id: Optional[str],
    task_id: str,
    sources: Dict[str, Any],
    parent_task_id: Optional[str] = None,
) -> CursorModelEvent:
    """按文档规则合并单条 turn 的多源证据。"""
    selected = sources.get("selected_model")
    route_kind = _route_kind(selected)

    resolved = None
    confidence = "low"
    event_source = "structured_log"

    tracking = sources.get("ai_tracking")
    hook = sources.get("hook")
    summary = sources.get("conversation_summary")
    hook_model = _hook_resolved_model(hook)
    if tracking and tracking.get("model"):
        tracking_model = tracking["model"]
        if tracking_model != "default":
            resolved = tracking_model
            confidence = "high"
            event_source = "ai_tracking_db"
        elif hook_model:
            resolved = hook_model
            confidence = "high"
            event_source = "hook"
        elif summary and _is_real_model(summary.get("model")):
            resolved = summary["model"]
            confidence = "medium"
            event_source = "conversation_summary"
    elif hook_model:
        resolved = hook_model
        confidence = "high"
        event_source = "hook"
    elif sources.get("catalog_model_id"):
        catalog = sources["catalog_model_id"]
        if catalog != "default":
            resolved = catalog
            confidence = "medium-high"
            event_source = "renderer_log"
    elif selected and selected != "default":
        resolved = selected
        confidence = "medium"
        event_source = "structured_log"
    elif summary and _is_real_model(summary.get("model")):
        resolved = summary["model"]
        confidence = "medium"
        event_source = "conversation_summary"

    status = sources.get("outcome") or sources.get("status") or "unknown"
    ttft = sources.get("ttft_ms")
    if ttft is not None:
        try:
            ttft = int(float(ttft))
        except (TypeError, ValueError):
            ttft = None

    generated_units = int(sources.get("generated_units") or 0)
    if tracking and tracking.get("count"):
        generated_units = max(generated_units, int(tracking.get("count") or 0))

    input_tokens = sources.get("input_tokens")
    output_tokens = sources.get("output_tokens")
    duration_ms = sources.get("duration_ms")
    if hook:
        if input_tokens is None:
            input_tokens = hook.get("input_tokens")
        if output_tokens is None:
            output_tokens = hook.get("output_tokens")
        if duration_ms is None:
            duration_ms = hook.get("duration_ms")

    def _as_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    return CursorModelEvent(
        task_id=task_id,
        request_id=request_id,
        parent_task_id=parent_task_id,
        selected_model=selected,
        resolved_model=resolved,
        route_kind=route_kind,
        event_source=event_source,
        confidence=confidence,
        generated_units=generated_units,
        ttft_ms=ttft,
        input_tokens=_as_int(input_tokens),
        output_tokens=_as_int(output_tokens),
        duration_ms=_as_int(duration_ms),
        status=status,
        error_text=sources.get("error_text"),
        unified_mode=sources.get("unified_mode"),
        timestamp=sources.get("timestamp"),
    )


@dataclass
class ImportResult:
    tasks_upserted: int = 0
    events_upserted: int = 0
    log_files_processed: int = 0
    tracking_rows: int = 0
    hook_events_seen: int = 0
    hook_events_resolved: int = 0


@dataclass
class TaskSummary:
    task_id: str
    title: Optional[str] = None
    mode: str = "unknown"
    route_kind: str = "unknown"
    request_count: int = 0
    code_unit_count: int = 0
    subagent_count: int = 0
    started_at: Optional[str] = None
    model_request_shares: Dict[str, float] = field(default_factory=dict)


@dataclass
class PeriodUsageReport:
    since_label: str
    task_count: int = 0
    auto_task_count: int = 0
    mixed_task_count: int = 0
    total_requests: int = 0
    total_output_units: int = 0
    resolved_requests: int = 0
    resolution_rate: float = 0.0
    request_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    output_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    latest_report: Optional["TaskUsageReport"] = None
    tasks: List[TaskSummary] = field(default_factory=list)


@dataclass
class TaskUsageReport:
    task_id: str
    title: Optional[str] = None
    mode: str = "unknown"
    route_kind: str = "unknown"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    request_count: int = 0
    code_unit_count: int = 0
    subagent_count: int = 0
    resolved_requests: int = 0
    resolution_rate: float = 0.0
    request_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    output_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Dual-track Auto transparency: factual telemetry vs blindtest inference.
    factual_request_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    factual_output_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    inferred_request_shares: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    coverage: float = 0.0  # (fact ∪ inferred) / requests for auto/mixed
    pending_infer_count: int = 0
    status_counts: Dict[str, int] = field(default_factory=dict)
    confidence_counts: Dict[str, int] = field(default_factory=dict)
    subagents: List[Dict[str, Any]] = field(default_factory=list)
    per_request: List[Dict[str, Any]] = field(default_factory=list)
    # Unified product view: call-count mix; confirmed/estimated only for detail.
    model_mix_v2: Dict[str, Any] = field(default_factory=dict)


def task_summary_to_dict(summary: TaskSummary) -> Dict[str, Any]:
    """Serialize TaskSummary for CLI --json / extension bridge."""
    return asdict(summary)


def task_report_to_dict(
    report: TaskUsageReport, *, include_per_request: bool = False
) -> Dict[str, Any]:
    """Serialize TaskUsageReport for CLI --json / extension bridge.

    Omits per_request by default (heavy); plugin panels use share aggregates.
    Always includes model_mix_v2 when present; keeps legacy dual-track fields.
    """
    payload = asdict(report)
    if not include_per_request:
        payload.pop("per_request", None)
    if not payload.get("model_mix_v2"):
        payload["model_mix_v2"] = _empty_model_mix_v2()
    payload["disclaimer"] = (
        "inferred tracks are not cloud routing ground truth; "
        "only factual_* come from telemetry; "
        "prefer model_mix_v2 for product UI"
    )
    return payload


PENDING_INFER_BUCKET = "pending-infer"
# Legacy alias kept for test/fixture compatibility during migration.
AUTO_OPAQUE_BUCKET = "auto-opaque"
UNKNOWN_MIX_LABEL = "未识别"


class CursorUsageImporter:
    def __init__(
        self,
        db: Optional[Database] = None,
        paths: Optional[CursorPaths] = None,
        hook_event_paths: Optional[List[Any]] = None,
    ):
        self.db = db or Database()
        self.paths = paths or discover_cursor_paths()
        self.hook_event_paths = [
            p if isinstance(p, Path) else Path(str(p))
            for p in (
                hook_event_paths
                if hook_event_paths is not None
                else default_hook_event_paths()
            )
        ]

    def import_all(
        self,
        since: Optional[datetime] = None,
        full: bool = False,
    ) -> ImportResult:
        result = ImportResult()
        since_iso = since.isoformat() if since else None

        subagent_map = (
            scan_subagent_relations(self.paths.projects_dir)
            if self.paths.projects_dir
            else {}
        )
        headers = (
            load_composer_headers(self.paths.global_state_db)
            if self.paths.global_state_db
            else {}
        )
        summaries = (
            read_conversation_summaries(self.paths.ai_tracking_db)
            if self.paths.ai_tracking_db
            else {}
        )

        # 1) ai-tracking hashes
        tracking_by_request: Dict[Tuple[str, str], Dict[str, Any]] = {}
        hash_count_by_request: Dict[Tuple[str, str, str], int] = defaultdict(int)
        if self.paths.ai_tracking_db:
            rows = read_ai_code_hashes(self.paths.ai_tracking_db, since=since)
            result.tracking_rows = len(rows)
            for row in rows:
                task_id = row.get("conversationId")
                request_id = row.get("requestId")
                model = row.get("model")
                if not task_id:
                    continue
                if request_id and model:
                    hash_count_by_request[(task_id, request_id, model)] += 1

            for (task_id, request_id, model), count in hash_count_by_request.items():
                key = (task_id, request_id)
                prev = tracking_by_request.get(key)
                if not prev or count > prev.get("count", 0):
                    tracking_by_request[key] = {
                        "model": model,
                        "count": count,
                        "timestamp": None,
                    }

        # 2) structured + renderer logs
        turn_data: Dict[Tuple[str, str], Dict[str, Any]] = {}
        task_meta: Dict[str, Dict[str, Any]] = {}

        log_files = (
            probe_structured_logs(self.paths.logs_dir) if self.paths.logs_dir else []
        )
        all_log_events = []
        for log_path in log_files:
            state = self.db.get_cursor_import_state(str(log_path))
            start_offset = 0 if full else int(state.get("last_offset") or 0)
            inode = _file_inode(log_path)
            if (
                not full
                and state.get("last_inode")
                and inode
                and state["last_inode"] != inode
            ):
                start_offset = 0

            events, new_offset = read_log_events(log_path, start_offset=start_offset)
            result.log_files_processed += 1
            all_log_events.extend(events)

            self.db.save_cursor_import_state(
                str(log_path), new_offset, inode or "", datetime.now().isoformat()
            )

        trace_map: Dict[str, Tuple[str, str]] = {}
        for ev in all_log_events:
            if ev.event_type != "request_trace":
                continue
            trace_id = ev.extra.get("trace_id")
            if trace_id and ev.task_id and ev.request_id:
                trace_map[str(trace_id)] = (ev.task_id, ev.request_id)

        for ev in all_log_events:
            if since and ev.timestamp and ev.timestamp < since:
                continue
            trace_id = ev.extra.get("trace_id")
            if (not ev.task_id or not ev.request_id) and trace_id:
                mapped = trace_map.get(str(trace_id))
                if mapped:
                    ev.task_id = ev.task_id or mapped[0]
                    ev.request_id = ev.request_id or mapped[1]
            if not ev.task_id:
                continue

            tid = ev.task_id
            meta = task_meta.setdefault(tid, {})
            if ev.unified_mode:
                meta["mode"] = ev.unified_mode
            if ev.timestamp:
                ts = ev.timestamp.isoformat()
                if not meta.get("started_at") or ts < meta["started_at"]:
                    meta["started_at"] = ts
                if not meta.get("ended_at") or ts > meta["ended_at"]:
                    meta["ended_at"] = ts

            if ev.event_type == "build_requested_model":
                if ev.catalog_model_id:
                    meta.setdefault("catalog_entries", []).append(
                        (ev.timestamp, ev.catalog_model_id)
                    )
                continue
            if ev.event_type == "request_trace":
                continue

            if not ev.request_id:
                continue

            key = (tid, ev.request_id)
            bucket = turn_data.setdefault(
                key, {"task_id": tid, "request_id": ev.request_id}
            )

            if ev.selected_model:
                bucket["selected_model"] = ev.selected_model
            if ev.unified_mode:
                bucket["unified_mode"] = ev.unified_mode
            if ev.outcome:
                bucket["outcome"] = ev.outcome
            if ev.ttft_ms is not None:
                bucket["ttft_ms"] = ev.ttft_ms
            if ev.error_text:
                bucket["error_text"] = ev.error_text
            if ev.timestamp:
                bucket["timestamp"] = ev.timestamp.isoformat()
            if ev.catalog_model_id:
                bucket["catalog_model_id"] = ev.catalog_model_id

        # merge renderer catalog into turns by task, respecting turn time
        for key, bucket in turn_data.items():
            tid = bucket["task_id"]
            if not bucket.get("catalog_model_id"):
                meta = task_meta.get(tid, {})
                entries = [
                    (ts, model)
                    for ts, model in meta.get("catalog_entries", [])
                    if model
                ]
                turn_ts = _parse_iso_datetime(bucket.get("timestamp"))
                selected_entry = None
                if entries and turn_ts:
                    previous = [
                        (ts, model) for ts, model in entries if ts and ts <= turn_ts
                    ]
                    if previous:
                        selected_entry = max(previous, key=lambda x: x[0])
                    else:
                        nearest = min(
                            ((abs(ts - turn_ts), model) for ts, model in entries if ts),
                            default=None,
                            key=lambda x: x[0],
                        )
                        if nearest and nearest[0] <= timedelta(minutes=10):
                            selected_entry = (turn_ts, nearest[1])
                elif entries:
                    selected_entry = entries[-1]
                if selected_entry:
                    bucket["catalog_model_id"] = selected_entry[1]

        # attach tracking units
        for key, bucket in turn_data.items():
            tracking = tracking_by_request.get(key)
            if tracking:
                bucket["ai_tracking"] = tracking
                bucket["generated_units"] = tracking.get("count", 0)

        # also create events from tracking-only requests not in logs
        for key, tracking in tracking_by_request.items():
            if key not in turn_data:
                turn_data[key] = {
                    "task_id": key[0],
                    "request_id": key[1],
                    "ai_tracking": tracking,
                    "generated_units": tracking.get("count", 0),
                    "timestamp": tracking.get("timestamp"),
                }

        # hook NDJSON events
        for hook_path in self.hook_event_paths:
            if not hook_path.is_file():
                continue
            state = self.db.get_cursor_import_state(str(hook_path))
            start_offset = 0 if full else int(state.get("last_offset") or 0)
            inode = _file_inode(hook_path)
            if (
                not full
                and state.get("last_inode")
                and inode
                and state["last_inode"] != inode
            ):
                start_offset = 0

            hook_events, new_offset = read_hook_events(
                hook_path, start_offset=start_offset
            )
            for hook_ev in hook_events:
                result.hook_events_seen += 1
                is_subagent = hook_ev.hook_event in ("subagentStart", "subagentStop")
                if is_subagent:
                    # subagentStop often omits subagent_model; fall back to model fields.
                    # Never treat these as parent-task turns (avoids bubble IDs as top-level).
                    sub_model = (
                        hook_ev.subagent_model
                        or hook_ev.model_id
                        or hook_ev.model
                    )
                    tid = hook_ev.subagent_id
                    parent = hook_ev.parent_conversation_id or hook_ev.conversation_id
                    if not (tid and parent and _is_real_model(sub_model)):
                        continue
                    rid = (
                        hook_ev.generation_id
                        or f"hook-{tid}-{hook_ev.received_at or 'unknown'}"
                    )
                    key = (tid, rid)
                    bucket = turn_data.setdefault(
                        key, {"task_id": tid, "request_id": rid}
                    )
                    bucket["selected_model"] = sub_model
                    bucket["hook"] = {
                        "model": sub_model,
                        "model_id": hook_ev.model_id or sub_model,
                        "input_tokens": hook_ev.input_tokens,
                        "output_tokens": hook_ev.output_tokens,
                        "duration_ms": hook_ev.duration_ms,
                    }
                    bucket["parent_task_id"] = parent
                    bucket["timestamp"] = hook_ev.received_at
                    bucket["status"] = hook_ev.status or bucket.get("status")
                    if hook_ev.input_tokens is not None:
                        bucket["input_tokens"] = hook_ev.input_tokens
                    if hook_ev.output_tokens is not None:
                        bucket["output_tokens"] = hook_ev.output_tokens
                    if hook_ev.duration_ms is not None:
                        bucket["duration_ms"] = hook_ev.duration_ms
                    result.hook_events_resolved += 1
                    task_meta.setdefault(parent, {})
                    continue

                hook_model = hook_ev.model_id or hook_ev.model
                if not (hook_ev.conversation_id and _is_real_model(hook_model)):
                    continue
                rid = hook_ev.generation_id or (
                    f"hook-{hook_ev.conversation_id}-{hook_ev.received_at or 'unknown'}"
                )
                key = (hook_ev.conversation_id, rid)
                bucket = turn_data.setdefault(
                    key, {"task_id": hook_ev.conversation_id, "request_id": rid}
                )
                if hook_ev.model:
                    bucket["selected_model"] = hook_ev.model
                bucket["hook"] = {
                    "model": hook_model,
                    "model_id": hook_ev.model_id or hook_model,
                    "input_tokens": hook_ev.input_tokens,
                    "output_tokens": hook_ev.output_tokens,
                    "duration_ms": hook_ev.duration_ms,
                }
                bucket["timestamp"] = bucket.get("timestamp") or hook_ev.received_at
                bucket["status"] = hook_ev.status or bucket.get("status")
                if hook_ev.input_tokens is not None:
                    bucket["input_tokens"] = hook_ev.input_tokens
                if hook_ev.output_tokens is not None:
                    bucket["output_tokens"] = hook_ev.output_tokens
                if hook_ev.duration_ms is not None:
                    bucket["duration_ms"] = hook_ev.duration_ms
                result.hook_events_resolved += 1

            self.db.save_cursor_import_state(
                str(hook_path), new_offset, inode or "", datetime.now().isoformat()
            )

        # conversation_summaries fallback for tasks whose other evidence is default
        for bucket in turn_data.values():
            summary = summaries.get(bucket["task_id"])
            if summary:
                bucket["conversation_summary"] = summary
                if summary.get("mode"):
                    task_meta.setdefault(bucket["task_id"], {})["mode"] = summary[
                        "mode"
                    ]

        # 3) upsert events
        events_saved = 0
        tasks_seen: Set[str] = set()
        child_task_ids: Set[str] = set()
        child_parent: Dict[str, str] = {}

        self.db.purge_malformed_cursor_ids()

        for (tid, rid), sources in turn_data.items():
            parent = sources.get("parent_task_id") or subagent_map.get(tid)
            merged = merge_turn(rid, tid, sources, parent_task_id=parent)
            event_id = str(uuid.uuid4())
            self.db.save_cursor_model_event(
                {
                    "id": event_id,
                    "task_id": tid,
                    "parent_task_id": parent,
                    "request_id": rid,
                    "selected_model": merged.selected_model,
                    "resolved_model": merged.resolved_model,
                    "route_kind": merged.route_kind,
                    "event_source": merged.event_source,
                    "confidence": merged.confidence,
                    "generated_units": merged.generated_units,
                    "input_tokens": merged.input_tokens,
                    "output_tokens": merged.output_tokens,
                    "ttft_ms": merged.ttft_ms,
                    "latency_ms": merged.duration_ms,
                    "status": merged.status,
                    "error_text": merged.error_text,
                    "timestamp": merged.timestamp,
                }
            )
            events_saved += 1
            if parent:
                child_task_ids.add(tid)
                child_parent[tid] = parent
                tasks_seen.add(parent)
            else:
                tasks_seen.add(tid)

        # Drop stale top-level rows for subagent / malformed child IDs.
        self.db.delete_cursor_tasks(sorted(child_task_ids))

        # 4) upsert tasks (parents only — subagents stay as events under parent)
        tasks_saved = 0
        for tid in tasks_seen:
            if tid in child_task_ids:
                continue
            header = headers.get(tid, {})
            meta = task_meta.get(tid, {})
            summary = summaries.get(tid) or {}
            title = (
                header_display_title(header)
                or summary.get("title")
                or summary.get("tldr")
            )
            mode = meta.get("mode") or header.get("unifiedMode") or "unknown"

            events = self.db.get_cursor_events_for_task(tid, since=since_iso)
            request_ids = {e["request_id"] for e in events if e.get("request_id")}
            code_units = sum(int(e.get("generated_units") or 0) for e in events)
            route_kinds = {e.get("route_kind") for e in events if e.get("route_kind")}
            if len(route_kinds) > 1:
                route_kind = "mixed"
            elif route_kinds:
                route_kind = next(iter(route_kinds))
            else:
                route_kind = "unknown"

            sub_ids = {sid for sid, pid in subagent_map.items() if pid == tid}
            sub_ids |= {sid for sid, pid in child_parent.items() if pid == tid}
            sub_count = len(sub_ids)
            started = meta.get("started_at")
            ended = meta.get("ended_at")
            if not started and events:
                ts_list = [e["timestamp"] for e in events if e.get("timestamp")]
                if ts_list:
                    started = min(ts_list)
                    ended = max(ts_list)

            self.db.save_cursor_task(
                {
                    "task_id": tid,
                    "title": title,
                    "mode": mode,
                    "route_kind": route_kind,
                    "started_at": started,
                    "ended_at": ended,
                    "request_count": len(request_ids),
                    "code_unit_count": code_units,
                    "subagent_count": sub_count,
                }
            )
            tasks_saved += 1

        # tasks from headers only (no events yet)
        for cid, header in headers.items():
            if cid in tasks_seen:
                continue
            created = header.get("createdAt") or header.get("lastUpdatedAt")
            if since_iso and created and str(created) < since_iso:
                continue
            summary = summaries.get(cid) or {}
            self.db.save_cursor_task(
                {
                    "task_id": cid,
                    "title": header_display_title(header)
                    or summary.get("title")
                    or summary.get("tldr"),
                    "mode": header.get("unifiedMode") or "unknown",
                    "route_kind": "unknown",
                    "started_at": created,
                    "request_count": 0,
                    "code_unit_count": 0,
                    "subagent_count": int(header.get("numSubComposers") or 0),
                }
            )
            tasks_saved += 1

        result.tasks_upserted = tasks_saved
        result.events_upserted = events_saved
        return result


def _bar(pct: float, width: int = 20) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _is_resolved_model(model: Optional[str]) -> bool:
    return bool(model and model not in ("", "default"))


def _bucket_label(ev: Dict[str, Any]) -> str:
    """Map event to display bucket: real model, pending-infer, or unknown.

    ``pending-infer`` replaces the former auto-opaque terminal bucket: Auto turns
    without a factual resolved model should be filled by the inference track.
    """
    resolved = ev.get("resolved_model")
    if _is_resolved_model(resolved):
        return resolved  # type: ignore[return-value]

    selected = ev.get("selected_model")
    if _is_resolved_model(selected):
        return selected  # type: ignore[return-value]

    if ev.get("route_kind") == "auto":
        return PENDING_INFER_BUCKET
    return "unknown"


def _shares_from_counts(counts: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
    total = sum(counts.values()) or 1
    return {
        m: {"pct": c / total * 100, "count": c}
        for m, c in sorted(counts.items(), key=lambda x: -x[1])
    }


def _load_inferred_by_request(db: Database, task_id: str) -> Dict[str, Dict[str, Any]]:
    """Map request_id -> latest blindtest inference row (non-null model)."""
    try:
        from verkee_verify.monitor.blindtest_view import get_inferred_view
    except ImportError:
        return {}
    view = get_inferred_view(db, task_id)
    if not view:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for pt in view.per_turn:
        if not pt.inferred_model or not pt.request_id:
            continue
        out[pt.request_id] = {
            "inferred_model": pt.inferred_model,
            "probability": pt.probability,
        }
    return out


def _load_inferred_for_tasks(
    db: Database, task_ids: List[str]
) -> Dict[tuple, Dict[str, Any]]:
    """Map (task_id, request_id) -> inference for a session scope."""
    out: Dict[tuple, Dict[str, Any]] = {}
    for tid in task_ids:
        for rid, info in _load_inferred_by_request(db, tid).items():
            out[(tid, rid)] = info
    return out


def _mix_display_label(bucket: str) -> str:
    if bucket in (PENDING_INFER_BUCKET, AUTO_OPAQUE_BUCKET, "unknown", ""):
        return UNKNOWN_MIX_LABEL
    return bucket


def _empty_model_mix_v2() -> Dict[str, Any]:
    return {
        "total_calls": 0,
        "subagent_calls": 0,
        "confirmed_count": 0,
        "estimated_count": 0,
        "unknown_count": 0,
        "composition": "confirmed_only",
        "models": {},
    }


def _build_model_mix_v2(
    *,
    confirmed_by_model: Dict[str, int],
    estimated_by_model: Dict[str, int],
    unknown_count: int,
    subagent_calls: int,
) -> Dict[str, Any]:
    """Unified call-count composition; confirmed/estimated only for detail folds."""
    models: Dict[str, Dict[str, Any]] = {}
    for m in set(confirmed_by_model) | set(estimated_by_model):
        if m == UNKNOWN_MIX_LABEL:
            continue
        c = int(confirmed_by_model.get(m, 0))
        e = int(estimated_by_model.get(m, 0))
        models[m] = {
            "call_count": c + e,
            "confirmed_count": c,
            "estimated_count": e,
            "pct": 0.0,
        }
    if unknown_count > 0:
        models[UNKNOWN_MIX_LABEL] = {
            "call_count": unknown_count,
            "confirmed_count": 0,
            "estimated_count": 0,
            "pct": 0.0,
        }

    total = sum(v["call_count"] for v in models.values()) or 0
    denom = total or 1
    for v in models.values():
        v["pct"] = v["call_count"] / denom * 100.0

    models_sorted = dict(
        sorted(models.items(), key=lambda item: (-item[1]["call_count"], item[0]))
    )
    confirmed_total = sum(confirmed_by_model.values())
    estimated_total = sum(estimated_by_model.values())
    if unknown_count > 0:
        composition = "partial"
    elif estimated_total > 0:
        composition = "includes_estimates"
    else:
        composition = "confirmed_only"

    return {
        "total_calls": confirmed_total + estimated_total + unknown_count,
        "subagent_calls": subagent_calls,
        "confirmed_count": confirmed_total,
        "estimated_count": estimated_total,
        "unknown_count": unknown_count,
        "composition": composition,
        "models": models_sorted,
    }


def aggregate_task(
    db: Database, task_id: str, *, auto_infer: bool = True
) -> Optional[TaskUsageReport]:
    """聚合单任务用量报告（根任务 + 一层子代理）。

    ``auto_infer``: 对仍有 pending-infer 的 Auto/Mixed 任务，在已训练盲测模型时
    自动写入 ``blindtest_inferences``（不修改 ``resolved_model``）。
    """
    task = db.get_cursor_task(task_id)
    if not task:
        tasks = db.list_cursor_tasks(limit=500)
        matches = [t for t in tasks if t["task_id"].startswith(task_id)]
        if len(matches) == 1:
            task_id = matches[0]["task_id"]
            task = matches[0]
        elif matches:
            matches.sort(key=lambda t: (-t.get("request_count", 0), -len(t["task_id"])))
            task = matches[0]
            task_id = task["task_id"]
        else:
            return None

    task_id = task["task_id"]
    subagents = db.get_cursor_subagents(task_id)
    child_ids = [s["task_id"] for s in subagents if s.get("task_id")]
    session_task_ids = [task_id, *child_ids]

    if auto_infer:
        try:
            from verkee_verify.monitor.blindtest_infer import ensure_task_inferences

            if task.get("route_kind") in ("auto", "mixed"):
                ensure_task_inferences(db, task_id)
            for cid in child_ids:
                try:
                    ensure_task_inferences(db, cid)
                except Exception:
                    pass
        except Exception:
            pass

    events = db.get_cursor_events_for_session(task_id)
    if not events:
        return TaskUsageReport(
            task_id=task_id,
            title=task.get("title"),
            mode=task.get("mode", "unknown"),
            model_mix_v2=_empty_model_mix_v2(),
        )

    # Dedupe by (task_id, request_id) so child request ids cannot collide with parent.
    by_request: Dict[tuple, Dict[str, Any]] = {}
    conf_rank = {"high": 4, "medium-high": 3, "medium": 2, "low": 1}
    for ev in events:
        tid = ev.get("task_id") or task_id
        rid = ev.get("request_id") or ev["id"]
        key = (tid, rid)
        prev = by_request.get(key)
        if not prev or conf_rank.get(ev.get("confidence", "low"), 0) > conf_rank.get(
            prev.get("confidence", "low"), 0
        ):
            by_request[key] = ev

    inferred_by_key = _load_inferred_for_tasks(db, session_task_ids)

    request_model_counts: Dict[str, int] = defaultdict(int)
    output_model_counts: Dict[str, int] = defaultdict(int)
    factual_req_counts: Dict[str, int] = defaultdict(int)
    factual_out_counts: Dict[str, int] = defaultdict(int)
    inferred_req_counts: Dict[str, int] = defaultdict(int)
    status_counts: Dict[str, int] = defaultdict(int)
    confidence_counts: Dict[str, int] = defaultdict(int)
    mix_confirmed: Dict[str, int] = defaultdict(int)
    mix_estimated: Dict[str, int] = defaultdict(int)

    per_request: List[Dict[str, Any]] = []
    resolved_requests = 0
    covered = 0
    pending_infer_count = 0
    unknown_mix_count = 0
    subagent_calls = 0
    for (tid, rid), ev in sorted(
        by_request.items(), key=lambda x: x[1].get("timestamp") or ""
    ):
        if tid != task_id:
            subagent_calls += 1
        bucket = _bucket_label(ev)
        factual = _is_resolved_model(ev.get("resolved_model")) or _is_resolved_model(
            ev.get("selected_model")
        )
        inf = inferred_by_key.get((tid, rid))
        display_bucket = bucket
        if bucket == PENDING_INFER_BUCKET and inf:
            display_bucket = inf["inferred_model"]
            inferred_req_counts[display_bucket] += 1
            mix_estimated[_mix_display_label(display_bucket)] += 1
            covered += 1
        elif factual:
            covered += 1
            factual_req_counts[bucket] += 1
            mix_confirmed[_mix_display_label(bucket)] += 1
        elif bucket == PENDING_INFER_BUCKET:
            pending_infer_count += 1
            unknown_mix_count += 1
        else:
            covered += 1  # unknown still "labeled" as unknown
            unknown_mix_count += 1

        request_model_counts[display_bucket] += 1
        if _is_resolved_model(ev.get("resolved_model")):
            resolved_requests += 1
        status_counts[ev.get("status") or "unknown"] += 1
        confidence_counts[ev.get("confidence") or "low"] += 1
        units = int(ev.get("generated_units") or 0)
        if units > 0:
            output_model_counts[display_bucket] += units
            if factual:
                factual_out_counts[bucket] += units
        per_request.append(
            {
                "request_id": rid,
                "task_id": tid,
                "selected_model": ev.get("selected_model"),
                "resolved_model": ev.get("resolved_model"),
                "inferred_model": (inf or {}).get("inferred_model"),
                "inferred_probability": (inf or {}).get("probability"),
                "status": ev.get("status"),
                "units": units,
                "confidence": ev.get("confidence"),
                "input_tokens": ev.get("input_tokens"),
                "output_tokens": ev.get("output_tokens"),
                "bucket": display_bucket,
            }
        )

    total_requests = sum(request_model_counts.values()) or 1
    resolution_rate = resolved_requests / total_requests if total_requests else 0.0
    n_req = len(by_request) or 1
    coverage = covered / n_req
    model_mix_v2 = _build_model_mix_v2(
        confirmed_by_model=dict(mix_confirmed),
        estimated_by_model=dict(mix_estimated),
        unknown_count=unknown_mix_count,
        subagent_calls=subagent_calls,
    )

    return TaskUsageReport(
        task_id=task_id,
        title=task.get("title"),
        mode=task.get("mode", "unknown"),
        route_kind=task.get("route_kind", "unknown"),
        started_at=task.get("started_at"),
        ended_at=task.get("ended_at"),
        request_count=len(by_request),
        code_unit_count=sum(output_model_counts.values()),
        subagent_count=len(subagents),
        resolved_requests=resolved_requests,
        resolution_rate=resolution_rate,
        request_shares=_shares_from_counts(request_model_counts),
        output_shares=_shares_from_counts(output_model_counts)
        if output_model_counts
        else {},
        factual_request_shares=_shares_from_counts(factual_req_counts)
        if factual_req_counts
        else {},
        factual_output_shares=_shares_from_counts(factual_out_counts)
        if factual_out_counts
        else {},
        inferred_request_shares=_shares_from_counts(inferred_req_counts)
        if inferred_req_counts
        else {},
        coverage=coverage,
        pending_infer_count=pending_infer_count,
        status_counts=dict(status_counts),
        confidence_counts=dict(confidence_counts),
        subagents=subagents,
        per_request=per_request,
        model_mix_v2=model_mix_v2,
    )


def list_tasks(
    db: Database,
    since: Optional[datetime] = None,
    limit: int = 20,
    auto_only: bool = False,
) -> List[TaskSummary]:
    since_iso = since.isoformat() if since else None
    rows = db.list_cursor_tasks(since=since_iso, limit=limit, auto_only=auto_only)
    summaries: List[TaskSummary] = []

    for row in rows:
        report = aggregate_task(db, row["task_id"])
        shares: Dict[str, float] = {}
        if report and report.request_shares:
            shares = {m: v["pct"] for m, v in report.request_shares.items()}

        summaries.append(
            TaskSummary(
                task_id=row["task_id"],
                title=row.get("title"),
                mode=row.get("mode", "unknown"),
                route_kind=row.get("route_kind", "unknown"),
                # Prefer session-scoped count (root + one-level subagents).
                request_count=(
                    report.request_count
                    if report is not None
                    else row.get("request_count", 0)
                ),
                code_unit_count=(
                    report.code_unit_count
                    if report is not None
                    else row.get("code_unit_count", 0)
                ),
                subagent_count=(
                    report.subagent_count
                    if report is not None
                    else row.get("subagent_count", 0)
                ),
                started_at=row.get("started_at"),
                model_request_shares=shares,
            )
        )
    return summaries


def format_model_share_line(shares: Dict[str, float], limit: int = 3) -> str:
    if not shares:
        return "unknown 100%"
    parts = []
    for model, pct in sorted(shares.items(), key=lambda x: -x[1])[:limit]:
        parts.append(f"{model} {pct:.0f}%")
    return " / ".join(parts)


def format_output_share_line(shares: Dict[str, float], limit: int = 3) -> str:
    if not shares:
        return "—"
    parts = []
    for model, pct in sorted(shares.items(), key=lambda x: -x[1])[:limit]:
        parts.append(f"{model} {pct:.1f}%")
    return " / ".join(parts)


def aggregate_period(
    db: Database,
    since: Optional[datetime] = None,
    limit: int = 20,
    auto_only: bool = False,
) -> PeriodUsageReport:
    """聚合时间范围内全部任务的模型占比。"""
    since_label = "全部"
    if since:
        delta = datetime.now() - since
        if delta.days >= 1:
            since_label = f"{delta.days}d"
        else:
            since_label = f"{int(delta.total_seconds() // 3600)}h"

    tasks = list_tasks(db, since=since, limit=limit, auto_only=auto_only)
    request_totals: Dict[str, int] = defaultdict(int)
    output_totals: Dict[str, int] = defaultdict(int)
    total_requests = 0
    total_output = 0
    resolved_requests = 0
    auto_count = mixed_count = 0

    latest_report: Optional[TaskUsageReport] = None
    best_output = -1
    for summary in tasks:
        if summary.route_kind == "auto":
            auto_count += 1
        elif summary.route_kind == "mixed":
            mixed_count += 1

        report = aggregate_task(db, summary.task_id)
        if not report:
            continue
        if report.code_unit_count > best_output:
            best_output = report.code_unit_count
            latest_report = report

        total_requests += report.request_count
        resolved_requests += report.resolved_requests
        for model, info in report.request_shares.items():
            request_totals[model] += info["count"]
        if report.output_shares:
            for model, info in report.output_shares.items():
                output_totals[model] += info["count"]
        total_output += report.code_unit_count

    req_den = sum(request_totals.values()) or 1
    out_den = sum(output_totals.values()) or 1

    resolution_rate = resolved_requests / total_requests if total_requests else 0.0

    return PeriodUsageReport(
        since_label=since_label,
        task_count=len(tasks),
        auto_task_count=auto_count,
        mixed_task_count=mixed_count,
        total_requests=total_requests,
        total_output_units=total_output,
        resolved_requests=resolved_requests,
        resolution_rate=resolution_rate,
        request_shares={
            m: {"pct": c / req_den * 100, "count": c}
            for m, c in sorted(request_totals.items(), key=lambda x: -x[1])
        },
        output_shares={
            m: {"pct": c / out_den * 100, "count": c}
            for m, c in sorted(output_totals.items(), key=lambda x: -x[1])
        },
        latest_report=latest_report,
        tasks=tasks,
    )


def period_to_since(period: str) -> str:
    return {"daily": "1d", "weekly": "7d", "monthly": "30d"}.get(period, "7d")


def get_model_scores(
    db: Database,
    models: List[str],
    hours: int = 24 * 30,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """从 score_snapshots 查找各模型最近智力分（支持模糊匹配）。"""
    latest = {row["model"]: row for row in db.get_latest_scores(hours=hours)}
    result: Dict[str, Optional[Dict[str, Any]]] = {}
    for model in models:
        if model in ("unknown", "default", "", "auto-opaque", PENDING_INFER_BUCKET):
            continue
        if model in latest:
            result[model] = latest[model]
            continue
        fuzzy = next(
            (snap for name, snap in latest.items() if model in name or name in model),
            None,
        )
        result[model] = fuzzy
    return result


def cursor_usage_insights(period: "PeriodUsageReport") -> List[str]:
    """根据周期聚合数据生成路由洞察。"""
    insights: List[str] = []
    req = period.request_shares
    out = period.output_shares

    if req and out:
        known_req = {k: v for k, v in req.items() if k != "unknown"}
        known_out = {k: v for k, v in out.items() if k != "unknown"}
        if known_req and known_out:
            top_req = max(known_req.items(), key=lambda x: x[1]["pct"])
            top_out = max(known_out.items(), key=lambda x: x[1]["pct"])
            if top_req[0] != top_out[0]:
                insights.append(
                    f"请求主力 {top_req[0]} ({top_req[1]['pct']:.0f}%) "
                    f"vs 产出主力 {top_out[0]} ({top_out[1]['pct']:.1f}%) "
                    "— Auto 路由可能存在任务类型分化"
                )

    unknown_pct = req.get("unknown", {}).get("pct", 0)
    pending_pct = req.get(PENDING_INFER_BUCKET, {}).get("pct", 0) or req.get(
        "auto-opaque", {}
    ).get("pct", 0)
    if pending_pct >= 20:
        pending_units = out.get(PENDING_INFER_BUCKET, {}).get("count", 0) or out.get(
            "auto-opaque", {}
        ).get("count", 0)
        insights.append(
            f"pending-infer 请求占 {pending_pct:.0f}%（{pending_units} code units 待推断），"
            "可 train 盲测后查看推断轨，或运行 verkee-verify cursor recommend"
        )
    elif unknown_pct >= 20:
        insights.append(
            f"unknown 请求占 {unknown_pct:.0f}%，可运行 verkee-verify cursor import --full 补采"
        )

    if period.auto_task_count + period.mixed_task_count == 0 and period.task_count > 0:
        insights.append("本周期无 Auto/Mixed 路由任务，占比反映的是手选模型使用情况")

    return insights


def render_task_score_table(report: TaskUsageReport, db: Database) -> Table:
    """构建任务模型占比 × 智力分对照表。"""
    models = set(report.output_shares.keys()) | set(report.request_shares.keys())
    models.discard("unknown")
    models.discard("auto-opaque")
    models.discard(PENDING_INFER_BUCKET)
    scores = get_model_scores(db, sorted(models))

    table = Table(title="模型占比 × 智力分", expand=True)
    table.add_column("模型", style="cyan")
    table.add_column("产出%", justify="right")
    table.add_column("请求%", justify="right")
    table.add_column("智力分", justify="right")
    table.add_column("偏差", justify="right", style="dim")
    table.add_column("快照", style="dim")

    for model in sorted(
        models,
        key=lambda m: -(report.output_shares.get(m, {}).get("pct", 0)),
    ):
        out_pct = report.output_shares.get(model, {}).get("pct")
        req_pct = report.request_shares.get(model, {}).get("pct")
        snap = scores.get(model)
        if snap and snap.get("intelligence_score") is not None:
            score = snap["intelligence_score"]
            color = "green" if score >= 85 else "yellow" if score >= 70 else "red"
            score_txt = f"[{color}]{score:.0f}[/{color}]"
            dev = snap.get("deviation")
            dev_txt = f"-{dev:.0f}" if dev else "—"
            ts = (snap.get("timestamp") or "")[:10]
        else:
            score_txt = "—"
            dev_txt = "—"
            ts = "无记录"
        table.add_row(
            model,
            f"{out_pct:.1f}%" if out_pct is not None else "—",
            f"{req_pct:.0f}%" if req_pct is not None else "—",
            score_txt,
            dev_txt,
            ts,
        )
    return table
