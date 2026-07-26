"""
配置管理模块
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from verkee_verify.paths import verify_home


class ConfigManager:
    """配置管理器"""

    DEFAULT_CONFIG = {
        "base_url": None,
        "api_key": None,
        "model": "gpt-4",
        "monitor": {
            "interval": "6h",
            "fingerprint": True,
            "quality": True,
            "security": True,
            "num_probes": 10,
            "num_questions": 10,
        },
        "alerts": {
            "console": True,
            "webhook": None,
            "webhook_platform": "auto",
        },
    }

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or verify_home()
        self.config_file = self.config_dir / "config.yaml"

    def init_config(self) -> None:
        """初始化配置目录和文件"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        if not self.config_file.exists():
            self._write_config(self.DEFAULT_CONFIG)

        # 创建其他必要目录
        (self.config_dir / "data").mkdir(exist_ok=True)
        (self.config_dir / "logs").mkdir(exist_ok=True)
        (self.config_dir / "cache").mkdir(exist_ok=True)

    def load(self) -> Dict[str, Any]:
        """加载配置"""
        if not self.config_file.exists():
            return self.DEFAULT_CONFIG.copy()

        with open(self.config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        # 合并默认配置
        result = self.DEFAULT_CONFIG.copy()
        result.update(config)
        return result

    def set(self, key: str, value: Any) -> None:
        """设置配置项"""
        config = self.load()

        # 支持嵌套键 (如 monitor.interval)
        keys = key.split(".")
        target = config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

        self._write_config(config)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        config = self.load()

        keys = key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def _write_config(self, config: Dict) -> None:
        """写入配置文件"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
