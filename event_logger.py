from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from config import EVENTS_FILE, ERRORS_FILE, PRESENCE_HISTORY_FILE

_lock = Lock()


def _read_json_array(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append(path: Path, item: dict[str, Any]) -> None:
    with _lock:
        rows = _read_json_array(path)
        rows.append(item)

        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)


def log_event(
    *,
    account: str,
    contact: str,
    event: str,
    status: str,
    message_id: str | None,
    message_preview: str,
    screenshot: str | None,
) -> dict:
    item = {
        "id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "account": account,
        "contact": contact,
        "event": event,
        "status": status,
        "message_id": message_id,
        "message_preview": message_preview,
        "screenshot": screenshot,
    }
    _append(EVENTS_FILE, item)
    return item


def log_presence_change(
    *,
    account: str,
    contact: str,
    previous_status: str,
    current_status: str,
    event: str,
    screenshot: str | None,
) -> dict:
    item = {
        "id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "account": account,
        "contact": contact,
        "previous_status": previous_status,
        "current_status": current_status,
        "event": event,
        "screenshot": screenshot,
    }
    _append(PRESENCE_HISTORY_FILE, item)
    return item


def read_presence_history(
    *,
    account: str | None = None,
    contact: str | None = None,
) -> list[dict]:
    rows = _read_json_array(PRESENCE_HISTORY_FILE)

    if account is not None:
        rows = [row for row in rows if row.get("account") == account]

    if contact is not None:
        rows = [row for row in rows if row.get("contact") == contact]

    return rows


def presence_history_contacts(account: str | None = None) -> list[str]:
    rows = read_presence_history(account=account)
    contacts = {
        str(row.get("contact", "")).strip()
        for row in rows
        if str(row.get("contact", "")).strip()
    }
    return sorted(contacts, key=str.lower)


def log_error(context: str, error: Exception | str) -> dict:
    item = {
        "id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "context": context,
        "error": str(error),
    }
    _append(ERRORS_FILE, item)
    return item
