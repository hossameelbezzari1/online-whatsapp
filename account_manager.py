from __future__ import annotations

import pickle
import re
import time
from pathlib import Path
from typing import Iterable

from selenium.common.exceptions import WebDriverException

from config import ACCOUNTS_DIR, WHATSAPP_URL
from session_manager import delete_session_snapshot


_ALLOWED_COOKIE_KEYS = {
    "name",
    "value",
    "path",
    "domain",
    "secure",
    "httpOnly",
    "expiry",
    "sameSite",
}


def safe_account_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "whatsapp_account"


def list_accounts() -> list[Path]:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(ACCOUNTS_DIR.glob("*.pkl"), key=lambda p: p.name.lower())


def account_label(path: Path) -> str:
    return path.stem


def save_cookies(driver, account_name: str, overwrite: bool = True) -> Path:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

    clean_name = safe_account_name(account_name)
    path = ACCOUNTS_DIR / f"{clean_name}.pkl"

    if path.exists() and not overwrite:
        raise FileExistsError(f"Account already exists: {path.name}")

    cookies = driver.get_cookies()

    payload = {
        "version": 1,
        "account_name": clean_name,
        "saved_at": time.time(),
        "url": WHATSAPP_URL,
        "cookies": cookies,
    }

    with path.open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

    return path


def _normalize_cookie(cookie: dict) -> dict:
    clean = {k: v for k, v in cookie.items() if k in _ALLOWED_COOKIE_KEYS}

    if "expiry" in clean:
        try:
            clean["expiry"] = int(clean["expiry"])
        except (TypeError, ValueError):
            clean.pop("expiry", None)

    same_site = clean.get("sameSite")
    if same_site not in {None, "Strict", "Lax", "None"}:
        clean.pop("sameSite", None)

    return clean


def read_cookie_file(path: Path) -> tuple[str, list[dict]]:
    # SECURITY: never unpickle files from an untrusted source.
    with path.open("rb") as fh:
        payload = pickle.load(fh)

    if isinstance(payload, list):
        # Compatibility with a simple pickle.dump(driver.get_cookies()) format.
        return path.stem, payload

    if not isinstance(payload, dict):
        raise ValueError("Invalid .pkl format")

    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("No cookies list found in .pkl file")

    account_name = str(payload.get("account_name") or path.stem)
    return account_name, cookies


def load_cookies(driver, path: Path) -> tuple[str, int, int]:
    account_name, cookies = read_cookie_file(path)

    # Selenium only allows adding cookies for the current domain.
    if "web.whatsapp.com" not in driver.current_url:
        driver.get(WHATSAPP_URL)

    loaded = 0
    failed = 0

    for raw_cookie in cookies:
        try:
            cookie = _normalize_cookie(raw_cookie)
            driver.add_cookie(cookie)
            loaded += 1
        except (WebDriverException, Exception):
            failed += 1

    driver.refresh()
    return account_name, loaded, failed


def delete_account(path: Path) -> None:
    account_name = path.stem
    path.unlink(missing_ok=True)
    delete_session_snapshot(account_name)
