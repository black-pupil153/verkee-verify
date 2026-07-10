"""
从 CC Switch 读取当前 Claude Code 供应商配置。

CC Switch 数据位置：
  ~/.cc-switch/cc-switch.db          # 供应商 SSOT
  ~/.cc-switch/settings.json        # 当前选中的 provider id
  ~/.claude/settings.json           # CC Switch 回填后的生效配置（兜底）

优先读数据库里的当前供应商；读不到再回退到 ~/.claude/settings.json。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


CC_SWITCH_DIR = Path.home() / ".cc-switch"
CC_SWITCH_DB = CC_SWITCH_DIR / "cc-switch.db"
CC_SWITCH_SETTINGS = CC_SWITCH_DIR / "settings.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


@dataclass
class ProviderConfig:
    """一个可用的上游渠道"""

    name: str
    base_url: str
    api_key: str
    model: Optional[str] = None
    source: str = "unknown"  # cc-switch | claude-settings | ai-verify
    provider_id: Optional[str] = None
    extra_env: Optional[Dict[str, str]] = None

    def masked(self) -> Dict[str, Any]:
        key = self.api_key
        if key and len(key) > 10:
            key = key[:6] + "..." + key[-4:]
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_key": key,
            "model": self.model,
            "source": self.source,
            "provider_id": self.provider_id,
        }


def _extract_from_env(env: Dict[str, Any], name: str, source: str, provider_id: Optional[str] = None) -> Optional[ProviderConfig]:
    if not isinstance(env, dict):
        return None
    base_url = (
        env.get("ANTHROPIC_BASE_URL")
        or env.get("OPENAI_BASE_URL")
        or env.get("OPENAI_API_BASE")
    )
    api_key = (
        env.get("ANTHROPIC_AUTH_TOKEN")
        or env.get("ANTHROPIC_API_KEY")
        or env.get("OPENAI_API_KEY")
    )
    if not base_url or not api_key:
        return None

    model = (
        env.get("ANTHROPIC_MODEL")
        or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or env.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
    )

    # 保留其它 env，方便 run 时一并注入（模型别名等）
    extra = {
        k: str(v)
        for k, v in env.items()
        if k not in {
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "OPENAI_API_KEY",
        }
        and v is not None
    }

    return ProviderConfig(
        name=name,
        base_url=str(base_url).rstrip("/"),
        api_key=str(api_key),
        model=str(model) if model else None,
        source=source,
        provider_id=provider_id,
        extra_env=extra or None,
    )


def list_cc_switch_providers(app_type: str = "claude") -> List[ProviderConfig]:
    """列出 CC Switch 里某应用的全部供应商"""
    if not CC_SWITCH_DB.exists():
        return []

    results: List[ProviderConfig] = []
    try:
        con = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, name, is_current, settings_config
            FROM providers
            WHERE app_type = ?
            ORDER BY is_current DESC, sort_index ASC
            """,
            (app_type,),
        ).fetchall()
        for r in rows:
            try:
                cfg = json.loads(r["settings_config"] or "{}")
            except Exception:
                continue
            env = cfg.get("env") if isinstance(cfg, dict) else None
            p = _extract_from_env(
                env or {},
                name=r["name"],
                source="cc-switch",
                provider_id=r["id"],
            )
            if p:
                results.append(p)
        con.close()
    except Exception:
        return []
    return results


def get_current_cc_switch_provider(app_type: str = "claude") -> Optional[ProviderConfig]:
    """读取 CC Switch 当前选中的供应商"""
    if not CC_SWITCH_DB.exists():
        return None

    current_id = None
    if CC_SWITCH_SETTINGS.exists():
        try:
            data = json.loads(CC_SWITCH_SETTINGS.read_text(encoding="utf-8"))
            key = {
                "claude": "currentProviderClaude",
                "codex": "currentProviderCodex",
                "gemini": "currentProviderGemini",
            }.get(app_type)
            if key:
                current_id = data.get(key)
        except Exception:
            pass

    try:
        con = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row

        row = None
        if current_id:
            row = con.execute(
                """
                SELECT id, name, settings_config FROM providers
                WHERE app_type = ? AND id = ?
                """,
                (app_type, current_id),
            ).fetchone()
        if row is None:
            row = con.execute(
                """
                SELECT id, name, settings_config FROM providers
                WHERE app_type = ? AND is_current = 1
                LIMIT 1
                """,
                (app_type,),
            ).fetchone()
        con.close()
        if not row:
            return None

        cfg = json.loads(row["settings_config"] or "{}")
        env = cfg.get("env") if isinstance(cfg, dict) else {}
        return _extract_from_env(
            env or {},
            name=row["name"],
            source="cc-switch",
            provider_id=row["id"],
        )
    except Exception:
        return None


def get_claude_settings_provider() -> Optional[ProviderConfig]:
    """兜底：读 ~/.claude/settings.json（CC Switch 回填后的生效配置）"""
    if not CLAUDE_SETTINGS.exists():
        return None
    try:
        data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
        env = data.get("env") if isinstance(data, dict) else {}
        return _extract_from_env(env or {}, name="claude-settings", source="claude-settings")
    except Exception:
        return None


def resolve_provider(
    prefer: str = "auto",
    app_type: str = "claude",
) -> Optional[ProviderConfig]:
    """
    解析要用的上游渠道。

    prefer:
      - auto: cc-switch 当前 → ~/.claude/settings → ai-verify config
      - cc-switch / claude / ai-verify: 强制某一来源
    """
    prefer = (prefer or "auto").lower()

    if prefer in ("auto", "cc-switch", "ccswitch"):
        p = get_current_cc_switch_provider(app_type=app_type)
        if p:
            return p
        if prefer != "auto":
            return None

    if prefer in ("auto", "claude", "claude-settings"):
        p = get_claude_settings_provider()
        if p:
            return p
        if prefer != "auto":
            return None

    if prefer in ("auto", "ai-verify", "aiverify", "config"):
        try:
            from ai_verify.config import ConfigManager

            cfg = ConfigManager().load()
            if cfg.get("base_url") and cfg.get("api_key"):
                return ProviderConfig(
                    name="ai-verify",
                    base_url=str(cfg["base_url"]).rstrip("/"),
                    api_key=str(cfg["api_key"]),
                    model=cfg.get("model"),
                    source="ai-verify",
                )
        except Exception:
            pass

    return None
