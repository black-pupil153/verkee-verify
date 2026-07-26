"""
Cursor probe — read-only forensics scanner for model fields in local logs.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from verkee_verify.providers.cursor import (
    CursorPaths,
    discover_cursor_paths,
    read_ai_code_hashes,
    scan_subagent_relations,
)

MODEL_KEY_RE = re.compile(r"model", re.IGNORECASE)
REQUEST_ID_RE = re.compile(
    r"(?:requestId|request_id|generation_id|generationId)[\"'=:\s]+([a-zA-Z0-9_-]{6,})",
    re.IGNORECASE,
)
TASK_ID_RE = re.compile(
    r"(?:conversationId|conversation_id|composerId|composer_id|task_id)[\"'=:\s]+([a-f0-9-]{6,})",
    re.IGNORECASE,
)
KV_MODEL_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_.]*model[A-Za-z0-9_.]*)\s*[=:]\s*([^\s,;\"']+)",
    re.IGNORECASE,
)


@dataclass
class ModelHit:
    request_id: str
    source: str
    key: str
    value: str


@dataclass
class ProbeReport:
    task_id: Optional[str]
    model_hits: List[ModelHit] = field(default_factory=list)
    tracking_buckets: Dict[str, int] = field(default_factory=dict)
    subagent_tree: Dict[str, List[str]] = field(default_factory=dict)
    files_scanned: int = 0
    lines_matched: int = 0


def _short_path(path: Path, logs_dir: Optional[Path]) -> str:
    try:
        if logs_dir:
            return str(path.relative_to(logs_dir))
    except ValueError:
        pass
    return path.name


def discover_probe_log_files(logs_dir: Path) -> List[Path]:
    """Discover all log files relevant to model forensics."""
    if not logs_dir.is_dir():
        return []

    files: Set[Path] = set()
    patterns = (
        "**/cursor.requestTraces.log",
        "**/Cursor Structured Logs*.log",
        "**/renderer.log",
    )
    for pattern in patterns:
        files.update(logs_dir.glob(pattern))

    for sub in ("exthost", "output_logging", "output_*"):
        for path in logs_dir.glob(f"**/{sub}/**/*.log"):
            if path.is_file():
                files.add(path)

    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _extract_json_model_fields(obj: Any, prefix: str = "") -> List[Tuple[str, str]]:
    hits: List[Tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if MODEL_KEY_RE.search(key) and val is not None:
                hits.append((full_key, str(val)))
            hits.extend(_extract_json_model_fields(val, full_key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            hits.extend(_extract_json_model_fields(item, f"{prefix}[{i}]"))
    return hits


def _request_ids_from_line(line: str) -> Set[str]:
    ids: Set[str] = set()
    for match in REQUEST_ID_RE.finditer(line):
        ids.add(match.group(1))
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            for key in ("requestId", "request_id", "generation_id", "generationId"):
                val = obj.get(key)
                if val:
                    ids.add(str(val))
    except (json.JSONDecodeError, TypeError):
        pass
    return ids


def _line_matches_task(line: str, task_id: Optional[str]) -> bool:
    if not task_id:
        return True
    if task_id in line:
        return True
    for match in TASK_ID_RE.finditer(line):
        if match.group(1).startswith(task_id) or task_id.startswith(match.group(1)[:8]):
            return True
    return False


def _scan_log_file(
    path: Path,
    task_id: Optional[str],
    logs_dir: Optional[Path],
    hits: List[ModelHit],
    seen: Set[Tuple[str, str, str, str]],
) -> Tuple[int, int]:
    source = _short_path(path, logs_dir)
    lines_matched = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not _line_matches_task(line, task_id):
                    continue
                if not MODEL_KEY_RE.search(line):
                    continue
                lines_matched += 1
                request_ids = _request_ids_from_line(line) or {"-"}

                json_hits: List[Tuple[str, str]] = []
                try:
                    obj = json.loads(line)
                    json_hits = _extract_json_model_fields(obj)
                except (json.JSONDecodeError, TypeError):
                    pass

                if not json_hits:
                    for match in KV_MODEL_RE.finditer(line):
                        json_hits.append((match.group(1), match.group(2)))

                for req_id in request_ids:
                    for key, value in json_hits:
                        dedupe = (req_id, source, key, value)
                        if dedupe in seen:
                            continue
                        seen.add(dedupe)
                        hits.append(
                            ModelHit(
                                request_id=req_id,
                                source=source,
                                key=key,
                                value=value,
                            )
                        )
    except OSError:
        return 0, 0
    return 1, lines_matched


def _tracking_buckets(
    paths: CursorPaths,
    task_id: Optional[str],
) -> Dict[str, int]:
    buckets: Dict[str, int] = defaultdict(int)
    if not paths.ai_tracking_db:
        return dict(buckets)

    rows = read_ai_code_hashes(paths.ai_tracking_db)
    for row in rows:
        cid = row.get("conversationId") or ""
        if task_id and not (cid.startswith(task_id) or task_id.startswith(cid[:8])):
            continue
        model = row.get("model") or "unknown"
        if model == "default":
            buckets["default"] += 1
        elif model in (None, ""):
            buckets["unknown"] += 1
        else:
            buckets[model] += 1
    return dict(buckets)


def _subagent_tree(
    paths: CursorPaths,
    task_id: Optional[str],
) -> Dict[str, List[str]]:
    relations = scan_subagent_relations(paths.projects_dir) if paths.projects_dir else {}
    tree: Dict[str, List[str]] = defaultdict(list)
    for sub_id, parent_id in relations.items():
        if task_id and not (
            parent_id.startswith(task_id)
            or task_id.startswith(parent_id[:8])
            or sub_id.startswith(task_id)
        ):
            continue
        tree[parent_id].append(sub_id)
    return {k: sorted(v) for k, v in tree.items()}


def run_probe(
    task_id: Optional[str] = None,
    paths: Optional[CursorPaths] = None,
    limit: int = 200,
) -> ProbeReport:
    """Scan local Cursor logs for model-related fields."""
    paths = paths or discover_cursor_paths()
    report = ProbeReport(task_id=task_id)

    hits: List[ModelHit] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    files_scanned = 0
    lines_matched = 0

    log_files: List[Path] = []
    if paths.logs_dir:
        log_files = discover_probe_log_files(paths.logs_dir)

    for log_path in log_files:
        f_count, l_count = _scan_log_file(
            log_path, task_id, paths.logs_dir, hits, seen
        )
        files_scanned += f_count
        lines_matched += l_count

    report.model_hits = hits[:limit]
    report.files_scanned = files_scanned
    report.lines_matched = lines_matched
    report.tracking_buckets = _tracking_buckets(paths, task_id)
    report.subagent_tree = _subagent_tree(paths, task_id)
    return report


def format_probe_report(report: ProbeReport) -> str:
    """Format probe report as plain text lines."""
    lines: List[str] = []
    header = f"Task: {report.task_id or '(all tasks)'}"
    lines.append(header)
    lines.append(f"Files scanned: {report.files_scanned}, lines with model fields: {report.lines_matched}")

    if report.tracking_buckets:
        lines.append("\n── ai-tracking buckets ──")
        for model, count in sorted(report.tracking_buckets.items(), key=lambda x: -x[1]):
            lines.append(f"  {model}: {count}")

    if report.subagent_tree:
        lines.append("\n── subagent tree ──")
        for parent, subs in sorted(report.subagent_tree.items()):
            short_parent = parent[:8]
            sub_short = ", ".join(s[:8] for s in subs)
            lines.append(f"  {short_parent} → [{sub_short}]")

    if report.model_hits:
        lines.append("\n── model field hits ──")
        lines.append(f"  {'request_id':<22} {'source':<28} {'key':<24} value")
        for hit in report.model_hits:
            lines.append(
                f"  {hit.request_id[:20]:<22} {hit.source[:26]:<28} {hit.key[:22]:<24} {hit.value[:40]}"
            )
    else:
        lines.append("\n(no model field hits found)")

    distinct_values = sorted({h.value for h in report.model_hits})
    real_models = [v for v in distinct_values if v not in ("default", "", "unknown")]
    lines.append(f"\nDistinct model values: {', '.join(distinct_values) or '(none)'}")
    lines.append(f"Real model slugs found: {'yes' if real_models else 'no'}")
    if real_models:
        lines.append(f"  → {', '.join(real_models)}")
    return "\n".join(lines)
