"""
数据目录定位：~/.verkee/verify，含旧版 ~/.verkeep/verify、~/.ai-verify 自动迁移
"""

import shutil
import sys
from pathlib import Path

# 迁移链：按从新到旧顺序检测，命中第一个存在的旧目录即迁移
LEGACY_HOMES = [
    Path.home() / ".verkeep" / "verify",
    Path.home() / ".ai-verify",
]
HOME_DIR = Path.home() / ".verkee" / "verify"

_migrated = False


def _tilde(path: Path) -> str:
    """Format path with ~ for user-facing messages."""
    return str(path).replace(str(Path.home()), "~", 1)


def verify_home() -> Path:
    """Return data home; auto-migrate legacy dirs on first use (idempotent)."""
    global _migrated
    if not _migrated:
        _migrated = True
        if not HOME_DIR.exists():
            for legacy in LEGACY_HOMES:
                if legacy.is_dir():
                    try:
                        HOME_DIR.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(legacy), str(HOME_DIR))
                        print(
                            f"检测到旧版数据目录 {_tilde(legacy)}，"
                            f"已自动迁移至 {_tilde(HOME_DIR)}，"
                            "配置、数据库与日志均已接续。",
                            file=sys.stderr,
                        )
                    except OSError as exc:
                        print(
                            f"数据目录迁移失败（{exc}），"
                            f"本次运行继续使用旧目录 {_tilde(legacy)}。",
                            file=sys.stderr,
                        )
                        return legacy
                    break
    return HOME_DIR
