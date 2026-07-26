"""
数据目录定位：~/.verkeep/verify，含旧版 ~/.ai-verify 自动迁移
"""

import shutil
import sys
from pathlib import Path

LEGACY_HOME = Path.home() / ".ai-verify"
HOME_DIR = Path.home() / ".verkeep" / "verify"

_migrated = False


def verify_home() -> Path:
    """Return data home; auto-migrate legacy ~/.ai-verify on first use."""
    global _migrated
    if not _migrated:
        _migrated = True
        if not HOME_DIR.exists() and LEGACY_HOME.is_dir():
            try:
                HOME_DIR.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(LEGACY_HOME), str(HOME_DIR))
                print(
                    "检测到旧版数据目录 ~/.ai-verify，已自动迁移至 ~/.verkeep/verify，"
                    "配置、数据库与日志均已接续。",
                    file=sys.stderr,
                )
            except OSError as exc:
                print(
                    f"数据目录迁移失败（{exc}），本次运行继续使用旧目录 ~/.ai-verify。",
                    file=sys.stderr,
                )
                return LEGACY_HOME
    return HOME_DIR
