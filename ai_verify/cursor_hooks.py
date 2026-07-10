"""
Cursor Hooks — install, analyze, and uninstall probe hooks for model forensics.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

HOOK_SCRIPT_NAME = "cursor-track.sh"
HOOK_EVENTS = ("stop", "subagentStart", "subagentStop", "afterAgentResponse")
MODEL_KEYS = ("model", "model_id", "subagent_model", "modelName", "catalogModelId")


def ai_verify_home() -> Path:
    return Path.home() / ".ai-verify"


def hook_script_path() -> Path:
    return ai_verify_home() / "hooks" / HOOK_SCRIPT_NAME


def probe_ndjson_path() -> Path:
    return ai_verify_home() / "cursor-hook-probe.ndjson"


def cursor_hooks_json_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def hook_command_for_event(event: str) -> str:
    script = hook_script_path()
    return f"{script} {event}"


HOOK_SCRIPT_CONTENT = """#!/usr/bin/env bash
# ai-verify Cursor hook probe — append full stdin JSON to ndjson log
set -euo pipefail
EVENT="${1:-unknown}"
NDJSON="${HOME}/.ai-verify/cursor-hook-probe.ndjson"
mkdir -p "$(dirname "$NDJSON")"
python3 -c "
import json, sys, datetime
event = sys.argv[1]
raw = sys.stdin.read()
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {'_raw': raw}
record = {
    'hook_event': event,
    'received_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'payload': payload,
}
with open(sys.argv[2], 'a', encoding='utf-8') as f:
    f.write(json.dumps(record, ensure_ascii=False) + '\\n')
" "$EVENT" "$NDJSON"
"""


@dataclass
class HooksInstallResult:
    script_path: Path
    hooks_json_path: Path
    backup_path: Optional[Path]
    events_added: List[str] = field(default_factory=list)
    events_existing: List[str] = field(default_factory=list)


@dataclass
class HooksAnalyzeResult:
    event_counts: Dict[str, int] = field(default_factory=dict)
    model_values: Dict[str, Set[str]] = field(default_factory=dict)
    provides_resolved_model: bool = False
    total_events: int = 0


def _normalize_hooks_doc(doc: Any) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        return {"version": 1, "hooks": {}}
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    return {"version": doc.get("version", 1), "hooks": hooks}


def _entry_command(entry: Any) -> Optional[str]:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("command")
    return None


def is_our_hook_command(command: Optional[str]) -> bool:
    if not command:
        return False
    return HOOK_SCRIPT_NAME in command or str(hook_script_path()) in command


def merge_hooks(
    existing: Dict[str, Any],
    events: Iterable[str] = HOOK_EVENTS,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Merge our hook entries into hooks.json, preserving others."""
    doc = _normalize_hooks_doc(existing)
    hooks: Dict[str, List[Any]] = doc["hooks"]
    added: List[str] = []
    already: List[str] = []

    for event in events:
        entries = list(hooks.get(event, []))
        filtered = [
            e for e in entries if not is_our_hook_command(_entry_command(e))
        ]
        cmd = hook_command_for_event(event)
        has_ours = any(is_our_hook_command(_entry_command(e)) for e in entries)
        if has_ours:
            already.append(event)
        else:
            added.append(event)
        filtered.append({"command": cmd})
        hooks[event] = filtered

    doc["hooks"] = hooks
    return doc, added, already


def install_hooks(
    hooks_json: Optional[Path] = None,
    script_out: Optional[Path] = None,
) -> HooksInstallResult:
    """Install probe hook script and merge into ~/.cursor/hooks.json."""
    hooks_path = hooks_json or cursor_hooks_json_path()
    script_path = script_out or hook_script_path()

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(HOOK_SCRIPT_CONTENT, encoding="utf-8")
    script_path.chmod(0o755)

    existing: Dict[str, Any] = {"version": 1, "hooks": {}}
    backup: Optional[Path] = None
    if hooks_path.is_file():
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = hooks_path.with_name(f"hooks.json.bak-{ts}")
        shutil.copy2(hooks_path, backup)

    merged, added, already = merge_hooks(existing)
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    return HooksInstallResult(
        script_path=script_path,
        hooks_json_path=hooks_path,
        backup_path=backup,
        events_added=added,
        events_existing=already,
    )


def uninstall_hooks(hooks_json: Optional[Path] = None) -> Tuple[Path, Optional[Path], List[str]]:
    """Remove our hook entries from hooks.json."""
    hooks_path = hooks_json or cursor_hooks_json_path()
    if not hooks_path.is_file():
        return hooks_path, None, []

    existing = json.loads(hooks_path.read_text(encoding="utf-8"))
    doc = _normalize_hooks_doc(existing)
    removed: List[str] = []

    for event, entries in list(doc["hooks"].items()):
        kept = [e for e in entries if not is_our_hook_command(_entry_command(e))]
        if len(kept) != len(entries):
            removed.append(event)
        if kept:
            doc["hooks"][event] = kept
        else:
            del doc["hooks"][event]

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = hooks_path.with_name(f"hooks.json.bak-{ts}")
    shutil.copy2(hooks_path, backup)
    hooks_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return hooks_path, backup, removed


def hooks_installed(hooks_json: Optional[Path] = None) -> bool:
    hooks_path = hooks_json or cursor_hooks_json_path()
    if not hooks_path.is_file():
        return False
    try:
        doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    hooks = doc.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if is_our_hook_command(_entry_command(entry)):
                return True
    return False


def _collect_model_values(payload: Any, found: Set[str]) -> None:
    if isinstance(payload, dict):
        for key, val in payload.items():
            if key in MODEL_KEYS or (
                isinstance(key, str) and "model" in key.lower()
            ):
                if val is not None and str(val).strip():
                    found.add(str(val))
            _collect_model_values(val, found)
    elif isinstance(payload, list):
        for item in payload:
            _collect_model_values(item, found)


def analyze_probe_ndjson(
    ndjson_path: Optional[Path] = None,
) -> HooksAnalyzeResult:
    """Analyze hook probe ndjson for model field presence."""
    path = ndjson_path or probe_ndjson_path()
    result = HooksAnalyzeResult()
    if not path.is_file():
        return result

    per_event_values: Dict[str, Set[str]] = defaultdict(set)

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = record.get("hook_event") or "unknown"
            result.event_counts[event] = result.event_counts.get(event, 0) + 1
            result.total_events += 1
            payload = record.get("payload", {})
            _collect_model_values(payload, per_event_values[event])

    result.model_values = {k: v for k, v in per_event_values.items()}
    all_values: Set[str] = set()
    for vals in per_event_values.values():
        all_values |= vals
    real = [v for v in all_values if v not in ("default", "", "unknown")]
    result.provides_resolved_model = bool(real)
    return result


def format_analyze_result(result: HooksAnalyzeResult) -> str:
    lines: List[str] = []
    lines.append(f"Total hook events: {result.total_events}")
    if result.event_counts:
        lines.append("\nEvents fired:")
        for event, count in sorted(result.event_counts.items()):
            vals = result.model_values.get(event, set())
            val_str = ", ".join(sorted(vals)) if vals else "(no model fields)"
            lines.append(f"  {event}: {count} — values: {val_str}")
    else:
        lines.append("No events recorded yet.")
    verdict = "yes" if result.provides_resolved_model else "no"
    lines.append(f"\nhook 提供 resolved model: {verdict}")
    return "\n".join(lines)
