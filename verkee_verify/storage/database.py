"""
数据存储模块
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from verkee_verify.paths import verify_home


class Database:
    """本地数据库管理"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = verify_home() / "data" / "ai_verify.db"

        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        """确保数据表存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS api_calls (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    claimed_model TEXT,

                    request_tokens INTEGER,
                    prompt_hash TEXT,

                    response_tokens INTEGER,
                    latency_ms INTEGER,
                    status_code INTEGER,

                    fingerprint_family TEXT,
                    fingerprint_confidence REAL,
                    quality_score REAL,

                    is_anomaly BOOLEAN DEFAULT FALSE,
                    anomaly_type TEXT,

                    request_preview TEXT,
                    response_preview TEXT
                );

                CREATE TABLE IF NOT EXISTS quality_tests (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    test_type TEXT,
                    question_hash TEXT,
                    is_correct BOOLEAN,
                    response_time_ms INTEGER,
                    baseline_correct BOOLEAN
                );

                CREATE TABLE IF NOT EXISTS anomalies (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT,
                    anomaly_type TEXT,
                    severity TEXT,
                    details TEXT,
                    resolved BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS score_snapshots (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    base_url TEXT,
                    intelligence_score REAL,
                    overall_score REAL,
                    quality_score REAL,
                    baseline REAL,
                    deviation REAL,
                    fingerprint_family TEXT,
                    fingerprint_confidence REAL,
                    fingerprint_match BOOLEAN,
                    latency_ms INTEGER,
                    correct INTEGER,
                    total INTEGER,
                    is_anomaly BOOLEAN DEFAULT FALSE,
                    note TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_api_calls_timestamp ON api_calls(timestamp);
                CREATE INDEX IF NOT EXISTS idx_api_calls_model ON api_calls(model);
                CREATE INDEX IF NOT EXISTS idx_score_timestamp ON score_snapshots(timestamp);
                CREATE INDEX IF NOT EXISTS idx_score_model ON score_snapshots(model);

                CREATE TABLE IF NOT EXISTS cursor_tasks (
                    task_id TEXT PRIMARY KEY,
                    project_path TEXT,
                    title TEXT,
                    mode TEXT,
                    route_kind TEXT,
                    started_at DATETIME,
                    ended_at DATETIME,
                    request_count INTEGER DEFAULT 0,
                    code_unit_count INTEGER DEFAULT 0,
                    subagent_count INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'import'
                );

                CREATE TABLE IF NOT EXISTS cursor_model_events (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    parent_task_id TEXT,
                    request_id TEXT,
                    selected_model TEXT,
                    resolved_model TEXT,
                    route_kind TEXT,
                    event_source TEXT,
                    confidence TEXT,
                    generated_units INTEGER DEFAULT 0,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    latency_ms INTEGER,
                    ttft_ms INTEGER,
                    status TEXT,
                    error_text TEXT,
                    timestamp DATETIME,
                    UNIQUE(task_id, request_id, event_source, timestamp)
                );

                CREATE INDEX IF NOT EXISTS idx_cursor_events_task ON cursor_model_events(task_id);
                CREATE INDEX IF NOT EXISTS idx_cursor_events_request ON cursor_model_events(request_id);
                CREATE INDEX IF NOT EXISTS idx_cursor_events_model ON cursor_model_events(resolved_model);
                CREATE INDEX IF NOT EXISTS idx_cursor_tasks_started ON cursor_tasks(started_at);

                CREATE TABLE IF NOT EXISTS cursor_import_state (
                    source_path TEXT PRIMARY KEY,
                    last_offset INTEGER DEFAULT 0,
                    last_inode TEXT,
                    last_seen_at DATETIME
                );

                CREATE TABLE IF NOT EXISTS blindtest_inferences (
                    task_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL DEFAULT 0,
                    request_id TEXT,
                    inferred_model TEXT,
                    probability REAL,
                    model_version TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (task_id, turn_index, model_version)
                );

                CREATE INDEX IF NOT EXISTS idx_blindtest_task ON blindtest_inferences(task_id);
            """)

    async def save_call(self, call_data: Dict[str, Any]) -> None:
        """保存 API 调用记录"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO api_calls (
                    id, timestamp, model, claimed_model,
                    request_tokens, response_tokens, latency_ms, status_code,
                    fingerprint_family, fingerprint_confidence, quality_score,
                    is_anomaly, anomaly_type, request_preview, response_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_data.get("id"),
                    call_data.get("timestamp", datetime.utcnow().isoformat()),
                    call_data.get("model"),
                    call_data.get("claimed_model"),
                    call_data.get("request_tokens"),
                    call_data.get("response_tokens"),
                    call_data.get("latency_ms"),
                    call_data.get("status_code"),
                    call_data.get("fingerprint_family"),
                    call_data.get("fingerprint_confidence"),
                    call_data.get("quality_score"),
                    call_data.get("is_anomaly", False),
                    call_data.get("anomaly_type"),
                    call_data.get("request_preview", "")[:500],
                    call_data.get("response_preview", "")[:500],
                ),
            )
            await db.commit()

    def get_call_history(
        self, hours: int = 168, model: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取调用历史"""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = """
                SELECT * FROM api_calls
                WHERE timestamp >= ?
            """
            params = [since]

            if model:
                query += " AND model = ?"
                params.append(model)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def save_score_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """保存一次智力打分快照（同步写入）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO score_snapshots (
                    id, timestamp, model, base_url,
                    intelligence_score, overall_score, quality_score,
                    baseline, deviation,
                    fingerprint_family, fingerprint_confidence, fingerprint_match,
                    latency_ms, correct, total, is_anomaly, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.get("id"),
                    snapshot.get("timestamp", datetime.utcnow().isoformat()),
                    snapshot.get("model"),
                    snapshot.get("base_url"),
                    snapshot.get("intelligence_score"),
                    snapshot.get("overall_score"),
                    snapshot.get("quality_score"),
                    snapshot.get("baseline"),
                    snapshot.get("deviation"),
                    snapshot.get("fingerprint_family"),
                    snapshot.get("fingerprint_confidence"),
                    snapshot.get("fingerprint_match"),
                    snapshot.get("latency_ms"),
                    snapshot.get("correct"),
                    snapshot.get("total"),
                    snapshot.get("is_anomaly", False),
                    snapshot.get("note"),
                ),
            )
            conn.commit()

    def get_score_history(
        self, model: Optional[str] = None, hours: int = 168, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """获取智力打分历史（时间升序）"""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM score_snapshots WHERE timestamp >= ?"
            params: List[Any] = [since]
            if model:
                query += " AND model = ?"
                params.append(model)
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_latest_scores(self, hours: int = 168) -> List[Dict[str, Any]]:
        """获取每个模型最近一次打分快照"""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT s.* FROM score_snapshots s
                INNER JOIN (
                    SELECT model, MAX(timestamp) AS mx
                    FROM score_snapshots
                    WHERE timestamp >= ?
                    GROUP BY model
                ) t ON s.model = t.model AND s.timestamp = t.mx
                ORDER BY s.model
                """,
                [since],
            ).fetchall()
            return [dict(row) for row in rows]

    def get_stats(self, hours: int = 24, model: Optional[str] = None) -> Dict[str, Any]:
        """获取统计数据"""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            base_query = "FROM api_calls WHERE timestamp >= ?"
            params = [since]

            if model:
                base_query += " AND model = ?"
                params.append(model)

            total = conn.execute(
                f"SELECT COUNT(*) as count {base_query}", params
            ).fetchone()["count"]

            anomalies = conn.execute(
                f"SELECT COUNT(*) as count {base_query} AND is_anomaly = 1", params
            ).fetchone()["count"]

            avg_latency = conn.execute(
                f"SELECT AVG(latency_ms) as avg {base_query}", params
            ).fetchone()["avg"] or 0

            avg_quality = conn.execute(
                f"SELECT AVG(quality_score) as avg {base_query}", params
            ).fetchone()["avg"] or 0

            return {
                "total_calls": total,
                "anomalies": anomalies,
                "avg_latency_ms": int(avg_latency),
                "avg_quality_score": round(avg_quality, 1),
                "period_hours": hours,
            }

    # ============== Cursor Auto Usage ==============

    def save_cursor_task(self, task: Dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cursor_tasks (
                    task_id, project_path, title, mode, route_kind,
                    started_at, ended_at, request_count, code_unit_count,
                    subagent_count, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    title=excluded.title,
                    mode=excluded.mode,
                    route_kind=excluded.route_kind,
                    started_at=COALESCE(excluded.started_at, cursor_tasks.started_at),
                    ended_at=COALESCE(excluded.ended_at, cursor_tasks.ended_at),
                    request_count=excluded.request_count,
                    code_unit_count=excluded.code_unit_count,
                    subagent_count=excluded.subagent_count
                """,
                (
                    task.get("task_id"),
                    task.get("project_path"),
                    task.get("title"),
                    task.get("mode"),
                    task.get("route_kind"),
                    task.get("started_at"),
                    task.get("ended_at"),
                    task.get("request_count", 0),
                    task.get("code_unit_count", 0),
                    task.get("subagent_count", 0),
                    task.get("source", "import"),
                ),
            )
            conn.commit()

    def save_cursor_model_event(self, event: Dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cursor_model_events (
                    id, task_id, parent_task_id, request_id,
                    selected_model, resolved_model, route_kind,
                    event_source, confidence, generated_units,
                    input_tokens, output_tokens, latency_ms, ttft_ms,
                    status, error_text, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, request_id, event_source, timestamp) DO UPDATE SET
                    selected_model=COALESCE(excluded.selected_model, cursor_model_events.selected_model),
                    resolved_model=COALESCE(excluded.resolved_model, cursor_model_events.resolved_model),
                    route_kind=COALESCE(excluded.route_kind, cursor_model_events.route_kind),
                    confidence=excluded.confidence,
                    generated_units=MAX(excluded.generated_units, cursor_model_events.generated_units),
                    input_tokens=COALESCE(excluded.input_tokens, cursor_model_events.input_tokens),
                    output_tokens=COALESCE(excluded.output_tokens, cursor_model_events.output_tokens),
                    latency_ms=COALESCE(excluded.latency_ms, cursor_model_events.latency_ms),
                    ttft_ms=COALESCE(excluded.ttft_ms, cursor_model_events.ttft_ms),
                    status=COALESCE(excluded.status, cursor_model_events.status),
                    error_text=COALESCE(excluded.error_text, cursor_model_events.error_text)
                """,
                (
                    event.get("id"),
                    event.get("task_id"),
                    event.get("parent_task_id"),
                    event.get("request_id"),
                    event.get("selected_model"),
                    event.get("resolved_model"),
                    event.get("route_kind"),
                    event.get("event_source"),
                    event.get("confidence"),
                    event.get("generated_units", 0),
                    event.get("input_tokens"),
                    event.get("output_tokens"),
                    event.get("latency_ms"),
                    event.get("ttft_ms"),
                    event.get("status"),
                    event.get("error_text"),
                    event.get("timestamp"),
                ),
            )
            conn.commit()

    def save_cursor_import_state(
        self, source_path: str, last_offset: int, last_inode: str, last_seen_at: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cursor_import_state (source_path, last_offset, last_inode, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    last_offset=excluded.last_offset,
                    last_inode=excluded.last_inode,
                    last_seen_at=excluded.last_seen_at
                """,
                (source_path, last_offset, last_inode, last_seen_at),
            )
            conn.commit()

    def get_cursor_import_state(self, source_path: str) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM cursor_import_state WHERE source_path = ?",
                (source_path,),
            ).fetchone()
            return dict(row) if row else {}

    def get_cursor_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM cursor_tasks
                WHERE task_id = ? OR task_id LIKE ?
                ORDER BY CASE WHEN task_id = ? THEN 0 ELSE 1 END, length(task_id) DESC
                """,
                (task_id, f"{task_id}%", task_id),
            ).fetchall()
            return dict(rows[0]) if rows else None

    def delete_cursor_tasks(self, task_ids: List[str]) -> int:
        """Remove top-level task rows (e.g. subagent IDs incorrectly upserted)."""
        if not task_ids:
            return 0
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ",".join("?" for _ in task_ids)
            cur = conn.execute(
                f"DELETE FROM cursor_tasks WHERE task_id IN ({placeholders})",
                list(task_ids),
            )
            conn.commit()
            return int(cur.rowcount or 0)

    def purge_malformed_cursor_ids(self) -> int:
        """Remove events/tasks whose IDs contain newlines (bad hook payloads)."""
        with sqlite3.connect(self.db_path) as conn:
            cur_e = conn.execute(
                """
                DELETE FROM cursor_model_events
                WHERE instr(task_id, char(10)) > 0
                   OR instr(task_id, char(13)) > 0
                   OR instr(IFNULL(parent_task_id, ''), char(10)) > 0
                """
            )
            cur_t = conn.execute(
                """
                DELETE FROM cursor_tasks
                WHERE instr(task_id, char(10)) > 0
                   OR instr(task_id, char(13)) > 0
                """
            )
            conn.commit()
            return int((cur_e.rowcount or 0) + (cur_t.rowcount or 0))

    def list_cursor_tasks(
        self,
        since: Optional[str] = None,
        limit: int = 20,
        auto_only: bool = False,
    ) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Exclude subagent / child task IDs that only exist under a parent.
            query = """
                SELECT * FROM cursor_tasks
                WHERE task_id NOT IN (
                    SELECT DISTINCT task_id FROM cursor_model_events
                    WHERE parent_task_id IS NOT NULL AND parent_task_id != ''
                )
            """
            params: List[Any] = []
            if since:
                query += " AND COALESCE(started_at, '') >= ?"
                params.append(since)
            if auto_only:
                query += " AND route_kind IN ('auto', 'mixed')"
            query += " ORDER BY COALESCE(started_at, '') DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_cursor_events_for_task(
        self, task_id: str, since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM cursor_model_events WHERE task_id = ?"
            params: List[Any] = [task_id]
            if since:
                query += " AND COALESCE(timestamp, '') >= ?"
                params.append(since)
            query += " ORDER BY timestamp ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_cursor_events_for_session(
        self, root_task_id: str, since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Root-task events ∪ one-level child events (parent_task_id = root)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = (
                "SELECT * FROM cursor_model_events "
                "WHERE task_id = ? OR parent_task_id = ?"
            )
            params: List[Any] = [root_task_id, root_task_id]
            if since:
                query += " AND COALESCE(timestamp, '') >= ?"
                params.append(since)
            query += " ORDER BY timestamp ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_cursor_subagents(self, parent_task_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT task_id, COUNT(DISTINCT request_id) AS request_count,
                       SUM(generated_units) AS code_units
                FROM cursor_model_events
                WHERE parent_task_id = ?
                GROUP BY task_id
                """,
                (parent_task_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_cursor_task(self) -> Optional[Dict[str, Any]]:
        tasks = self.list_cursor_tasks(limit=1)
        return tasks[0] if tasks else None

    # ============== Blindtest 推断 ==============

    def save_blindtest_inference(self, inf: Dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO blindtest_inferences (
                    task_id, turn_index, request_id,
                    inferred_model, probability, model_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, turn_index, model_version) DO UPDATE SET
                    request_id=excluded.request_id,
                    inferred_model=excluded.inferred_model,
                    probability=excluded.probability,
                    created_at=excluded.created_at
                """,
                (
                    inf.get("task_id"),
                    inf.get("turn_index", 0),
                    inf.get("request_id"),
                    inf.get("inferred_model"),
                    inf.get("probability"),
                    inf.get("model_version"),
                    inf.get("created_at", datetime.utcnow().isoformat()),
                ),
            )
            conn.commit()

    def get_blindtest_inferences(self, task_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM blindtest_inferences
                WHERE task_id = ? OR task_id LIKE ?
                ORDER BY turn_index ASC
                """,
                (task_id, f"{task_id}%"),
            ).fetchall()
            return [dict(row) for row in rows]

    def search_cursor_tasks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM cursor_tasks
                WHERE title LIKE ? OR task_id LIKE ?
                ORDER BY COALESCE(started_at, '') DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            return [dict(row) for row in rows]
