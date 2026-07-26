"""
盲测特征提取 — 从单个 assistant turn 提取确定性特征向量。

设计原则：
- 全部特征确定性可复现（哈希用 md5，不依赖 PYTHONHASHSEED）
- 隐私友好：n-gram / 标识符只存哈希桶频率，不落原文或代码正文
- 特征族：文风（text）/ 行为（tools）/ 时延（latency）/ 轻量代码风格（LPcodedec 思路）
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

# 哈希桶大小（特征维度权衡：语料小，桶不宜过大）
CHAR_NGRAM_BUCKETS = 64
TOOL_NAME_BUCKETS = 16
OPENING_BUCKETS = 16
IDENT_BUCKETS = 16

_BULLET_RE = re.compile(r"^\s*[-*•]\s+")
_NUMBERED_RE = re.compile(r"^\s*\d+[.、)]\s+")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s+")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_FENCE_BLOCK_RE = re.compile(r"```[\w.+-]*\n(.*?)```", re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]|\.(?:\s|$)|\n")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_CAMEL_RE = re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b")
_PASCAL_RE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b")
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")


@dataclass
class TurnRecord:
    """一个样本单元：一次用户请求对应的全部 assistant 输出。"""

    conversation_id: str
    turn_index: int
    assistant_texts: List[str] = field(default_factory=list)
    tool_batches: List[List[str]] = field(default_factory=list)
    thinking_texts: List[str] = field(default_factory=list)
    user_timestamp: Optional[datetime] = None
    request_id: Optional[str] = None
    ttft_ms: Optional[float] = None
    duration_ms: Optional[float] = None
    label: Optional[str] = None
    label_source: Optional[str] = None

    @property
    def full_text(self) -> str:
        return "\n\n".join(t for t in self.assistant_texts if t)


def _hash_bucket(token: str, buckets: int) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % buckets


def _char_class(ch: str) -> str:
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "cjk"
    if ch.isascii() and ch.isalpha():
        return "latin"
    if ch.isdigit():
        return "digit"
    if ch.isspace():
        return "space"
    return "other"


def _is_emoji(ch: str) -> bool:
    code = ord(ch)
    return (
        0x1F300 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or code in (0x2705, 0x274C, 0x2757, 0x2B50)
    )


def _per_kb(count: int, n_chars: int) -> float:
    if n_chars <= 0:
        return 0.0
    return count * 1000.0 / n_chars


def _text_style_features(text: str) -> Dict[str, float]:
    feats: Dict[str, float] = {}
    n = len(text)
    feats["txt_chars_log"] = math.log1p(n)
    if n == 0:
        return feats

    counts = {"cjk": 0, "latin": 0, "digit": 0, "space": 0, "other": 0}
    emoji = 0
    punct_counts = {
        "punct_cn": 0,  # ，。；：！？、
        "punct_en": 0,  # ,.;:!?
        "dash": 0,  # — –
        "ellipsis": 0,  # … or ...
        "paren_cn": 0,  # （）「」《》
        "backtick": 0,
    }
    for ch in text:
        counts[_char_class(ch)] += 1
        if _is_emoji(ch):
            emoji += 1
        if ch in "，。；：！？、":
            punct_counts["punct_cn"] += 1
        elif ch in ",.;:!?":
            punct_counts["punct_en"] += 1
        elif ch in "—–":
            punct_counts["dash"] += 1
        elif ch == "…":
            punct_counts["ellipsis"] += 1
        elif ch in "（）「」《》【】":
            punct_counts["paren_cn"] += 1
        elif ch == "`":
            punct_counts["backtick"] += 1

    non_space = max(1, n - counts["space"])
    feats["txt_cjk_ratio"] = counts["cjk"] / non_space
    feats["txt_latin_ratio"] = counts["latin"] / non_space
    feats["txt_digit_ratio"] = counts["digit"] / non_space
    feats["txt_emoji_per_kb"] = _per_kb(emoji, n)
    for key, val in punct_counts.items():
        feats[f"txt_{key}_per_kb"] = _per_kb(val, n)
    feats["txt_ellipsis_per_kb"] += _per_kb(text.count("..."), n)

    lines = text.split("\n")
    n_lines = max(1, len(lines))
    feats["txt_bullet_line_ratio"] = sum(1 for l in lines if _BULLET_RE.match(l)) / n_lines
    feats["txt_numbered_line_ratio"] = sum(1 for l in lines if _NUMBERED_RE.match(l)) / n_lines
    feats["txt_header_line_ratio"] = sum(1 for l in lines if _HEADER_RE.match(l)) / n_lines
    feats["txt_table_line_ratio"] = sum(1 for l in lines if _TABLE_RE.match(l)) / n_lines
    feats["txt_blank_line_ratio"] = sum(1 for l in lines if not l.strip()) / n_lines
    feats["txt_avg_line_len"] = n / n_lines

    feats["txt_bold_per_kb"] = _per_kb(len(_BOLD_RE.findall(text)), n)
    feats["txt_inline_code_per_kb"] = _per_kb(len(_INLINE_CODE_RE.findall(text)), n)
    feats["txt_fence_count"] = float(len(_FENCE_RE.findall(text)))

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if sentences:
        lens = [len(s) for s in sentences]
        mean_len = sum(lens) / len(lens)
        feats["txt_sentence_mean_len"] = mean_len
        feats["txt_sentence_len_std"] = math.sqrt(
            sum((x - mean_len) ** 2 for x in lens) / len(lens)
        )
        feats["txt_sentence_count_log"] = math.log1p(len(sentences))

    words = _LATIN_WORD_RE.findall(text)
    if words:
        feats["txt_latin_word_avg_len"] = sum(len(w) for w in words) / len(words)

    return feats


def _char_ngram_features(text: str, max_chars: int = 20000) -> Dict[str, float]:
    """字符 3-gram 哈希桶频率（小写、空白折叠、去 markdown 记号影响小）。"""
    normalized = re.sub(r"\s+", " ", text.lower())[:max_chars]
    if len(normalized) < 3:
        return {}
    buckets = [0] * CHAR_NGRAM_BUCKETS
    total = 0
    for i in range(len(normalized) - 2):
        gram = normalized[i : i + 3]
        buckets[_hash_bucket(gram, CHAR_NGRAM_BUCKETS)] += 1
        total += 1
    if total == 0:
        return {}
    return {
        f"ng3_{i:02d}": buckets[i] / total
        for i in range(CHAR_NGRAM_BUCKETS)
        if buckets[i] > 0
    }


def _opening_features(assistant_texts: List[str]) -> Dict[str, float]:
    """开场句式：首条 assistant 文本的前缀哈希 + 首字符类别。"""
    feats: Dict[str, float] = {}
    first = next((t for t in assistant_texts if t and t.strip()), "")
    first = first.strip()
    if not first:
        return feats
    prefix = re.sub(r"\s+", " ", first[:24].lower())
    feats[f"open_h{_hash_bucket(prefix, OPENING_BUCKETS):02d}"] = 1.0
    first_ch = first[0]
    feats[f"open_class_{_char_class(first_ch)}"] = 1.0
    return feats


def _behavior_features(turn: TurnRecord) -> Dict[str, float]:
    feats: Dict[str, float] = {}
    n_msgs = max(len(turn.assistant_texts), len(turn.tool_batches), 1)
    feats["beh_msgs_log"] = math.log1p(n_msgs)

    batches = [b for b in turn.tool_batches if b]
    total_tools = sum(len(b) for b in batches)
    feats["beh_tools_total_log"] = math.log1p(total_tools)
    feats["beh_tools_per_msg"] = total_tools / n_msgs
    feats["beh_batch_count_log"] = math.log1p(len(batches))
    if batches:
        parallel = sum(1 for b in batches if len(b) >= 2)
        feats["beh_parallel_batch_ratio"] = parallel / len(batches)
        feats["beh_max_batch_size"] = float(max(len(b) for b in batches))
        feats["beh_avg_batch_size"] = total_tools / len(batches)
    else:
        feats["beh_parallel_batch_ratio"] = 0.0
        feats["beh_max_batch_size"] = 0.0
        feats["beh_avg_batch_size"] = 0.0

    distinct = {name for b in batches for name in b}
    feats["beh_distinct_tools"] = float(len(distinct))
    if total_tools > 0:
        tool_buckets = [0] * TOOL_NAME_BUCKETS
        for b in batches:
            for name in b:
                tool_buckets[_hash_bucket(name, TOOL_NAME_BUCKETS)] += 1
        for i in range(TOOL_NAME_BUCKETS):
            if tool_buckets[i] > 0:
                feats[f"tool_h{i:02d}"] = tool_buckets[i] / total_tools

    texts_with_content = sum(1 for t in turn.assistant_texts if t and t.strip())
    feats["beh_text_msg_ratio"] = texts_with_content / n_msgs
    if texts_with_content:
        feats["beh_avg_text_len_log"] = math.log1p(
            sum(len(t) for t in turn.assistant_texts if t) / texts_with_content
        )

    think_chars = sum(len(t) for t in turn.thinking_texts)
    feats["beh_think_chars_log"] = math.log1p(think_chars)
    return feats


def _latency_features(turn: TurnRecord) -> Dict[str, float]:
    feats: Dict[str, float] = {}
    if turn.ttft_ms is not None and turn.ttft_ms >= 0:
        feats["lat_ttft_present"] = 1.0
        feats["lat_ttft_log"] = math.log1p(turn.ttft_ms)
    if turn.duration_ms is not None and turn.duration_ms >= 0:
        feats["lat_duration_present"] = 1.0
        feats["lat_duration_log"] = math.log1p(turn.duration_ms)
    # 输出长度（时序通道的一部分；不落正文）
    out_chars = sum(len(t) for t in turn.assistant_texts)
    if out_chars > 0:
        feats["lat_out_chars_log"] = math.log1p(out_chars)
    return feats


# 特征通道：消融实验用前缀约定
FEATURE_CHANNELS: Dict[str, Tuple[str, ...]] = {
    "text": ("txt_", "ng3_", "open_"),
    "code": ("code_",),
    "behavior": ("beh_",),
    "latency": ("lat_",),
}
ALL_CHANNELS: Tuple[str, ...] = ("text", "code", "behavior", "latency")


def parse_channels(
    channels: Optional[Sequence[str]] = None,
    *,
    ablate: Optional[Sequence[str]] = None,
) -> Tuple[str, ...]:
    """解析 --channels / --ablate；默认全通道。"""
    selected = set(ALL_CHANNELS if channels is None else channels)
    unknown = selected - set(ALL_CHANNELS)
    if unknown:
        raise ValueError(f"unknown feature channels: {sorted(unknown)}")
    if ablate:
        drop = set(ablate)
        unknown_a = drop - set(ALL_CHANNELS)
        if unknown_a:
            raise ValueError(f"unknown ablate channels: {sorted(unknown_a)}")
        selected -= drop
    if not selected:
        raise ValueError("no feature channels left after ablate")
    return tuple(c for c in ALL_CHANNELS if c in selected)


def filter_features_by_channels(
    features: Dict[str, float], channels: Sequence[str]
) -> Dict[str, float]:
    """按通道前缀保留特征（用于消融 train/eval，无需重建语料）。"""
    prefixes: List[str] = []
    for ch in channels:
        if ch not in FEATURE_CHANNELS:
            raise ValueError(f"unknown feature channel: {ch}")
        prefixes.extend(FEATURE_CHANNELS[ch])
    return {
        k: v
        for k, v in features.items()
        if any(k.startswith(p) for p in prefixes)
    }


def _extract_code_blobs(text: str) -> str:
    """Pull fenced code only — never store raw blobs, only derived stats."""
    blocks = _FENCE_BLOCK_RE.findall(text)
    if blocks:
        return "\n".join(blocks)
    # Fallback: lines that look like indented code without fences
    code_lines = [
        ln
        for ln in text.split("\n")
        if ln.startswith("    ") or ln.startswith("\t") or ln.strip().startswith(("def ", "class ", "function ", "import ", "from "))
    ]
    return "\n".join(code_lines)


def _code_style_features(text: str) -> Dict[str, float]:
    """Lightweight LPcodedec-inspired code stylometry (hashed / ratios only)."""
    feats: Dict[str, float] = {}
    code = _extract_code_blobs(text)
    n = len(code)
    feats["code_chars_log"] = math.log1p(n)
    feats["code_present"] = 1.0 if n > 0 else 0.0
    if n == 0:
        return feats

    lines = code.split("\n")
    n_lines = max(1, len(lines))
    comment_lines = sum(
        1
        for ln in lines
        if ln.lstrip().startswith(("#", "//", "/*", "*", "--"))
    )
    blank = sum(1 for ln in lines if not ln.strip())
    feats["code_comment_line_ratio"] = comment_lines / n_lines
    feats["code_blank_line_ratio"] = blank / n_lines
    feats["code_avg_line_len"] = n / n_lines

    snake = len(_SNAKE_RE.findall(code))
    camel = len(_CAMEL_RE.findall(code))
    pascal = len(_PASCAL_RE.findall(code))
    naming_total = max(1, snake + camel + pascal)
    feats["code_snake_ratio"] = snake / naming_total
    feats["code_camel_ratio"] = camel / naming_total
    feats["code_pascal_ratio"] = pascal / naming_total

    idents = _IDENT_RE.findall(code)
    if idents:
        buckets = [0] * IDENT_BUCKETS
        for ident in idents[:500]:
            buckets[_hash_bucket(ident.lower(), IDENT_BUCKETS)] += 1
        total = sum(buckets) or 1
        for i, c in enumerate(buckets):
            if c:
                feats[f"code_id_h{i:02d}"] = c / total
        feats["code_ident_avg_len"] = sum(len(i) for i in idents) / len(idents)

    # Structural punctuation density (no AST dependency)
    for name, chs in (
        ("brace", "{}"),
        ("paren", "()"),
        ("bracket", "[]"),
        ("semicolon", ";"),
        ("colon", ":"),
    ):
        feats[f"code_{name}_per_kb"] = _per_kb(sum(code.count(c) for c in chs), n)

    return feats


def _text_extra_features(text: str) -> Dict[str, float]:
    """Small text-side enhancements without heavy NLP deps."""
    feats: Dict[str, float] = {}
    n = len(text)
    if n == 0:
        return feats
    # Question / hedge markers (language-agnostic counts)
    feats["txt_qmark_per_kb"] = _per_kb(text.count("?") + text.count("？"), n)
    hedges = ("可能", "或许", "大概", "might", "perhaps", "probably", "seems")
    hedge_hits = sum(text.lower().count(h) for h in hedges)
    feats["txt_hedge_per_kb"] = _per_kb(hedge_hits, n)
    # Code-to-prose balance already partially in fence_count; add ratio of fenced chars
    code = _extract_code_blobs(text)
    feats["txt_code_char_ratio"] = len(code) / max(1, n)
    return feats


def extract_features(turn: TurnRecord) -> Dict[str, float]:
    """确定性特征提取：文风 + n-gram + 开场 + 行为 + 时延 + 代码风格。"""
    text = turn.full_text
    feats: Dict[str, float] = {}
    feats.update(_text_style_features(text))
    feats.update(_text_extra_features(text))
    feats.update(_char_ngram_features(text))
    feats.update(_opening_features(turn.assistant_texts))
    feats.update(_behavior_features(turn))
    feats.update(_latency_features(turn))
    feats.update(_code_style_features(text))
    return feats
