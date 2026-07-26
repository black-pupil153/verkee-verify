"""
Cursor Auto Usage — 只读本地路径探测与 schema 诊断。

独立于 cc-switch 的 resolve_provider()，不混入供应商解析。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from verkeep_verify.paths import verify_home

AI_TRACKING_TABLES = (
    "ai_code_hashes",
    "conversation_summaries",
    "tracked_file_content",
    "ai_deleted_files",
)

AI_CODE_HASHES_COLUMNS = (
    "hash",
    "source",
    "fileExtension",
    "fileName",
    "requestId",
    "conversationId",
    "timestamp",
    "model",
    "createdAt",
)

COMPOSER_HEADERS_KEY = "composer.composerHeaders"


@dataclass
class CursorPaths:
    """Cursor 本地数据路径（只读探测结果）。"""

    ai_tracking_db: Optional[Path] = None
    global_state_db: Optional[Path] = None
    logs_dir: Optional[Path] = None
    projects_dir: Optional[Path] = None
    platform: str = field(default_factory=platform.system)


def _cursor_home() -> Path:
    return Path.home() / ".cursor"


def _cursor_app_support() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Cursor"
        return Path.home() / "AppData" / "Roaming" / "Cursor"
    return Path.home() / ".config" / "Cursor"


def discover_cursor_paths() -> CursorPaths:
    """发现本机 Cursor 数据路径（三平台）。"""
    home = _cursor_home()
    app = _cursor_app_support()

    ai_tracking = home / "ai-tracking" / "ai-code-tracking.db"
    global_state = app / "User" / "globalStorage" / "state.vscdb"
    logs_dir = app / "logs"
    projects_dir = home / "projects"

    return CursorPaths(
        ai_tracking_db=ai_tracking if ai_tracking.is_file() else None,
        global_state_db=global_state if global_state.is_file() else None,
        logs_dir=logs_dir if logs_dir.is_dir() else None,
        projects_dir=projects_dir if projects_dir.is_dir() else None,
    )


def _open_sqlite_readonly(db_path: Path) -> sqlite3.Connection:
    """以只读方式打开 SQLite；锁定时复制到临时文件。"""
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error:
        pass

    tmp = Path(tempfile.gettempdir()) / f"verkeep-verify-cursor-{db_path.name}"
    shutil.copy2(db_path, tmp)
    return sqlite3.connect(tmp)


def probe_ai_tracking_schema(db_path: Path) -> Dict[str, Any]:
    """探测 ai-tracking.db 表与关键列。"""
    result: Dict[str, Any] = {
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size if db_path.is_file() else 0,
        "tables": {},
        "readable": False,
    }
    if not db_path.is_file():
        return result

    try:
        with _open_sqlite_readonly(db_path) as conn:
            result["readable"] = True
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in AI_TRACKING_TABLES:
                if table not in existing:
                    result["tables"][table] = {"exists": False}
                    continue
                cols = {
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                result["tables"][table] = {
                    "exists": True,
                    "columns": sorted(cols),
                }
            if "ai_code_hashes" in existing:
                row = conn.execute("SELECT COUNT(*) FROM ai_code_hashes").fetchone()
                result["ai_code_hash_count"] = row[0] if row else 0
    except sqlite3.Error as exc:
        result["error"] = str(exc)

    return result


def probe_structured_logs(logs_dir: Path) -> List[Path]:
    """发现 structured logs 与 renderer.log 文件。"""
    if not logs_dir.is_dir():
        return []

    files: List[Path] = []
    for pattern in (
        "**/Cursor Structured Logs*.log",
        "**/renderer.log",
        "**/cursor.requestTraces.log",
    ):
        files.extend(logs_dir.glob(pattern))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)


def probe_renderer_logs(logs_dir: Path) -> List[Path]:
    if not logs_dir.is_dir():
        return []
    return sorted(
        logs_dir.glob("**/renderer.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )


def _file_inode(path: Path) -> Optional[str]:
    try:
        st = path.stat()
        return f"{st.st_dev}:{st.st_ino}"
    except OSError:
        return None


def probe_log_files_summary(log_files: List[Path]) -> Dict[str, Any]:
    latest_mtime: Optional[datetime] = None
    for f in log_files:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
        except OSError:
            continue
    return {
        "count": len(log_files),
        "structured_count": sum(1 for f in log_files if "Structured Logs" in f.name),
        "renderer_count": sum(1 for f in log_files if f.name == "renderer.log"),
        "latest_mtime": latest_mtime,
    }


def header_display_title(header: Optional[Dict[str, Any]]) -> Optional[str]:
    """Pick the user-visible session title from a composer header.

    Prefer auto-generated ``name`` over ``subtitle`` (often first-message /
    activity snippets). Never reads prompt/response bodies.
    """
    if not header:
        return None
    for key in ("name", "title", "subtitle"):
        value = header.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def probe_composer_headers(global_state_db: Path) -> Dict[str, Any]:
    """探测 composer headers（ItemTable JSON 与 table-gated 表）。"""
    result: Dict[str, Any] = {"exists": False, "composer_count": 0}
    if not global_state_db.is_file():
        return result

    try:
        with _open_sqlite_readonly(global_state_db) as conn:
            row = conn.execute(
                "SELECT 1 FROM ItemTable WHERE key = ?",
                (COMPOSER_HEADERS_KEY,),
            ).fetchone()
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            table_exists = "composerHeaders" in tables
            if row or table_exists:
                result["exists"] = True
        headers = load_composer_headers(global_state_db)
        result["composer_count"] = len(headers)
        if headers:
            result["exists"] = True
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        result["error"] = str(exc)

    return result


def load_composer_headers(global_state_db: Path) -> Dict[str, Dict[str, Any]]:
    """读取 composer headers，返回 composerId -> header dict。

    Cursor 新版本在 ``composerHeaders`` 表存 Agent/Glass 会话（含自动生成
    ``name``）；旧版仍写 ItemTable ``composer.composerHeaders`` JSON。两者合并，
    同 id 时取 ``lastUpdatedAt`` 较新的一侧。
    """
    if not global_state_db.is_file():
        return {}

    out: Dict[str, Dict[str, Any]] = {}

    def _upsert(item: Dict[str, Any]) -> None:
        cid = item.get("composerId") or item.get("id")
        if not cid:
            return
        key = str(cid)
        item = dict(item)
        item.setdefault("composerId", key)
        existing = out.get(key)
        if existing is None:
            out[key] = item
            return
        old_ts = existing.get("lastUpdatedAt") or 0
        new_ts = item.get("lastUpdatedAt") or 0
        try:
            old_n = int(old_ts)
            new_n = int(new_ts)
        except (TypeError, ValueError):
            out[key] = item
            return
        if new_n >= old_n:
            out[key] = item

    try:
        with _open_sqlite_readonly(global_state_db) as conn:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?",
                (COMPOSER_HEADERS_KEY,),
            ).fetchone()
            if row:
                data = json.loads(row[0])
                if isinstance(data, dict) and "allComposers" in data:
                    composers = data["allComposers"]
                elif isinstance(data, list):
                    composers = data
                else:
                    composers = []
                for item in composers:
                    if isinstance(item, dict):
                        _upsert(item)

            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "composerHeaders" in tables:
                for cid, value, last_updated in conn.execute(
                    "SELECT composerId, value, lastUpdatedAt FROM composerHeaders"
                ):
                    if not cid or not value:
                        continue
                    try:
                        item = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    if last_updated is not None and "lastUpdatedAt" not in item:
                        item["lastUpdatedAt"] = last_updated
                    _upsert(item)
        return out
    except (sqlite3.Error, json.JSONDecodeError):
        return out


def probe_agent_transcripts(projects_dir: Path) -> Dict[str, Any]:
    """扫描 agent-transcripts 目录。"""
    result: Dict[str, Any] = {
        "project_dirs": [],
        "task_count": 0,
        "subagent_count": 0,
    }
    if not projects_dir.is_dir():
        return result

    best_dir: Optional[Path] = None
    best_count = 0
    total_tasks = 0
    total_subagents = 0

    for project in sorted(projects_dir.iterdir()):
        transcripts = project / "agent-transcripts"
        if not transcripts.is_dir():
            continue
        tasks = [
            p
            for p in transcripts.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        subagents = sum(
            1
            for t in tasks
            for _ in (t / "subagents").glob("*.jsonl")
            if (t / "subagents").is_dir()
        )
        total_tasks += len(tasks)
        total_subagents += subagents
        if len(tasks) > best_count:
            best_count = len(tasks)
            best_dir = transcripts

    result["task_count"] = total_tasks
    result["subagent_count"] = total_subagents
    if best_dir:
        result["project_dirs"] = [str(best_dir)]
        result["primary_transcripts_dir"] = str(best_dir)
    return result


def scan_subagent_relations(projects_dir: Path) -> Dict[str, str]:
    """返回 subagent_id -> parent_task_id。"""
    relations: Dict[str, str] = {}
    if not projects_dir.is_dir():
        return relations

    for project in projects_dir.iterdir():
        transcripts = project / "agent-transcripts"
        if not transcripts.is_dir():
            continue
        for task_dir in transcripts.iterdir():
            if not task_dir.is_dir():
                continue
            parent_id = task_dir.name
            sub_dir = task_dir / "subagents"
            if not sub_dir.is_dir():
                continue
            for sub_file in sub_dir.glob("*.jsonl"):
                relations[sub_file.stem] = parent_id
    return relations


def _coerce_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 1e12:
            num /= 1000.0
        try:
            return datetime.fromtimestamp(num)
        except (OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        num = float(text)
        if num > 1e12:
            num /= 1000.0
        try:
            return datetime.fromtimestamp(num)
        except (OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_ai_code_hashes(
    db_path: Path,
    since: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """只读 ai_code_hashes 元数据（不读 content 类字段）。"""
    if not db_path.is_file():
        return []

    query = """
        SELECT requestId, conversationId, model, timestamp, createdAt
        FROM ai_code_hashes
    """

    try:
        with _open_sqlite_readonly(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                if since:
                    ts = _coerce_timestamp(
                        item.get("timestamp") or item.get("createdAt")
                    )
                    if ts and ts < since:
                        continue
                out.append(item)
            return out
    except sqlite3.Error:
        return []


def read_conversation_summaries(db_path: Path) -> Dict[str, Dict[str, Any]]:
    """Read conversation_summaries model metadata, if Cursor stores it locally."""
    if not db_path.is_file():
        return {}

    try:
        with _open_sqlite_readonly(db_path) as conn:
            conn.row_factory = sqlite3.Row
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "conversation_summaries" not in existing:
                return {}
            cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(conversation_summaries)"
                ).fetchall()
            }
            if "conversationId" not in cols:
                return {}
            select_cols = ["conversationId"]
            for optional in ("model", "mode", "title", "tldr"):
                if optional in cols:
                    select_cols.append(optional)
            rows = conn.execute(
                f"SELECT {', '.join(select_cols)} FROM conversation_summaries"
            ).fetchall()
            out: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                item = dict(row)
                cid = item.get("conversationId")
                if cid:
                    out[str(cid)] = {
                        "model": item.get("model"),
                        "mode": item.get("mode"),
                        "title": item.get("title"),
                        "tldr": item.get("tldr"),
                    }
            return out
    except sqlite3.Error:
        return {}


def count_proxy_cursor_calls(db_path: Path) -> int:
    """统计 proxy 中可能与 Cursor 相关的 api_calls（补充源，非 MVP 主路径）。"""
    if not db_path.is_file():
        return 0
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM api_calls
                WHERE model LIKE '%cursor%' OR claimed_model LIKE '%cursor%'
                """
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    extra: Dict[str, Any] = field(default_factory=dict)
    optional: bool = False
    severity: str = "error"  # error | warning | info


