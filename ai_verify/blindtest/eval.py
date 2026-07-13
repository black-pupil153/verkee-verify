"""
盲测评估：selective（阈值弃权）与 forced top-1，指标落盘到 runs/。

指标：Acc@forced、Acc@τ、τ sweep、macro-F1、混淆矩阵、ECE、Brier。
隐私：只落预测/标签/特征维度元数据，不落 prompt/response 正文。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ai_verify.blindtest.classifier import (
    BlindModelClassifier,
    TrainReport,
    report_as_dict,
)
from ai_verify.blindtest.corpus import DEFAULT_BLINDTEST_DIR, Corpus, CorpusSample
from ai_verify.blindtest.splits import SealedLabel

RUNS_SUBDIR = "runs"
DEFAULT_TAU_SWEEP = (0.5, 0.6, 0.7, 0.8, 0.9)


@dataclass
class EvalReport:
    mode: str  # "forced" | "selective"
    n_samples: int
    n_conversations: int
    classes: List[str]
    threshold: Optional[float]
    accuracy: Optional[float]
    coverage: Optional[float]  # selective: 非弃权比例；forced: 1.0
    abstained: int
    macro_f1: Optional[float]
    per_class_f1: Dict[str, float]
    confusion_matrix: Dict[str, Dict[str, int]]  # true -> pred -> count
    ece: Optional[float]
    brier: Optional[float]
    tau_sweep: List[Dict[str, Any]] = field(default_factory=list)
    evaluated_at: str = ""
    split_name: Optional[str] = None
    model_path: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _top1(probs: Sequence[Tuple[str, float]]) -> Tuple[str, float]:
    return max(probs, key=lambda x: x[1])


def _predict_distribution(
    clf: BlindModelClassifier, features: Dict[str, float]
) -> List[Tuple[str, float]]:
    """返回全类别校准概率（不受 threshold 影响）。"""
    vec = clf._vectorize(features)
    probs = clf._predict_proba(vec)
    return list(zip(clf.classes, probs))


def _confusion(
    y_true: Sequence[str], y_pred: Sequence[str], classes: Sequence[str]
) -> Dict[str, Dict[str, int]]:
    matrix = {t: {p: 0 for p in classes} for t in classes}
    for t, p in zip(y_true, y_pred):
        if t not in matrix:
            matrix[t] = {c: 0 for c in classes}
        if p not in matrix[t]:
            # 预测了训练集未见类别时扩列
            for row in matrix.values():
                row.setdefault(p, 0)
            matrix[t][p] = matrix[t].get(p, 0) + 1
        else:
            matrix[t][p] += 1
    return matrix


def _f1_from_confusion(
    matrix: Dict[str, Dict[str, int]], classes: Sequence[str]
) -> Tuple[Optional[float], Dict[str, float]]:
    per: Dict[str, float] = {}
    f1s: List[float] = []
    for c in classes:
        tp = matrix.get(c, {}).get(c, 0)
        fp = sum(matrix.get(t, {}).get(c, 0) for t in matrix if t != c)
        fn = sum(v for p, v in matrix.get(c, {}).items() if p != c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        per[c] = f1
        if tp + fp + fn > 0:
            f1s.append(f1)
    macro = sum(f1s) / len(f1s) if f1s else None
    return macro, per


def expected_calibration_error(
    confidences: Sequence[float],
    correct: Sequence[bool],
    n_bins: int = 10,
) -> Optional[float]:
    if not confidences:
        return None
    bins = [[] for _ in range(n_bins)]
    for conf, hit in zip(confidences, correct):
        idx = min(n_bins - 1, max(0, int(conf * n_bins)))
        bins[idx].append((conf, 1.0 if hit else 0.0))
    ece = 0.0
    n = len(confidences)
    for bucket in bins:
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        avg_acc = sum(a for _, a in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_acc - avg_conf)
    return ece


def brier_score_multiclass(
    y_true: Sequence[str],
    prob_rows: Sequence[Dict[str, float]],
    classes: Sequence[str],
) -> Optional[float]:
    if not y_true:
        return None
    total = 0.0
    for label, probs in zip(y_true, prob_rows):
        for c in classes:
            p = probs.get(c, 0.0)
            y = 1.0 if c == label else 0.0
            total += (p - y) ** 2
    return total / len(y_true)


def evaluate_predictions(
    y_true: Sequence[str],
    predictions: Sequence[Optional[str]],
    confidences: Sequence[float],
    prob_rows: Sequence[Dict[str, float]],
    *,
    classes: Optional[Sequence[str]] = None,
    mode: str = "selective",
    threshold: Optional[float] = None,
    conversation_ids: Optional[Sequence[str]] = None,
) -> EvalReport:
    if classes is None:
        classes = sorted(set(y_true) | {p for p in predictions if p})
    classes = list(classes)

    kept_true: List[str] = []
    kept_pred: List[str] = []
    kept_conf: List[float] = []
    kept_probs: List[Dict[str, float]] = []
    abstained = 0

    for t, p, conf, pr in zip(y_true, predictions, confidences, prob_rows):
        if p is None:
            abstained += 1
            continue
        kept_true.append(t)
        kept_pred.append(p)
        kept_conf.append(conf)
        kept_probs.append(pr)

    n = len(y_true)
    coverage = (n - abstained) / n if n else None
    if kept_true:
        correct = sum(1 for t, p in zip(kept_true, kept_pred) if t == p)
        accuracy = correct / len(kept_true)
        matrix = _confusion(kept_true, kept_pred, classes)
        macro_f1, per_f1 = _f1_from_confusion(matrix, classes)
        hits = [t == p for t, p in zip(kept_true, kept_pred)]
        ece = expected_calibration_error(kept_conf, hits)
        brier = brier_score_multiclass(kept_true, kept_probs, classes)
    else:
        accuracy = None
        matrix = {c: {p: 0 for p in classes} for c in classes}
        macro_f1, per_f1 = None, {}
        ece, brier = None, None

    n_convs = len(set(conversation_ids)) if conversation_ids else 0
    return EvalReport(
        mode=mode,
        n_samples=n,
        n_conversations=n_convs,
        classes=classes,
        threshold=threshold,
        accuracy=accuracy,
        coverage=coverage if mode == "selective" else 1.0,
        abstained=abstained if mode == "selective" else 0,
        macro_f1=macro_f1,
        per_class_f1=per_f1,
        confusion_matrix=matrix,
        ece=ece,
        brier=brier,
        evaluated_at=datetime.now().isoformat(),
    )


def evaluate_classifier(
    clf: BlindModelClassifier,
    samples: Sequence[CorpusSample],
    *,
    forced: bool = False,
    tau: Optional[float] = None,
    sweep: bool = False,
    sweep_taus: Sequence[float] = DEFAULT_TAU_SWEEP,
    sealed: Optional[Dict[Tuple[str, int], SealedLabel]] = None,
    split_name: Optional[str] = None,
    model_path: Optional[str] = None,
) -> EvalReport:
    """对带标签样本（或密封标签）评估。"""
    threshold = tau if tau is not None else clf.threshold
    y_true: List[str] = []
    preds: List[Optional[str]] = []
    confs: List[float] = []
    prob_rows: List[Dict[str, float]] = []
    conv_ids: List[str] = []

    for s in samples:
        label = s.label
        if label is None and sealed is not None:
            sealed_lab = sealed.get((s.conversation_id, s.turn_index))
            if sealed_lab is None:
                continue
            label = sealed_lab.label
        if label is None:
            continue
        dist = _predict_distribution(clf, s.features)
        top_model, top_prob = _top1(dist)
        y_true.append(label)
        confs.append(top_prob)
        prob_rows.append({m: p for m, p in dist})
        conv_ids.append(s.conversation_id)
        if forced:
            preds.append(top_model)
        else:
            preds.append(top_model if top_prob >= threshold else None)

    classes = sorted(set(y_true) | set(clf.classes))
    report = evaluate_predictions(
        y_true,
        preds,
        confs,
        prob_rows,
        classes=classes,
        mode="forced" if forced else "selective",
        threshold=None if forced else threshold,
        conversation_ids=conv_ids,
    )
    report.split_name = split_name
    report.model_path = model_path

    if sweep and not forced:
        top_models = [_top1(list(pr.items()))[0] for pr in prob_rows]
        sweep_rows: List[Dict[str, Any]] = []
        for t in sweep_taus:
            sel_preds = [m if c >= t else None for m, c in zip(top_models, confs)]
            sub = evaluate_predictions(
                y_true,
                sel_preds,
                confs,
                prob_rows,
                classes=classes,
                mode="selective",
                threshold=t,
                conversation_ids=conv_ids,
            )
            sweep_rows.append(
                {
                    "tau": t,
                    "accuracy": sub.accuracy,
                    "coverage": sub.coverage,
                    "abstained": sub.abstained,
                    "macro_f1": sub.macro_f1,
                    "ece": sub.ece,
                    "brier": sub.brier,
                }
            )
        report.tau_sweep = sweep_rows

    return report


def new_run_dir(blindtest_dir: Optional[Path] = None) -> Path:
    base = (blindtest_dir or DEFAULT_BLINDTEST_DIR) / RUNS_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / ts
    # 避免同秒冲突
    suffix = 0
    while path.exists():
        suffix += 1
        path = base / f"{ts}-{suffix}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def save_run_artifacts(
    run_dir: Path,
    *,
    train_report: Optional[TrainReport] = None,
    eval_reports: Optional[Sequence[EvalReport]] = None,
    auto_report: Optional[AutoEvalReport] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Path:
    """将 TrainReport / EvalReport / AutoEvalReport 写入 runs/<ts>/，不含正文。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    if train_report is not None:
        (run_dir / "train_report.json").write_text(
            json.dumps(report_as_dict(train_report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if eval_reports:
        payload = [asdict(r) for r in eval_reports]
        (run_dir / "eval_report.json").write_text(
            json.dumps(payload if len(payload) > 1 else payload[0], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if auto_report is not None:
        (run_dir / "auto_eval_report.json").write_text(
            json.dumps(asdict(auto_report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if meta:
        (run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return run_dir


def report_eval_as_dict(report: EvalReport) -> Dict[str, Any]:
    return asdict(report)


@dataclass
class AutoEvalReport:
    """Auto 集弱验证（无完整 GT；factual 子集可核对）。"""

    n_tasks: int
    n_turns: int
    coverage: float  # (fact ∪ inferred) / turns
    opaque_residual: float  # 仍 pending-infer（或 auto-opaque）/ turns → 目标 0
    agree_with_fact: Optional[float]  # Acc(inferred, factual) where factual ≠ default
    n_fact_pairs: int  # 参与 agree_with_fact 的 turn 数
    n_factual: int
    n_inferred_only: int
    n_opaque: int
    evaluated_at: str = ""
    notes: List[str] = field(default_factory=list)


def evaluate_auto_reports(
    reports: Sequence[Any],
    *,
    pending_bucket: str = "pending-infer",
    opaque_bucket: str = "auto-opaque",
) -> AutoEvalReport:
    """从 TaskUsageReport 列表汇总 Auto 弱验证指标。

    不读 prompt/response；只用 per_request 上的 resolved/selected 与 inferred。
    """
    opaque_set = {pending_bucket, opaque_bucket}
    n_tasks = 0
    n_turns = 0
    n_covered = 0
    n_opaque = 0
    n_factual = 0
    n_inferred_only = 0
    n_agree = 0
    n_fact_pairs = 0
    notes: List[str] = []

    for report in reports:
        per_request = getattr(report, "per_request", None) or []
        if not per_request:
            continue
        n_tasks += 1
        for row in per_request:
            n_turns += 1
            resolved = row.get("resolved_model")
            selected = row.get("selected_model")
            fact_name = None
            for cand in (resolved, selected):
                if cand and cand not in ("", "default") and cand not in opaque_set:
                    fact_name = cand
                    break
            inferred = row.get("inferred_model")
            bucket = row.get("bucket")

            if bucket in opaque_set:
                n_opaque += 1
            else:
                n_covered += 1
                if fact_name:
                    n_factual += 1
                elif inferred:
                    n_inferred_only += 1

            if fact_name and inferred:
                n_fact_pairs += 1
                if str(inferred).lower() == str(fact_name).lower():
                    n_agree += 1

    if n_turns == 0:
        notes.append("no Auto turns found in reports")
    coverage = (n_covered / n_turns) if n_turns else 0.0
    opaque_residual = (n_opaque / n_turns) if n_turns else 0.0
    agree = (n_agree / n_fact_pairs) if n_fact_pairs else None

    return AutoEvalReport(
        n_tasks=n_tasks,
        n_turns=n_turns,
        coverage=coverage,
        opaque_residual=opaque_residual,
        agree_with_fact=agree,
        n_fact_pairs=n_fact_pairs,
        n_factual=n_factual,
        n_inferred_only=n_inferred_only,
        n_opaque=n_opaque,
        evaluated_at=datetime.now().isoformat(),
        notes=notes,
    )


def evaluate_auto_from_db(
    db: Any,
    *,
    task_ids: Optional[Sequence[str]] = None,
    auto_only: bool = True,
    limit: int = 50,
    auto_infer: bool = True,
) -> AutoEvalReport:
    """从本机 DB 拉 Auto/Mixed 任务并汇总弱验证指标（不写 resolved_model）。"""
    from ai_verify.monitor.cursor_usage import aggregate_task

    if task_ids:
        ids = list(task_ids)
    else:
        tasks = db.list_cursor_tasks(limit=max(limit * 3, 50))
        ids = []
        for t in tasks:
            if auto_only and t.get("route_kind") not in ("auto", "mixed"):
                continue
            ids.append(t["task_id"])
            if len(ids) >= limit:
                break

    reports = []
    for tid in ids:
        report = aggregate_task(db, tid, auto_infer=auto_infer)
        if report is not None:
            reports.append(report)

    out = evaluate_auto_reports(reports)
    if not ids:
        out.notes.append("no matching tasks in DB")
    return out


ABLATION_PRESETS: List[Tuple[str, Tuple[str, ...]]] = [
    ("text", ("text",)),
    ("code", ("code",)),
    ("text+code", ("text", "code")),
    ("text+code+behavior", ("text", "code", "behavior")),
    ("+latency", ("text", "code", "behavior", "latency")),
]


def apply_channels_to_samples(
    samples: Sequence[CorpusSample], channels: Sequence[str]
) -> List[CorpusSample]:
    """返回特征按通道过滤后的样本副本。"""
    from ai_verify.blindtest.features import filter_features_by_channels

    out: List[CorpusSample] = []
    for s in samples:
        out.append(
            CorpusSample(
                conversation_id=s.conversation_id,
                turn_index=s.turn_index,
                request_id=s.request_id,
                label=s.label,
                label_source=s.label_source,
                ttft_ms=s.ttft_ms,
                features=filter_features_by_channels(s.features, channels),
                duration_ms=s.duration_ms,
            )
        )
    return out


def apply_channels_to_corpus(corpus: Corpus, channels: Sequence[str]) -> Corpus:
    return Corpus(
        samples=apply_channels_to_samples(corpus.samples, channels),
        built_at=corpus.built_at,
        stats=dict(corpus.stats),
    )
