from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import SCREENSHOTS_DIR


def _safe(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value.strip())
    value = re.sub(r"\s+", "_", value)
    return value[:80] or "unknown"


def take_screenshot(driver, account: str, contact: str, event: str) -> Path:
    folder = SCREENSHOTS_DIR / _safe(account)
    folder.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{_safe(contact)}_{_safe(event)}_{stamp}.png"
    path = folder / filename

    driver.save_screenshot(str(path))
    return path
