"""
通知发送模块
"""

import platform
from typing import Any


def send_system_notification(title: str, message: str) -> bool:
    """发送系统通知"""
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            import subprocess
            subprocess.run([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}"'
            ], check=True)
            return True

        elif system == "Linux":
            # 尝试使用 notify-send
            import subprocess
            subprocess.run(["notify-send", title, message], check=True)
            return True

        elif system == "Windows":
            # Windows 10+ toast notification
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=5)
                return True
            except ImportError:
                return False

    except Exception:
        return False

    return False


def send_webhook(url: str, payload: dict[str, Any]) -> bool:
    """发送 Webhook 通知"""
    import httpx

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload)
            return response.status_code == 200
    except Exception:
        return False
