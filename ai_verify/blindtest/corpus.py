"""
盲测语料构建 — 从 agent transcripts 提取 turn 样本并关联模型标签。

标签来源（优先级从高到低）：
1. hook `model_id`（非 default；按 generation_id / requestId join）— 最高优先级事实
2. structured logs `Starting stream request`(modelName != default)，按 用户消息时间戳 ↔ 请求时间 就近对齐
3. ai_code_hashes.model（非 default，按对齐得到的 requestId join）
4. 会话级统一标签：该会话全部请求均为同一非 default 模型时整体打标

Ground-truth 训练：只用**手选会话**（明确手动选模或 hook/tracking 已给出非 default
标签的会话）构建语料；纯 Auto / default 不可见请求不得当作 GT 标签。

隐私：语料只保存特征向量与哈希，不落原始文本。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ai_verify.blindtest.features import TurnRecord, extract_features
from ai_verify.cursor_logs import iter_log_events

DEFAULT_BLINDTEST_DIR = Path.home() / ".ai-verify" / "blindtest"
CORPUS_FILENAME = "corpus.json"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TS_RE = re.compile(
    r"<timestamp>\s*\w+,?\s+(\w{3})\w*\.?\s+(\d{1,2}),\s*(\d{4}),?\s*(\d{1,2}):(\d{2})\s*(AM|PM)",
    re.IGNORECASE,
)

# 用户消息与请求开始时间的对齐窗口（用户 timestamp 只有分钟精度）
MATCH_BEFORE_S = 180
MATCH_AFTER_S = 900


def _naive_dt(value: Optional[datetime]) -> Optional[datetime]:
    """统一为 naive datetime，避免 hook(aware) 与 structured log(naive) 混排报错。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


@dataclass
class CorpusSample:
    conversation_id: str
    turn_index: int
    request_id: Optional[str]
    label: Optional[str]
    label_source: Optional[str]
    ttft_ms: Optional[float]
    features: Dict[str, float]


@dataclass
class Corpus:
    samples: List[CorpusSample] = field(default_factory=list)
    built_at: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def labeled(self) -> List[CorpusSample]:
        return [s for s in self.samples if s.label]


def parse_user_timestamp(text: str) -> Optional[datetime]:
    """解析用户消息中的 <timestamp>Friday, Jul 3, 2026, 10:12 AM (UTC+8)</timestamp>。"""
    m = _TS_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group(1).lower())
    if not month:
        return None
    hour = int(m.group(4)) % 12
    if m.group(6).upper() == "PM":
        hour += 12
    try:
        return datetime(int(m.group(3)), month, int(m.group(2)), hour, int(m.group(5)))
    except ValueError:
        return None


# ---------------------------------------------------------------- transcripts


def extract_turns(jsonl_path: Path, conversation_id: Optional[str] = None) -> List[TurnRecord]:
    """把一个 transcript jsonl 切分为 per-turn 记录。

    切分规则：每条 role=user 记录开启一个新 turn；其后的 assistant 记录
    （文本块 / tool_use 批次 / thinking 块）归入当前 turn。
    """
    cid = conversation_id or jsonl_path.stem
    turns: List[TurnRecord] = []
    current: Optional[TurnRecord] = None

    with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = obj.get("role")
            message = obj.get("message") or {}
            content = message.get("content") or []
            if not isinstance(content, list):
                continue

            if role == "user":
                current = TurnRecord(conversation_id=cid, turn_index=len(turns))
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        ts = parse_user_timestamp(blk.get("text") or "")
                        if ts and current.user_timestamp is None:
                            current.user_timestamp = ts
                turns.append(current)
            elif role == "assistant" and current is not None:
                batch: List[str] = []
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    btype = blk.get("type")
                    if btype == "text":
                        current.assistant_texts.append(blk.get("text") or "")
                    elif btype == "tool_use":
                        batch.append(str(blk.get("name") or "unknown"))
                    elif btype == "thinking":
                        current.thinking_texts.append(blk.get("thinking") or blk.get("text") or "")
                if batch:
                    current.tool_batches.append(batch)

    # 过滤空 turn（无 assistant 产出）
    kept = [t for t in turns if t.assistant_texts or t.tool_batches]
    for i, t in enumerate(kept):
        t.turn_index = i
    return kept