@dataclass
class DoctorReport:
    checks: List[DoctorCheck] = field(default_factory=list)
    collectable_fields: List[Tuple[str, str, str]] = field(default_factory=list)
    suggestion: str = ""

    def add(self, check: DoctorCheck) -> None:
        self.checks.append(check)

    @property
    def required_ok(self) -> bool:
        required = [c for c in self.checks if not c.optional]
        return all(c.ok for c in required) if required else False

    @property
    def warnings(self) -> List[DoctorCheck]:
        return [
            c
            for c in self.checks
            if c.optional and (not c.ok or c.severity == "warning")
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for CLI --json / extension bridge."""
        return {
            # Overall health ignores optional/supplement sources.
            "ok": self.required_ok,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "detail": c.detail,
                    "optional": c.optional,
                    "severity": c.severity,
                    # extra may contain Path / large schema blobs; keep lean
                    "extra_keys": sorted(c.extra.keys()) if c.extra else [],
                }
                for c in self.checks
            ],
            "warnings": [
                {"name": c.name, "detail": c.detail, "severity": c.severity}
                for c in self.warnings
            ],
            "collectable_fields": [
                {"label": label, "via": via, "source": source}
                for label, via, source in self.collectable_fields
            ],
            "suggestion": self.suggestion,
        }


def run_doctor(verkeep_verify_db: Optional[Path] = None) -> DoctorReport:
    """运行 Cursor Auto Usage 环境诊断。"""
    paths = discover_cursor_paths()
    report = DoctorReport()

    # ai-tracking.db
    if paths.ai_tracking_db:
        schema = probe_ai_tracking_schema(paths.ai_tracking_db)
        size_mb = schema.get("size_bytes", 0) / (1024 * 1024)
        tables = schema.get("tables", {})
        hashes_ok = tables.get("ai_code_hashes", {}).get("exists", False)
        summaries_ok = tables.get("conversation_summaries", {}).get("exists", False)
        schema_line = (
            f"schema: ai_code_hashes {'✓' if hashes_ok else '✗'}  "
            f"conversation_summaries {'✓' if summaries_ok else '✗'}"
        )
        report.add(
            DoctorCheck(
                name="ai-tracking.db",
                ok=schema.get("readable", False) and hashes_ok,
                detail=f"{paths.ai_tracking_db} ({size_mb:.1f} MB)\n  {schema_line}",
                extra=schema,
            )
        )
    else:
        report.add(
            DoctorCheck(
                name="ai-tracking.db",
                ok=False,
                detail="not found",
            )
        )

    # structured logs
    log_files = probe_structured_logs(paths.logs_dir) if paths.logs_dir else []
    log_summary = probe_log_files_summary(log_files)
    if log_files:
        latest = log_summary.get("latest_mtime")
        latest_str = latest.strftime("%Y-%m-%d") if latest else "unknown"
        report.add(
            DoctorCheck(
                name="structured logs",
                ok=True,
                detail=f"{log_summary['count']} files, latest {latest_str}",
                extra=log_summary,
            )
        )
    else:
        report.add(
            DoctorCheck(
                name="structured logs",
                ok=False,
                detail="not found",
            )
        )

    # global state
    if paths.global_state_db:
        headers = probe_composer_headers(paths.global_state_db)
        report.add(
            DoctorCheck(
                name="global state",
                ok=headers.get("exists", False),
                detail=(
                    f"composer.composerHeaders {'✓' if headers.get('exists') else '✗'}"
                    + (
                        f" ({headers.get('composer_count', 0)} composers)"
                        if headers.get("exists")
                        else ""
                    )
                ),
                extra=headers,
            )
        )
    else:
        report.add(
            DoctorCheck(
                name="global state",
                ok=False,
                detail="state.vscdb not found",
            )
        )

    # agent transcripts
    transcripts = (
        probe_agent_transcripts(paths.projects_dir) if paths.projects_dir else {}
    )
    if transcripts.get("task_count", 0) > 0:
        primary = transcripts.get("primary_transcripts_dir", "")
        report.add(
            DoctorCheck(
                name="agent transcripts",
                ok=True,
                detail=(
                    f"{primary} ({transcripts['task_count']} tasks, "
                    f"{transcripts.get('subagent_count', 0)} subagents)"
                ),
                extra=transcripts,
            )
        )
    else:
        report.add(
            DoctorCheck(
                name="agent transcripts",
                ok=False,
                detail="not found",
            )
        )

    # proxy supplement (optional): missing data is degraded, not blocking
    verify_db = verkeep_verify_db or (verify_home() / "data" / "ai_verify.db")
    proxy_count = count_proxy_cursor_calls(verify_db)
    if proxy_count > 0:
        report.add(
            DoctorCheck(
                name="proxy supplement",
                ok=True,
                detail=f"{proxy_count} cursor-related api_calls",
                optional=True,
                severity="info",
            )
        )
    else:
        report.add(
            DoctorCheck(
                name="proxy supplement",
                ok=False,
                detail=(
                    f"{proxy_count} cursor-related api_calls "
                    "(optional; core Cursor sources still usable)"
                ),
                optional=True,
                severity="warning",
            )
        )

    report.collectable_fields = [
        ("resolved_model (high)", "via ai_code_hashes.model", "ai_tracking_db"),
        ("request routing (med)", "via structured logs", "structured_log"),
        ("outcome/ttft (med)", "via agent.turn.outcome", "structured_log"),
        (
            "tokens (hook)",
            "via cursor hooks input_tokens/output_tokens when present",
            "hook",
        ),
    ]
    report.suggestion = "verkeep-verify cursor import --since 7d"
    return report


def format_size(path: Path) -> str:
    try:
        size = path.stat().st_size
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
    except OSError:
        return "unknown"
