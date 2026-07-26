"""
Webhook 报警模块
支持飞书、钉钉、企业微信等平台
"""

import json
from typing import Any, Dict, Optional
from dataclasses import dataclass
from enum import Enum

import httpx


class AlertLevel(Enum):
    """报警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """报警对象"""
    title: str
    message: str
    level: AlertLevel = AlertLevel.WARNING
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            from datetime import datetime
            self.timestamp = datetime.utcnow().isoformat()


class WebhookAlerter:
    """Webhook 报警器"""

    # 平台类型
    PLATFORM_LARK = "lark"           # 飞书
    PLATFORM_DINGTALK = "dingtalk"   # 钉钉
    PLATFORM_WECHAT = "wechat"       # 企业微信
    PLATFORM_SLACK = "slack"         # Slack
    PLATFORM_GENERIC = "generic"     # 通用 Webhook

    def __init__(self, webhook_url: str, platform: str = "auto"):
        self.webhook_url = webhook_url
        self.platform = self._detect_platform(webhook_url) if platform == "auto" else platform

    def _detect_platform(self, url: str) -> str:
        """自动检测平台类型"""
        url_lower = url.lower()

        if ".feishu.cn" in url_lower or "lark" in url_lower:
            return self.PLATFORM_LARK
        elif "dingtalk" in url_lower:
            return self.PLATFORM_DINGTALK
        elif "qyapi.weixin.qq.com" in url_lower:
            return self.PLATFORM_WECHAT
        elif "slack" in url_lower or "hooks.slack.com" in url_lower:
            return self.PLATFORM_SLACK
        else:
            return self.PLATFORM_GENERIC

    def send(self, alert: Alert) -> bool:
        """发送报警"""
        try:
            if self.platform == self.PLATFORM_LARK:
                return self._send_lark(alert)
            elif self.platform == self.PLATFORM_DINGTALK:
                return self._send_dingtalk(alert)
            elif self.platform == self.PLATFORM_WECHAT:
                return self._send_wechat(alert)
            elif self.platform == self.PLATFORM_SLACK:
                return self._send_slack(alert)
            else:
                return self._send_generic(alert)
        except Exception as e:
            print(f"[Webhook 报警失败]: {e}")
            return False

    def _send_lark(self, alert: Alert) -> bool:
        """发送飞书报警"""
        # 飞书消息卡片格式
        color = self._get_color(alert.level)

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": alert.title
                    },
                    "template": color
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "plain_text",
                            "content": alert.message
                        }
                    }
                ]
            }
        }

        # 添加详情
        if alert.details:
            elements = payload["card"]["elements"]
            for key, value in alert.details.items():
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{key}**: {value}"
                    }
                })

        with httpx.Client(timeout=10) as client:
            response = client.post(self.webhook_url, json=payload)
            return response.status_code == 200

    def _send_dingtalk(self, alert: Alert) -> bool:
        """发送钉钉报警"""
        # 钉钉 Markdown 格式
        level_text = {
            AlertLevel.INFO: "ℹ️ 信息",
            AlertLevel.WARNING: "⚠️ 警告",
            AlertLevel.ERROR: "❌ 错误",
            AlertLevel.CRITICAL: "🚨 严重",
        }

        text = f"### {level_text.get(alert.level, '⚠️')}: {alert.title}\n\n{alert.message}"

        if alert.details:
            text += "\n\n---\n\n"
            for key, value in alert.details.items():
                text += f"- **{key}**: {value}\n"

        text += f"\n\n_时间: {alert.timestamp}_"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": alert.title,
                "text": text
            }
        }

        with httpx.Client(timeout=10) as client:
            response = client.post(self.webhook_url, json=payload)
            return response.status_code == 200

    def _send_wechat(self, alert: Alert) -> bool:
        """发送企业微信报警"""
        level_text = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }

        content = f"{level_text.get(alert.level, '⚠️')} **{alert.title}**\n\n{alert.message}"

        if alert.details:
            content += "\n\n"
            for key, value in alert.details.items():
                content += f"> {key}: {value}\n"

        content += f"\n_时间: {alert.timestamp}_"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }

        with httpx.Client(timeout=10) as client:
            response = client.post(self.webhook_url, json=payload)
            return response.status_code == 200

    def _send_slack(self, alert: Alert) -> bool:
        """发送 Slack 报警"""
        color = self._get_color(alert.level)

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": alert.title,
                    "text": alert.message,
                    "fields": [],
                    "footer": f"Verkee Verify | {alert.timestamp}"
                }
            ]
        }

        if alert.details:
            for key, value in alert.details.items():
                payload["attachments"][0]["fields"].append({
                    "title": key,
                    "value": str(value),
                    "short": True
                })

        with httpx.Client(timeout=10) as client:
            response = client.post(self.webhook_url, json=payload)
            return response.status_code == 200

    def _send_generic(self, alert: Alert) -> bool:
        """发送通用 Webhook 报警"""
        payload = {
            "title": alert.title,
            "message": alert.message,
            "level": alert.level.value,
            "details": alert.details,
            "timestamp": alert.timestamp,
        }

        with httpx.Client(timeout=10) as client:
            response = client.post(self.webhook_url, json=payload)
            return response.status_code == 200

    def _get_color(self, level: AlertLevel) -> str:
        """获取报警级别对应的颜色"""
        colors = {
            AlertLevel.INFO: "blue",
            AlertLevel.WARNING: "yellow",
            AlertLevel.ERROR: "red",
            AlertLevel.CRITICAL: "red",
        }
        return colors.get(level, "yellow")


class AlertManager:
    """报警管理器"""

    def __init__(self):
        self.webhooks: list[WebhookAlerter] = []
        self.console_enabled = True

    def add_webhook(self, webhook_url: str, platform: str = "auto"):
        """添加 Webhook"""
        self.webhooks.append(WebhookAlerter(webhook_url, platform))

    def alert(
        self,
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.WARNING,
        details: Optional[Dict[str, Any]] = None,
    ):
        """发送报警到所有渠道"""
        alert = Alert(
            title=title,
            message=message,
            level=level,
            details=details,
        )

        # 控制台输出
        if self.console_enabled:
            self._console_alert(alert)

        # Webhook 发送
        for webhook in self.webhooks:
            webhook.send(alert)

    def _console_alert(self, alert: Alert):
        """控制台输出报警"""
        from rich.console import Console

        console = Console()

        level_colors = {
            AlertLevel.INFO: "blue",
            AlertLevel.WARNING: "yellow",
            AlertLevel.ERROR: "red",
            AlertLevel.CRITICAL: "red",
        }

        level_icons = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }

        color = level_colors.get(alert.level, "yellow")
        icon = level_icons.get(alert.level, "⚠️")

        console.print()
        console.print(f"[{color}]{icon} {alert.title}[/{color}]")
        console.print(f"  {alert.message}")

        if alert.details:
            console.print("  [dim]详情:[/dim]")
            for key, value in alert.details.items():
                console.print(f"    [dim]- {key}: {value}[/dim]")

        console.print()
