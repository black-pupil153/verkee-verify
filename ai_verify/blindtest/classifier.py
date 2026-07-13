"""
盲测分类器 — 轻量可解释、带校准概率。

设计：
- 训练：优先 scikit-learn LogisticRegression（multinomial, balanced）；
  sklearn 不可用时退化为纯 Python 高斯朴素贝叶斯
- 推理：纯 Python（模型存为权重 JSON，与 sklearn 解耦）
- 校准：leave-one-conversation-out 留出预测上拟合温度缩放（Platt 式），
  避免 CalibratedClassifierCV 在小语料上折内类别塌缩
- 概率低于阈值（默认 0.7）时输出 inferred_model=None
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ai_verify.blindtest.features import TurnRecord, extract_features

MODEL_FORMAT_VERSION = 1
DEFAULT_THRESHOLD = 0.7


@dataclass
class InferenceResult:
    inferred_model: Optional[str]  # 低于阈值时为 None
    probability: float
    top_candidates: List[Tuple[str, float]]
    features_used: int


@dataclass
class TrainReport:
    backend: str
    n_samples: int
    n_conversations: int
    class_counts: Dict[str, int]
    cv_accuracy: Optional[float]
    cv_evaluated: int
    cv_skipped: int
    per_class_accuracy: Dict[str, float]
    temperature: float
    feature_count: int
    trained_at: str
    notes: List[str] = field(default_factory=list)
    split_name: Optional[str] = None
    n_train: Optional[int] = None
    n_val: Optional[int] = None
    val_accuracy: Optional[float] = None


def _softmax(logits: Sequence[float]) -> List[float]:
    mx = max(logits)
    exps = [math.exp(z - mx) for z in logits]
    total = sum(exps)
    return [e / total for e in exps]


def _sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
        import numpy  # noqa: F401

        return True
    except ImportError:
        return False


def _extract_samples(corpus: Any) -> List[Any]:
    """接受 Corpus 对象或样本列表；只保留有标签样本。"""
    samples = getattr(corpus, "samples", corpus)
    return [s for s in samples if getattr(s, "label", None)]


class BlindModelClassifier:
    """features dict → 校准概率 → InferenceResult。"""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self.classes: List[str] = []
        self.feature_names: List[str] = []
        self.means: List[float] = []
        self.stds: List[float] = []
        self.temperature: float = 1.0
        self.backend: str = "none"
        # logistic 权重（backend=sklearn_lr）
        self.coef: List[List[float]] = []
        self.intercept: List[float] = []
        # 高斯 NB 参数（backend=gaussian_nb）
        self.nb_means: List[List[float]] = []
        self.nb_vars: List[List[float]] = []
        self.nb_log_priors: List[float] = []

    # ------------------------------------------------------------- vectorize

    def _fit_vocab(self, feature_dicts: List[Dict[str, float]]) -> None:
        names = sorted({k for fd in feature_dicts for k in fd})
        self.feature_names = names
        n = len(feature_dicts)
        means = []
        stds = []
        for name in names:
            vals = [fd.get(name, 0.0) for fd in feature_dicts]
            mean = sum(vals) / n
            var = sum((v - mean) ** 2 for v in vals) / n
            std = math.sqrt(var)
            means.append(mean)
            # 常量特征：std 置 1 使 z 恒为 0，而不是除以极小数
            stds.append(std if std > 1e-9 else 1.0)
        self.means = means
        self.stds = stds

    def _vectorize(self, features: Dict[str, float]) -> List[float]:
        # clamp z-score，避免近似常量特征的极端值导致数值不稳定
        return [
            max(-8.0, min(8.0, (features.get(name, 0.0) - self.means[i]) / self.stds[i]))
            for i, name in enumerate(self.feature_names)
        ]

    # ------------------------------------------------------------- backends

    def _fit_model(
        self, X: List[List[float]], y: List[str], classes: List[str]
    ) -> Dict[str, Any]:
        """返回可直接用于纯 Python 推理的权重。"""
        if _sklearn_available():
            return self._fit_sklearn_lr(X, y, classes)
        return self._fit_gaussian_nb(X, y, classes)

    @staticmethod
    def _fit_sklearn_lr(
        X: List[List[float]], y: List[str], classes: List[str]
    ) -> Dict[str, Any]:
        import numpy as np
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(
            C=0.5, class_weight="balanced", max_iter=2000
        )
        # macOS Accelerate BLAS 在 matmul 上会误报 divide-by-zero/overflow
        # RuntimeWarning（输入已验证无非有限值），这里局部屏蔽
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            clf.fit(np.asarray(X, dtype=float), y)
        return {
            "backend": "sklearn_lr",
            "coef": clf.coef_.tolist(),
            "intercept": clf.intercept_.tolist(),
            "classes": [str(c) for c in clf.classes_],
        }

    @staticmethod
    def _fit_gaussian_nb(
        X: List[List[float]], y: List[str], classes: List[str]
    ) -> Dict[str, Any]:
        n_features = len(X[0]) if X else 0
        by_class: Dict[str, List[List[float]]] = {c: [] for c in classes}
        for row, label in zip(X, y):
            by_class[label].append(row)
        # 全局方差用于平滑
        all_vars = []
        for j in range(n_features):
            vals = [row[j] for row in X]
            mean = sum(vals) / len(vals)
            all_vars.append(sum((v - mean) ** 2 for v in vals) / len(vals))
        smoothing = 1e-2 * (max(all_vars) if all_vars else 1.0) + 1e-6

        nb_means, nb_vars, nb_log_priors = [], [], []
        for c in classes:
            rows = by_class[c]
            n = max(len(rows), 1)
            cmeans, cvars = [], []
            for j in range(n_features):
                vals = [row[j] for row in rows] or [0.0]
                mean = sum(vals) / len(vals)
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                cmeans.append(mean)
                cvars.append(var + smoothing)
            nb_means.append(cmeans)
            nb_vars.append(cvars)
            nb_log_priors.append(math.log(n / max(len(X), 1)))
        return {
            "backend": "gaussian_nb",
            "nb_means": nb_means,
            "nb_vars": nb_vars,
            "nb_log_priors": nb_log_priors,
            "classes": classes,
        }

    def _apply_weights(self, weights: Dict[str, Any]) -> None:
        self.backend = weights["backend"]
        self.classes = list(weights["classes"])
        if self.backend == "sklearn_lr":
            self.coef = weights["coef"]
            self.intercept = weights["intercept"]
        else:
            self.nb_means = weights["nb_means"]
            self.nb_vars = weights["nb_vars"]
            self.nb_log_priors = weights["nb_log_priors"]

    def _logits(self, vec: List[float]) -> List[float]:
        if self.backend == "sklearn_lr":
            if len(self.classes) == 2 and len(self.coef) == 1:
                z = sum(w * x for w, x in zip(self.coef[0], vec)) + self.intercept[0]
                return [-z / 2.0, z / 2.0]
            return [
                sum(w * x for w, x in zip(row, vec)) + b
                for row, b in zip(self.coef, self.intercept)
            ]
        if self.backend == "gaussian_nb":
            logits = []
            for ci in range(len(self.classes)):
                ll = self.nb_log_priors[ci]
                for j, x in enumerate(vec):
                    var = self.nb_vars[ci][j]
                    diff = x - self.nb_means[ci][j]
                    ll += -0.5 * (math.log(2 * math.pi * var) + diff * diff / var)
                logits.append(ll)
            return logits
        raise RuntimeError("classifier not trained; call train() or load()")

    def _predict_proba(self, vec: List[float]) -> List[float]:
        logits = self._logits(vec)
        return _softmax([z / self.temperature for z in logits])

    # ------------------------------------------------------------- training

    def train(
        self,
        corpus: Any,
        *,
        split: Any = None,
        split_name: Optional[str] = None,
    ) -> TrainReport:
        """训练 + 温度校准。

        - 无 split：leave-one-conversation-out CV + 在留出 logits 上拟合 T（兼容旧路径）
        - 有 split：只用 train 拟合权重，T **只在 val** 上拟合；test 不得带标签
        """
        if split is not None:
            return self._train_with_split(corpus, split, split_name=split_name)
        return self._train_loco(corpus)

    def _train_loco(self, corpus: Any) -> TrainReport:
        """训练 + leave-one-conversation-out 交叉验证 + 温度校准。"""
        samples = _extract_samples(corpus)
        if len(samples) < 4:
            raise ValueError(
                f"labeled samples too few ({len(samples)}); need at least 4"
            )
        classes = sorted({s.label for s in samples})
        if len(classes) < 2:
            raise ValueError(
                f"need at least 2 classes, got {classes}; "
                "collect data from more manually-selected model tasks"
            )

        feature_dicts = [s.features for s in samples]
        self._fit_vocab(feature_dicts)
        X = [self._vectorize(fd) for fd in feature_dicts]
        y = [s.label for s in samples]
        conv_ids = [s.conversation_id for s in samples]
        notes: List[str] = []

        # leave-one-conversation-out
        held_logits: List[List[float]] = []
        held_labels: List[str] = []
        held_classes: List[List[str]] = []
        cv_skipped = 0
        conversations = sorted(set(conv_ids))
        if len(conversations) >= 2:
            for held_conv in conversations:
                train_idx = [i for i, c in enumerate(conv_ids) if c != held_conv]
                test_idx = [i for i, c in enumerate(conv_ids) if c == held_conv]
                fold_classes = sorted({y[i] for i in train_idx})
                if len(fold_classes) < 2:
                    cv_skipped += len(test_idx)
                    continue
                weights = self._fit_model(
                    [X[i] for i in train_idx], [y[i] for i in train_idx], fold_classes
                )
                fold = BlindModelClassifier(threshold=self.threshold)
                fold.feature_names = self.feature_names
                fold.means, fold.stds = self.means, self.stds
                fold._apply_weights(weights)
                for i in test_idx:
                    held_logits.append(fold._logits(X[i]))
                    held_labels.append(y[i])
                    held_classes.append(fold.classes)
        else:
            notes.append("only 1 labeled conversation; CV not possible")

        cv_correct = 0
        cv_evaluated = len(held_labels)
        per_class_hit: Dict[str, List[int]] = {c: [0, 0] for c in classes}
        for logits, label, fold_cls in zip(held_logits, held_labels, held_classes):
            probs = _softmax(logits)
            pred = fold_cls[probs.index(max(probs))]
            hit = 1 if (label in fold_cls and pred == label) else 0
            cv_correct += hit
            per_class_hit[label][0] += hit
            per_class_hit[label][1] += 1

        cv_accuracy = cv_correct / cv_evaluated if cv_evaluated else None
        per_class_accuracy = {
            c: (hit / tot) for c, (hit, tot) in per_class_hit.items() if tot > 0
        }

        # 温度校准：在留出 logits 上最大化对数似然
        self.temperature = self._fit_temperature(held_logits, held_labels, held_classes)

        # 全量训练最终模型
        weights = self._fit_model(X, y, classes)
        self._apply_weights(weights)

        class_counts: Dict[str, int] = {}
        for label in y:
            class_counts[label] = class_counts.get(label, 0) + 1
        if cv_evaluated and cv_evaluated < len(samples):
            notes.append(
                f"{cv_skipped} samples skipped in CV (single-conversation classes)"
            )

        return TrainReport(
            backend=self.backend,
            n_samples=len(samples),
            n_conversations=len(conversations),
            class_counts=class_counts,
            cv_accuracy=cv_accuracy,
            cv_evaluated=cv_evaluated,
            cv_skipped=cv_skipped,
            per_class_accuracy=per_class_accuracy,
            temperature=self.temperature,
            feature_count=len(self.feature_names),
            trained_at=datetime.now().isoformat(),
            notes=notes,
        )

    def _train_with_split(
        self, corpus: Any, split: Any, *, split_name: Optional[str] = None
    ) -> TrainReport:
        """尊重 split：train 拟合、val 校准 T、test 标签不可见。"""
        from ai_verify.blindtest.splits import (
            assert_no_test_labels,
            filter_samples,
            strip_test_labels,
        )

        # 内存密封：即使语料仍带 test 标签，训练路径也先剥掉
        if hasattr(corpus, "samples"):
            open_corpus = strip_test_labels(corpus, split)
            all_samples = open_corpus.samples
        else:
            all_samples = list(corpus)
            assert_no_test_labels(all_samples, split)

        assert_no_test_labels(all_samples, split)

        train_samples = filter_samples(all_samples, split, "train", labeled_only=True)
        val_samples = filter_samples(all_samples, split, "val", labeled_only=True)

        if len(train_samples) < 4:
            raise ValueError(
                f"train labeled samples too few ({len(train_samples)}); need at least 4"
            )
        classes = sorted({s.label for s in train_samples if s.label})
        if len(classes) < 2:
            raise ValueError(
                f"need at least 2 classes in train, got {classes}; "
                "collect data from more manually-selected model tasks"
            )

        notes: List[str] = [
            f"split={split_name or getattr(split, 'name', 'custom')}: "
            f"train={len(train_samples)} val={len(val_samples)}; "
            f"T fit on val only; test sealed"
        ]

        feature_dicts = [s.features for s in train_samples]
        self._fit_vocab(feature_dicts)
        X_train = [self._vectorize(s.features) for s in train_samples]
        y_train = [s.label for s in train_samples]

        weights = self._fit_model(X_train, y_train, classes)
        self._apply_weights(weights)

        # 温度只在 val 上拟合
        val_accuracy: Optional[float] = None
        per_class_accuracy: Dict[str, float] = {}
        if val_samples:
            val_logits: List[List[float]] = []
            val_labels: List[str] = []
            val_classes: List[List[str]] = []
            for s in val_samples:
                vec = self._vectorize(s.features)
                val_logits.append(self._logits(vec))
                val_labels.append(s.label)
                val_classes.append(self.classes)
            self.temperature = self._fit_temperature(val_logits, val_labels, val_classes)

            correct = 0
            per_hit: Dict[str, List[int]] = {c: [0, 0] for c in classes}
            for logits, label in zip(val_logits, val_labels):
                probs = _softmax([z / self.temperature for z in logits])
                pred = self.classes[probs.index(max(probs))]
                hit = 1 if pred == label else 0
                correct += hit
                if label in per_hit:
                    per_hit[label][0] += hit
                    per_hit[label][1] += 1
            val_accuracy = correct / len(val_labels)
            per_class_accuracy = {
                c: (h / t) for c, (h, t) in per_hit.items() if t > 0
            }
        else:
            notes.append("no val samples; temperature left at 1.0")
            self.temperature = 1.0

        class_counts: Dict[str, int] = {}
        for label in y_train:
            class_counts[label] = class_counts.get(label, 0) + 1

        n_convs = len({s.conversation_id for s in train_samples})
        return TrainReport(
            backend=self.backend,
            n_samples=len(train_samples),
            n_conversations=n_convs,
            class_counts=class_counts,
            cv_accuracy=None,  # split 路径不以 LOCO-CV 充当盲评
            cv_evaluated=0,
            cv_skipped=0,
            per_class_accuracy=per_class_accuracy,
            temperature=self.temperature,
            feature_count=len(self.feature_names),
            trained_at=datetime.now().isoformat(),
            notes=notes,
            split_name=split_name or getattr(split, "name", None),
            n_train=len(train_samples),
            n_val=len(val_samples),
            val_accuracy=val_accuracy,
        )

    @staticmethod
    def _fit_temperature(
        held_logits: List[List[float]],
        held_labels: List[str],
        held_classes: List[List[str]],
    ) -> float:
        """网格搜索温度 T，最大化留出集对数似然。无留出数据时返回保守值 2.0。"""
        usable = [
            (logits, cls.index(label))
            for logits, label, cls in zip(held_logits, held_labels, held_classes)
            if label in cls
        ]
        if not usable:
            return 2.0
        # 下限 1.0：小语料留出集常被完美分开，允许 T<1 会导致过度自信
        best_t, best_ll = 1.0, -math.inf
        t = 1.0
        while t <= 8.0:
            ll = 0.0
            for logits, target in usable:
                probs = _softmax([z / t for z in logits])
                ll += math.log(max(probs[target], 1e-12))
            if ll > best_ll:
                best_ll, best_t = ll, t
            t *= 1.25
        return best_t

    # ------------------------------------------------------------- inference

    def predict_turn(
        self, turn_features: Union[Dict[str, float], TurnRecord]
    ) -> InferenceResult:
        if isinstance(turn_features, TurnRecord):
            turn_features = extract_features(turn_features)
        if not self.classes:
            raise RuntimeError("classifier not trained; call train() or load()")

        features_used = sum(
            1 for name in self.feature_names if turn_features.get(name)
        )
        vec = self._vectorize(turn_features)
        probs = self._predict_proba(vec)
        ranked = sorted(zip(self.classes, probs), key=lambda x: -x[1])
        top_model, top_prob = ranked[0]
        return InferenceResult(
            inferred_model=top_model if top_prob >= self.threshold else None,
            probability=top_prob,
            top_candidates=[(m, round(p, 4)) for m, p in ranked[:3]],
            features_used=features_used,
        )

    # ------------------------------------------------------------- persist

    def save(self, path: Union[str, Path]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": MODEL_FORMAT_VERSION,
            "backend": self.backend,
            "threshold": self.threshold,
            "classes": self.classes,
            "feature_names": self.feature_names,
            "means": self.means,
            "stds": self.stds,
            "temperature": self.temperature,
            "coef": self.coef,
            "intercept": self.intercept,
            "nb_means": self.nb_means,
            "nb_vars": self.nb_vars,
            "nb_log_priors": self.nb_log_priors,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "BlindModelClassifier":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        obj = cls(threshold=payload.get("threshold", DEFAULT_THRESHOLD))
        obj.backend = payload["backend"]
        obj.classes = payload["classes"]
        obj.feature_names = payload["feature_names"]
        obj.means = payload["means"]
        obj.stds = payload["stds"]
        obj.temperature = payload.get("temperature", 1.0)
        obj.coef = payload.get("coef", [])
        obj.intercept = payload.get("intercept", [])
        obj.nb_means = payload.get("nb_means", [])
        obj.nb_vars = payload.get("nb_vars", [])
        obj.nb_log_priors = payload.get("nb_log_priors", [])
        return obj


def report_as_dict(report: TrainReport) -> Dict[str, Any]:
    return asdict(report)