def discover_transcript_files(projects_dir: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """返回 (conversation_id, jsonl_path)。同一会话多处存在时取文件最大的。"""
    root = projects_dir or (Path.home() / ".cursor" / "projects")
    if not root.is_dir():
        return []
    best: Dict[str, Path] = {}
    for project in root.iterdir():
        transcripts = project / "agent-transcripts"
        if not transcripts.is_dir():
            continue
        for task_dir in transcripts.iterdir():
            if not task_dir.is_dir():
                continue
            main = task_dir / f"{task_dir.name}.jsonl"
            candidates = [main] if main.is_file() else []
            sub_dir = task_dir / "subagents"
            if sub_dir.is_dir():
                candidates.extend(sub_dir.glob("*.jsonl"))
            for path in candidates:
                cid = path.stem
                prev = best.get(cid)
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if prev is None or size > prev.stat().st_size:
                    best[cid] = path
    return sorted(best.items())


# ---------------------------------------------------------------- label index


@dataclass
class RequestEvent:
    conversation_id: str
    request_id: Optional[str]
    model: Optional[str]  # None 表示不可见（default）
    timestamp: Optional[datetime]
    ttft_ms: Optional[float] = None
    source: str = "structured_log"


class LabelIndex:
    """按会话组织的请求级标签索引，支持时间就近对齐。"""

    def __init__(self) -> None:
        self.by_conversation: Dict[str, List[RequestEvent]] = {}
        self.hash_models: Dict[str, str] = {}  # request_id -> model (非 default)
        self.hook_models: Dict[str, str] = {}  # request_id -> hook model_id (非 default)

    def add_event(self, ev: RequestEvent) -> None:
        self.by_conversation.setdefault(ev.conversation_id, []).append(ev)

    def finalize(self) -> None:
        for events in self.by_conversation.values():
            events.sort(key=lambda e: _naive_dt(e.timestamp) or datetime.min)

    def resolve_model(
        self, request_id: Optional[str], event_model: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """返回 (model, label_source)；hook > event > hashes。"""
        rid = request_id or ""
        if rid and rid in self.hook_models:
            return self.hook_models[rid], "hook"
        if event_model:
            return event_model, None  # caller sets source from event
        if rid and rid in self.hash_models:
            return self.hash_models[rid], "ai_code_hashes"
        return None, None

    def uniform_label(self, conversation_id: str) -> Optional[str]:
        events = self.by_conversation.get(conversation_id, [])
        if not events:
            return None
        models = set()
        for ev in events:
            model, _ = self.resolve_model(ev.request_id, ev.model)
            if model is None:
                return None  # 存在不可见请求 → 不能整体打标
            models.add(model)
        return models.pop() if len(models) == 1 else None

    def match_turn(
        self, conversation_id: str, user_ts: Optional[datetime], used: set
    ) -> Optional[RequestEvent]:
        """把 turn 的用户时间戳对齐到最近的请求事件（每个事件只用一次）。"""
        user_naive = _naive_dt(user_ts)
        if user_naive is None:
            return None
        candidates = []
        for i, ev in enumerate(self.by_conversation.get(conversation_id, [])):
            ev_ts = _naive_dt(ev.timestamp)
            if i in used or ev_ts is None:
                continue
            delta = (ev_ts - user_naive).total_seconds()
            if -MATCH_BEFORE_S <= delta <= MATCH_AFTER_S:
                candidates.append((abs(delta), i, ev))
        if not candidates:
            return None
        _, idx, ev = min(candidates, key=lambda c: (c[0], c[1]))
        used.add(idx)
        return ev


def _parse_hook_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _naive_dt(datetime.fromisoformat(text))
    except ValueError:
        return None


def build_label_index(
    logs_dir: Optional[Path] = None,
    tracking_db: Optional[Path] = None,
    ai_verify_db: Optional[Path] = None,
    hook_event_paths: Optional[List[Path]] = None,
) -> LabelIndex:
    """扫描 hooks + structured logs + ai_code_hashes (+ 可选 cursor_model_events)。"""
    index = LabelIndex()

    # 0. hooks：model_id 为最高优先级标签（仅非 default）
    from ai_verify.cursor_hook_events import default_hook_event_paths, iter_hook_events

    if hook_event_paths is not None:
        paths = hook_event_paths
    elif logs_dir is None and tracking_db is None:
        # Full discover mode (CLI) — include default hook NDJSON paths.
        paths = default_hook_event_paths()
    else:
        # Fixture / explicit path mode — do not pull host ~/.ai-verify hooks.
        paths = []
    for hook_path in paths:
        try:
            for hev in iter_hook_events(hook_path):
                mid = hev.model_id or hev.subagent_model
                if not mid or mid == "default":
                    continue
                rid = hev.generation_id
                if rid:
                    index.hook_models[rid] = mid
                if hev.conversation_id:
                    index.add_event(
                        RequestEvent(
                            conversation_id=hev.conversation_id,
                            request_id=rid,
                            model=mid,
                            timestamp=_parse_hook_timestamp(hev.received_at),
                            source="hook",
                        )
                    )
        except OSError:
            continue

    # 1. structured logs：stream_start 提供 (conversation, request, model, ts)，
    #    turn_outcome 提供 ttft_ms
    log_files: List[Path] = []
    if logs_dir is None:
        from ai_verify.providers.cursor import discover_cursor_paths, probe_structured_logs

        paths_c = discover_cursor_paths()
        if paths_c.logs_dir:
            log_files = [
                f for f in probe_structured_logs(paths_c.logs_dir)
                if "Structured Logs" in f.name
            ]
    elif logs_dir.is_dir():
        log_files = sorted(logs_dir.glob("**/*.log"))

    ttft_by_request: Dict[str, float] = {}
    stream_events: List[RequestEvent] = []
    for log_file in log_files:
        try:
            for ev in iter_log_events(log_file):
                if ev.event_type == "stream_start" and ev.task_id:
                    model = ev.selected_model
                    stream_events.append(
                        RequestEvent(
                            conversation_id=ev.task_id,
                            request_id=ev.request_id,
                            model=model if model and model != "default" else None,
                            timestamp=ev.timestamp,
                        )
                    )
                elif ev.event_type == "turn_outcome" and ev.request_id and ev.ttft_ms:
                    ttft_by_request[ev.request_id] = ev.ttft_ms
        except OSError:
            continue

    seen_requests = set()
    for ev in stream_events:
        key = (ev.conversation_id, ev.request_id)
        if ev.request_id and key in seen_requests:
            continue
        seen_requests.add(key)
        if ev.request_id:
            ev.ttft_ms = ttft_by_request.get(ev.request_id)
        index.add_event(ev)

    # 2. ai_code_hashes：requestId -> model（非 default；不覆盖 hook）
    if tracking_db is None:
        from ai_verify.providers.cursor import discover_cursor_paths

        tracking_db = discover_cursor_paths().ai_tracking_db
    if tracking_db and Path(tracking_db).is_file():
        from ai_verify.providers.cursor import read_ai_code_hashes

        for row in read_ai_code_hashes(Path(tracking_db)):
            model = row.get("model")
            rid = row.get("requestId")
            if rid and model and model != "default" and str(rid) not in index.hook_models:
                index.hash_models[str(rid)] = str(model)

    # 3. 可选：ai-verify DB 里 confidence 较高的 resolved_model
    if ai_verify_db and Path(ai_verify_db).is_file():
        import sqlite3

        try:
            with sqlite3.connect(ai_verify_db) as conn:
                rows = conn.execute(
                    """
                    SELECT task_id, request_id, resolved_model, timestamp, ttft_ms
                    FROM cursor_model_events
                    WHERE resolved_model IS NOT NULL
                      AND resolved_model != 'default'
                      AND confidence IN ('high', 'medium-high', 'medium_high')
                    """
                ).fetchall()
        except sqlite3.Error:
            rows = []
        existing = {
            (ev.conversation_id, ev.request_id)
            for events in index.by_conversation.values()
            for ev in events
        }
        for task_id, request_id, model, ts, ttft in rows:
            if (task_id, request_id) in existing:
                continue
            parsed_ts = None
            if ts:
                try:
                    parsed_ts = _naive_dt(datetime.fromisoformat(str(ts)))
                except ValueError:
                    parsed_ts = None
            index.add_event(
                RequestEvent(
                    conversation_id=str(task_id),
                    request_id=str(request_id) if request_id else None,
                    model=str(model),
                    timestamp=parsed_ts,
                    ttft_ms=float(ttft) if ttft else None,
                    source="cursor_model_events",
                )
            )

    index.finalize()
    return index


# ---------------------------------------------------------------- build & IO


def label_turns(turns: List[TurnRecord], index: LabelIndex) -> None:
    """就地为 turns 填充 request_id / ttft_ms / label / label_source。"""
    if not turns:
        return
    cid = turns[0].conversation_id
    uniform = index.uniform_label(cid)
    used: set = set()
    for turn in turns:
        ev = index.match_turn(cid, turn.user_timestamp, used)
        if ev is not None:
            turn.request_id = ev.request_id
            turn.ttft_ms = ev.ttft_ms
            model, src = index.resolve_model(ev.request_id, ev.model)
            if model:
                turn.label = model
                turn.label_source = src or ev.source
        if turn.label is None and uniform:
            turn.label = uniform
            turn.label_source = "conversation_uniform"


def build_corpus(
    projects_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    tracking_db: Optional[Path] = None,
    ai_verify_db: Optional[Path] = None,
    hook_event_paths: Optional[List[Path]] = None,
    since: Optional[datetime] = None,
    include_unlabeled: bool = False,
    min_turn_chars: int = 1,
) -> Corpus:
    """扫描全部 transcripts，产出特征化语料。"""
    index = build_label_index(
        logs_dir=logs_dir,
        tracking_db=tracking_db,
        ai_verify_db=ai_verify_db,
        hook_event_paths=hook_event_paths,
    )

    corpus = Corpus(built_at=datetime.now().isoformat())
    n_conversations = 0
    n_turns_total = 0
    label_sources: Dict[str, int] = {}

    for cid, path in discover_transcript_files(projects_dir):
        if since is not None:
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if mtime < since:
                continue
        turns = extract_turns(path, cid)
        if not turns:
            continue
        n_conversations += 1
        n_turns_total += len(turns)
        label_turns(turns, index)
        for turn in turns:
            if len(turn.full_text) < min_turn_chars and not turn.tool_batches:
                continue
            if turn.label is None and not include_unlabeled:
                continue
            if turn.label_source:
                label_sources[turn.label_source] = label_sources.get(turn.label_source, 0) + 1
            corpus.samples.append(
                CorpusSample(
                    conversation_id=turn.conversation_id,
                    turn_index=turn.turn_index,
                    request_id=turn.request_id,
                    label=turn.label,
                    label_source=turn.label_source,
                    ttft_ms=turn.ttft_ms,
                    features=extract_features(turn),
                )
            )

    class_counts: Dict[str, int] = {}
    for s in corpus.samples:
        if s.label:
            class_counts[s.label] = class_counts.get(s.label, 0) + 1
    corpus.stats = {
        "conversations_scanned": n_conversations,
        "turns_scanned": n_turns_total,
        "samples": len(corpus.samples),
        "labeled": len(corpus.labeled),
        "class_counts": class_counts,
        "label_sources": label_sources,
    }
    return corpus


def save_corpus(corpus: Corpus, blindtest_dir: Optional[Path] = None) -> Path:
    out_dir = blindtest_dir or DEFAULT_BLINDTEST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CORPUS_FILENAME
    payload = {
        "built_at": corpus.built_at,
        "stats": corpus.stats,
        "samples": [asdict(s) for s in corpus.samples],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_corpus(blindtest_dir: Optional[Path] = None) -> Corpus:
    path = (blindtest_dir or DEFAULT_BLINDTEST_DIR) / CORPUS_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    corpus = Corpus(built_at=payload.get("built_at"), stats=payload.get("stats", {}))
    for item in payload.get("samples", []):
        corpus.samples.append(CorpusSample(**item))
    return corpus


def load_turns_for_task(
    task_id: str, projects_dir: Optional[Path] = None
) -> List[TurnRecord]:
    """按 task_id（支持前缀）加载 turns 并尽可能附加 ttft（不要求有标签）。"""
    matches = [
        (cid, path)
        for cid, path in discover_transcript_files(projects_dir)
        if cid.startswith(task_id)
    ]
    if not matches:
        return []
    cid, path = matches[0]
    turns = extract_turns(path, cid)
    index = build_label_index()
    label_turns(turns, index)
    return turns
