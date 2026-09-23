from __future__ import annotations

import platform
from pathlib import Path

import requests

from config import (
    SEND_SCREENSHOT_TO_TELEGRAM,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WINDOWS_NOTIFICATIONS,
)


def telegram_is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_text(text: str) -> tuple[bool, str]:
    if not telegram_is_configured():
        return False, "Telegram is not configured"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()
        return True, "Telegram message sent"
    except Exception as exc:
        return False, str(exc)


def send_telegram_photo(photo_path: Path, caption: str) -> tuple[bool, str]:
    if not telegram_is_configured():
        return False, "Telegram is not configured"

    if not photo_path.exists():
        return False, f"Screenshot not found: {photo_path}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    try:
        with photo_path.open("rb") as fh:
            response = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],
                },
                files={"photo": fh},
                timeout=30,
            )
        response.raise_for_status()
        return True, "Telegram photo sent"
    except Exception as exc:
        return False, str(exc)


def send_windows_notification(title: str, message: str) -> tuple[bool, str]:
    if not WINDOWS_NOTIFICATIONS:
        return False, "Windows notifications are disabled"

    if platform.system().lower() != "windows":
        return False, "Not running on Windows"

    try:
        from winotify import Notification

        toast = Notification(
            app_id="WhatsApp Watcher",
            title=title,
            msg=message,
            duration="short",
        )
        toast.show()
        return True, "Windows notification sent"
    except Exception as exc:
        return False, str(exc)


def notify_event(
    *,
    account: str,
    contact: str,
    event: str,
    status: str,
    message_preview: str,
    timestamp: str,
    screenshot_path: Path | None,
) -> dict:
    pretty_event = {
        "sent": "Sent",
        "delivered": "Delivered",
        "read": "Read",
        "pending": "Pending",
        "presence_changed": "Presence Changed",
        "online": "Online",
        "offline": "Offline",
        "unavailable": "Unavailable",
    }.get(event, event)

    preview = message_preview.strip() or "(media / no text)"
    if len(preview) > 240:
        preview = preview[:237] + "..."

    text = (
        f"WhatsApp event\n"
        f"Account: {account}\n"
        f"Contact: {contact}\n"
        f"Event: {pretty_event}\n"
        f"Status: {status}\n"
        f"Time: {timestamp}\n"
        f"Message: {preview}"
    )

    results = {}

    if (
        SEND_SCREENSHOT_TO_TELEGRAM
        and screenshot_path is not None
        and screenshot_path.exists()
    ):
        ok, info = send_telegram_photo(screenshot_path, text)
    else:
        ok, info = send_telegram_text(text)

    results["telegram"] = {"ok": ok, "info": info}

    ok, info = send_windows_notification(
        title=f"WhatsApp - {contact}",
        message=f"{pretty_event}: {preview}",
    )
    results["windows"] = {"ok": ok, "info": info}

    return results


def test_notifications() -> dict:
    message = "WhatsApp Watcher test notification"
    tg_ok, tg_info = send_telegram_text(message)
    win_ok, win_info = send_windows_notification(
        "WhatsApp Watcher",
        "Test notification",
    )

    return {
        "telegram": {"ok": tg_ok, "info": tg_info},
        "windows": {"ok": win_ok, "info": win_info},
    }
