"""
盲测模型指纹识别（离线 transcript 分类）。

当 Cursor Auto 元数据全是 `default` 时，通过 assistant 回复的文风 / 工具调用行为 /
时延特征推断底层模型。与 monitor/fingerprint.py（在线探针）不同，本包对本地
agent transcripts 做离线分类。
"""

from verkeep_verify.blindtest.classifier import (
    BlindModelClassifier,
    InferenceResult,
    TrainReport,
)
from verkeep_verify.blindtest.features import TurnRecord, extract_features

__all__ = [
    "BlindModelClassifier",
    "InferenceResult",
    "TrainReport",
    "TurnRecord",
    "extract_features",
]
