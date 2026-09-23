from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import SCREENSHOTS_DIR


def _safe(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value.strip())
    value = re.sub(r"\s+", "_", value)
    return value[:80] or "unknown"


def take_screenshot(driver, account: str, contact: str, event: str, platform: str = "whatsapp") -> Path:
    folder = SCREENSHOTS_DIR / _safe(platform) / _safe(account)
    folder.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    filename = f"{_safe(contact)}_{_safe(event)}_{stamp}.png"
    path = folder / filename

    if not driver.save_screenshot(str(path)):
        raise RuntimeError("Screenshot failed")
    return path
