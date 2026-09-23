# Social Watcher — Complete Files

Complete source files, ready to copy. Keep your existing .env and private runtime directories.

## main.py

````python
"""Local UI; Selenium belongs exclusively to PlatformManager."""
import questionary
from questionary import Choice
import config
from platform_manager import PlatformManager
from telegram_controller import TelegramController, format_result
from notifier import test_notifications


def choose(title, items):
    return questionary.select(title, choices=[Choice(label, value) for label, value in items]).ask()


def show(manager, action, platform='all', **kwargs):
    try:
        print(format_result(manager.call(action, platform, **kwargs)))
    except Exception as exc:
        print(str(exc))


def platform_menu(manager, platform):
    show(manager, 'focus', platform)
    while True:
        action = choose(platform.title(), [
            ('Current Chat / DM', 'status'), ('Current Status (cached presence)', 'status'),
            ('Refresh Status', 'refresh'), ('Message Status', 'status'),
            ('Screenshot', 'screenshot'), ('Start Watch', 'watch'), ('Stop Watch', 'stop'),
            ('Save session cookies', 'save'), ('Back', 'back')])
        if action in {None, 'back'}:
            return
        show(manager, action, platform)


def accounts_menu(manager):
    while True:
        accounts = manager.call('accounts')
        print(format_result(accounts))
        items = [(f'{p}: {name}', (p, name)) for p, row in accounts.items() for name in row['saved']]
        selection = choose('Accounts', items + [('Add account', 'add'), ('Delete saved account', 'delete'), ('Back', 'back')])
        if selection in {None, 'back'}:
            return
        if selection == 'delete':
            target = choose('Delete saved account', items + [('Back', None)])
            if target and questionary.confirm(f'Delete {target[0]} account {target[1]} and its saved sessions?', default=False).ask():
                show(manager, 'delete', target[0], account=target[1])
            continue
        if selection == 'add':
            platform = choose('Platform', [('WhatsApp', 'whatsapp'), ('Instagram', 'instagram'), ('Back', None)])
            if not platform:
                continue
            name = questionary.text('Local account label:').ask()
            if not name or not name.strip():
                continue
        else:
            platform, name = selection
        show(manager, 'select', platform, account=name)
        print('Log in inside Chrome, then choose Save session cookies in the platform menu.')


def main():
    manager = PlatformManager()
    telegram = TelegramController(manager)
    if config.TELEGRAM_CONTROL:
        print(telegram.start())
    try:
        while True:
            action = choose('Social Watcher', [
                ('WhatsApp', 'whatsapp'), ('Instagram', 'instagram'), ('Status All', 'status'),
                ('Refresh All', 'refresh'), ('Screenshots', 'screenshot'), ('Watchers', 'watchers'),
                ('Accounts', 'accounts'), ('Logs', 'logs'), ('Presence History', 'history'),
                ('Settings', 'settings'), ('Telegram Control', 'telegram'), ('Exit', 'exit')])
            if action in {None, 'exit'}:
                break
            if action in {'whatsapp', 'instagram'}:
                platform_menu(manager, action)
            elif action == 'accounts':
                accounts_menu(manager)
            elif action == 'watchers':
                selected = choose('Watchers', [(f'{a.title()} {p.title()}', (a, p))
                    for p in ('whatsapp', 'instagram', 'all') for a in ('watch', 'stop')] + [('Back', None)])
                if selected:
                    show(manager, *selected)
            elif action == 'telegram':
                selected = choose('Telegram Control', [('Start', 'start'), ('Stop', 'stop'),
                    ('Test notifications', 'test'), ('Back', None)])
                if selected == 'test':
                    print(test_notifications())
                elif selected:
                    print(getattr(telegram, selected)())
            else:
                show(manager, action)
    except (KeyboardInterrupt, EOFError):
        print('Closing Social Watcher...')
    finally:
        telegram.stop()
        manager.close()


if __name__ == '__main__':
    main()
````

## config.py

````python
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ACCOUNTS_DIR = BASE_DIR / "accounts"
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SESSIONS_DIR = BASE_DIR / "sessions"

EVENTS_FILE = DATA_DIR / "events.json"
ERRORS_FILE = DATA_DIR / "errors.json"
PRESENCE_HISTORY_FILE = DATA_DIR / "presence_history.json"

WHATSAPP_URL = "https://web.whatsapp.com/"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CHECK_INTERVAL = float(os.getenv("CHECK_INTERVAL", "2"))
PRESENCE_CHECK_INTERVAL = max(
    0.1,
    float(os.getenv("PRESENCE_CHECK_INTERVAL", "0.25")),
)
LOGIN_TIMEOUT = int(os.getenv("LOGIN_TIMEOUT", "180"))

SEND_SCREENSHOT_TO_TELEGRAM = (
    os.getenv("SEND_SCREENSHOT_TO_TELEGRAM", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)

WINDOWS_NOTIFICATIONS = (
    os.getenv("WINDOWS_NOTIFICATIONS", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)

CHROME_HEADLESS = (
    os.getenv("CHROME_HEADLESS", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)


def ensure_directories() -> None:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    if not EVENTS_FILE.exists():
        EVENTS_FILE.write_text("[]", encoding="utf-8")

    if not ERRORS_FILE.exists():
        ERRORS_FILE.write_text("[]", encoding="utf-8")

    if not PRESENCE_HISTORY_FILE.exists():
        PRESENCE_HISTORY_FILE.write_text("[]", encoding="utf-8")

INSTAGRAM_URL = "https://www.instagram.com/direct/inbox/"
PRESENCE_CONFIRMATIONS = max(2, int(os.getenv("PRESENCE_CONFIRMATIONS", "2")))
PRESENCE_CHECK_DELAY = max(0.1, float(os.getenv("PRESENCE_CHECK_DELAY", "0.3")))
CHECK_INTERVAL = max(1.0, CHECK_INTERVAL)
TELEGRAM_CONTROL = os.getenv("TELEGRAM_CONTROL", "true").lower() == "true"
````

## browser.py

````python
from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import CHROME_HEADLESS
from session_manager import create_temp_profile


def create_driver(account_name: str):
    """
    Lightweight Chrome:
      - disposable temp user-data-dir for this run
      - restores a lightweight session snapshot (legacy account or social pair)
      - no permanent browser cache/history profile
    """
    temp_profile = create_temp_profile(account_name)

    options = Options()
    options.page_load_strategy = "eager"

    options.add_argument(f"--user-data-dir={temp_profile}")
    options.add_argument("--profile-directory=Default")

    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disk-cache-size=1")
    options.add_argument("--media-cache-size=1")

    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    if CHROME_HEADLESS:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1600,1000")

    try:
        driver = webdriver.Chrome(options=options)
    except Exception:
        # If Chrome fails to start, remove the disposable profile immediately.
        from session_manager import cleanup_temp_profile
        cleanup_temp_profile(temp_profile)
        raise

    driver.set_page_load_timeout(35)

    # The single Selenium worker snapshots this AFTER driver.quit().
    driver._wa_temp_profile = temp_profile
    return driver
````

## account_manager.py

````python
from __future__ import annotations

import pickle
import re
import time
import json
from pathlib import Path
from typing import Iterable

from selenium.common.exceptions import WebDriverException

from config import ACCOUNTS_DIR, WHATSAPP_URL, INSTAGRAM_URL, SESSIONS_DIR
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


def list_accounts(platform: str = "whatsapp") -> list[Path]:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(account_directory(platform).glob("*.pkl"), key=lambda p: p.name.lower())


def account_label(path: Path) -> str:
    return path.stem


def save_cookies(driver, account_name: str, overwrite: bool = True, platform: str = "whatsapp") -> Path:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

    clean_name = safe_account_name(account_name)
    path = account_directory(platform) / f"{clean_name}.pkl"

    if path.exists() and not overwrite:
        raise FileExistsError(f"Account already exists: {path.name}")

    cookies = driver.get_cookies()

    payload = {
        "version": 1,
        "account_name": clean_name,
        "saved_at": time.time(),
        "url": WHATSAPP_URL if platform == "whatsapp" else INSTAGRAM_URL,
        "platform": platform,
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


def load_cookies(driver, path: Path, platform: str = "whatsapp") -> tuple[str, int, int]:
    account_name, cookies = read_cookie_file(path)

    # Selenium only allows adding cookies for the current domain.
    url = WHATSAPP_URL if platform == "whatsapp" else INSTAGRAM_URL
    driver.get(url)

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
    path = path.resolve()
    if path.parent not in {ACCOUNTS_DIR.resolve(), (ACCOUNTS_DIR / 'instagram').resolve()} or path.suffix != '.pkl':
        raise ValueError('Invalid account path')
    platform = 'instagram' if path.parent.name == 'instagram' else 'whatsapp'
    account_name = path.stem
    path.unlink(missing_ok=True)
    if platform == 'whatsapp':
        delete_session_snapshot(account_name)
    for metadata in SESSIONS_DIR.glob('social_*/accounts.json'):
        try:
            accounts = json.loads(metadata.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if accounts.get(platform) == account_name:
            delete_session_snapshot(metadata.parent.name)


def account_directory(platform: str) -> Path:
    if platform not in {"whatsapp", "instagram"}:
        raise ValueError("Unknown platform")
    path = ACCOUNTS_DIR if platform == "whatsapp" else ACCOUNTS_DIR / platform
    path.mkdir(parents=True, exist_ok=True)
    return path
````

## whatsapp_watcher.py

````python
from __future__ import annotations

import time
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from config import (
    CHECK_INTERVAL,
    LOGIN_TIMEOUT,
    PRESENCE_CHECK_INTERVAL,
    WHATSAPP_URL,
)
from event_logger import log_error, log_event, log_presence_change
from notifier import notify_event
from screenshot_manager import take_screenshot


@dataclass
class MessageSnapshot:
    message_id: str | None
    status: str
    text: str


@dataclass
class PresenceState:
    key: str
    label: str


LAST_SEEN_RE = re.compile(
    r"^last\s+seen\s+"
    r"(?P<day>today|yesterday)\s+"
    r"at\s+"
    r"(?P<time>\d{1,2}:\d{2})$",
    re.IGNORECASE,
)


def xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'

    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"


def is_logged_in(driver: Chrome) -> bool:
    selectors = [
        "#pane-side",
        "div#side",
    ]

    for selector in selectors:
        try:
            items = driver.find_elements(By.CSS_SELECTOR, selector)
            if any(item.is_displayed() for item in items):
                return True
        except Exception:
            pass

    return False


def wait_until_logged_in(driver: Chrome, timeout: int = LOGIN_TIMEOUT) -> bool:
    try:
        WebDriverWait(driver, timeout).until(lambda d: is_logged_in(d))
        return True
    except TimeoutException:
        return False


def wait_for_whatsapp(driver: Chrome) -> bool:
    if "web.whatsapp.com" not in driver.current_url:
        driver.get(WHATSAPP_URL)

    return wait_until_logged_in(driver)


def _find_search_box(driver: Chrome):
    selectors = [
        "div#side div[contenteditable='true'][role='textbox']",
        "div#side div[contenteditable='true']",
        "div[contenteditable='true'][data-tab='3']",
    ]

    for selector in selectors:
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, selector)
            for item in candidates:
                if item.is_displayed() and item.is_enabled():
                    return item
        except Exception:
            pass

    # Fallback for UI/localization changes.
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//div[@id='side']//div[@contenteditable='true' and @role='textbox']",
        )
        for item in candidates:
            if item.is_displayed():
                return item
    except Exception:
        pass

    raise NoSuchElementException(
        "WhatsApp search box was not found. "
        "The WhatsApp Web DOM may have changed."
    )


def _clean_presence_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _normalize_presence(value: str | None) -> PresenceState:
    text = _clean_presence_text(value)

    if not text:
        return PresenceState("not_visible", "Not visible")

    lowered = text.lower()

    if lowered == "not visible":
        return PresenceState("not_visible", "Not visible")

    if lowered == "online":
        return PresenceState("online", text)

    match = LAST_SEEN_RE.match(text)
    if match:
        day = match.group("day").lower()
        seen_time = match.group("time")
        return PresenceState("offline", f"last seen {day} at {seen_time}")

    if lowered.startswith("last seen"):
        return PresenceState("offline", text)

    return PresenceState("unknown", text)


def _looks_like_presence(value: str | None) -> bool:
    text = _clean_presence_text(value).lower()
    return text in {"online", "not visible"} or text.startswith("last seen")




def get_current_chat_presence(
    driver: Chrome,
    attempts: int = 2,
    delay: float = 0.35,
) -> str | None:
    """
    Read the current subtitle shown under the open chat title.

    The function retries several times because WhatsApp Web can render
    chat-subtitle asynchronously after opening/switching a conversation.

    This does not keep a long-running background tracker; it only retries
    during the current manual status check.
    """
    selectors = [
        "#main [data-testid='chat-subtitle'] "
        "span[data-testid='selectable-text']",
        "#main [data-testid='chat-subtitle'] span[title]",
        "#main [data-testid='chat-subtitle']",
    ]

    attempts = max(1, int(attempts))
    delay = max(0.0, float(delay))

    for attempt in range(attempts):
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)

                for element in elements:
                    if not element.is_displayed():
                        continue

                    title = (element.get_attribute("title") or "").strip()

                    text = (
                        element.get_attribute("innerText")
                        or element.text
                        or ""
                    ).strip()

                    value = title or text

                    if value:
                        return value

            except (
                StaleElementReferenceException,
                NoSuchElementException,
            ):
                continue
            except Exception:
                continue

        if attempt < attempts - 1 and delay > 0:
            time.sleep(delay)

    return None


def get_current_chat_name(driver: Chrome) -> str | None:
    """
    Return the title/name of the chat currently open in WhatsApp Web.

    We intentionally look only inside #main header so we do not accidentally
    read a contact title from the left sidebar.
    """
    try:
        value = driver.execute_script(
            r"""
            const header = document.querySelector("#main header");
            if (!header) return null;

            const selectors = [
              "[data-testid='conversation-info-header-chat-title']",
              "[role='button'] span[dir='auto']",
              "span[title]"
            ];

            for (const selector of selectors) {
              const nodes = Array.from(header.querySelectorAll(selector));
              for (const node of nodes) {
                if (!node.getClientRects().length) continue;
                if (node.closest("[data-testid='chat-subtitle']")) continue;
                const value = (node.getAttribute("title")
                  || node.innerText
                  || node.textContent
                  || "").trim();
                if (value && !/^(online|not visible|last seen\b|typing)/i.test(value)) return value;
              }
            }

            return null;
            """
        )
        value = (value or "").strip()
        if value and not _looks_like_presence(value):
            return value
    except Exception:
        pass

    selectors = [
        "#main header [data-testid='conversation-info-header-chat-title']",
        "#main header [role='button'] span[dir='auto']",
        "#main header span[title]",
    ]

    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                if not element.is_displayed():
                    continue
                try:
                    if element.find_elements(
                        By.XPATH,
                        "ancestor::*[@data-testid='chat-subtitle']",
                    ):
                        continue
                except Exception:
                    pass

                title = (element.get_attribute("title") or "").strip()
                text = (element.text or "").strip()

                value = title or text
                if value and not _looks_like_presence(value):
                    return value
        except Exception:
            pass

    # XPath fallback for WhatsApp Web DOM changes.
    xpaths = [
        (
            "//*[@id='main']//header//*[@role='button']//span[@dir='auto' "
            "and not(ancestor::*[@data-testid='chat-subtitle'])]"
        ),
        (
            "//*[@id='main']//header//span[@title "
            "and not(ancestor::*[@data-testid='chat-subtitle'])]"
        ),
    ]

    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for element in elements:
                if not element.is_displayed():
                    continue

                value = (
                    (element.get_attribute("title") or "").strip()
                    or (element.text or "").strip()
                )
                if value and not _looks_like_presence(value):
                    return value
        except Exception:
            pass

    return None

def open_chat(driver: Chrome, contact: str, timeout: int = 25) -> bool:
    contact = contact.strip()
    if not contact:
        raise ValueError("Contact name is empty")

    search = WebDriverWait(driver, timeout).until(lambda d: _find_search_box(d))
    search.click()

    # contenteditable elements respond better to CTRL+A than .clear()
    search.send_keys(Keys.CONTROL, "a")
    search.send_keys(Keys.BACKSPACE)
    search.send_keys(contact)

    exact = xpath_literal(contact)
    xpaths = [
        f"//span[@title={exact}]",
        f"//*[@id='pane-side']//span[@title={exact}]",
    ]

    deadline = time.time() + timeout
    while time.time() < deadline:
        for xp in xpaths:
            try:
                matches = driver.find_elements(By.XPATH, xp)
                for match in matches:
                    if match.is_displayed():
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            match,
                        )
                        match.click()
                        time.sleep(1)
                        return True
            except StaleElementReferenceException:
                continue

        time.sleep(0.35)

    # Leave the typed search text visible so the user can see what failed.
    return False


def _message_text(message_element) -> str:
    selectors = [
        "span.selectable-text",
        "div.copyable-text span",
        "div.copyable-text",
    ]

    for selector in selectors:
        try:
            pieces = message_element.find_elements(By.CSS_SELECTOR, selector)
            texts = []
            for item in pieces:
                txt = (item.get_attribute("innerText") or item.text or "").strip()
                if txt and txt not in texts:
                    texts.append(txt)

            if texts:
                return " ".join(texts).strip()
        except Exception:
            pass

    raw = (message_element.get_attribute("innerText") or "").strip()
    return raw


def _status_from_message(message_element) -> str:
    try:
        icons = message_element.find_elements(By.CSS_SELECTOR, "span[data-icon]")
    except Exception:
        return "unknown"

    seen_icons = []

    for icon in reversed(icons):
        try:
            data_icon = (icon.get_attribute("data-icon") or "").strip().lower()
            aria = (icon.get_attribute("aria-label") or "").strip().lower()
            seen_icons.append((data_icon, aria))

            if data_icon in {"msg-dblcheck-ack", "msg-dblcheck-ack-light"}:
                return "read"

            if data_icon == "msg-dblcheck":
                # Newer/older WhatsApp builds sometimes keep the same icon
                # but expose "Read" through aria-label.
                if any(
                    token in aria
                    for token in (
                        "read",
                        "seen",
                        "lu",
                        "lue",
                        "Ù‚Ø±Ø¦Øª",
                        "Ù…Ù‚Ø±ÙˆØ¡",
                    )
                ):
                    return "read"
                return "delivered"

            if data_icon == "msg-check":
                return "sent"

            if data_icon in {"msg-time", "msg-clock"}:
                return "pending"
        except StaleElementReferenceException:
            continue

    # Fallback: inspect HTML for status markers if icon walking failed.
    try:
        html = (message_element.get_attribute("innerHTML") or "").lower()
        if "msg-dblcheck-ack" in html:
            return "read"
        if "msg-dblcheck" in html:
            return "delivered"
        if "msg-check" in html:
            return "sent"
        if "msg-time" in html:
            return "pending"
    except Exception:
        pass

    return "unknown"


def get_last_outgoing_message(driver: Chrome) -> MessageSnapshot | None:
    """
    Detect the latest outgoing message using the CURRENT WhatsApp Web DOM.

    Current structure observed:
      - outer row: data-testid="conv-msg-..."
      - outgoing marker: descendant span[aria-label="You:"]
      - metadata: div[data-testid="msg-meta"]
      - status: span[aria-label=" Sent " | " Delivered " | " Read "]

    We intentionally avoid WhatsApp's random CSS class names.
    """

    try:
        rows = driver.find_elements(
            By.CSS_SELECTOR,
            "#main [data-testid^='conv-msg-']"
        )
    except Exception:
        rows = []

    if not rows:
        return None

    # Work backwards: the most recent outgoing rendered row is what we want.
    for row in reversed(rows):
        try:
            # Empty virtualized rows have no inner message DOM.
            if not row.is_displayed():
                continue

            # Reliable marker for a message authored by the current account.
            you_markers = row.find_elements(
                By.CSS_SELECTOR,
                "span[aria-label='You:']"
            )
            if not you_markers:
                # Fallback to the accessibility label used by the message row.
                outgoing_nodes = row.find_elements(
                    By.CSS_SELECTOR,
                    "[aria-label^='You  ']"
                )
                if not outgoing_nodes:
                    continue

            message_id = (
                row.get_attribute("data-id")
                or row.get_attribute("data-testid")
                or None
            )

            # Status is exposed directly by WhatsApp in aria-label.
            status = "unknown"

            status_nodes = row.find_elements(
                By.CSS_SELECTOR,
                "[data-testid='msg-meta'] span[aria-label]"
            )

            for node in reversed(status_nodes):
                label = (
                    node.get_attribute("aria-label") or ""
                ).strip().lower()

                if label == "read":
                    status = "read"
                    break
                if label == "delivered":
                    status = "delivered"
                    break
                if label == "sent":
                    status = "sent"
                    break
                if label in {"pending", "sending"}:
                    status = "pending"
                    break

            # Accessibility-label fallback.
            if status == "unknown":
                labelled = row.find_elements(By.CSS_SELECTOR, "[aria-label]")
                labels = [
                    (el.get_attribute("aria-label") or "").strip().lower()
                    for el in labelled
                ]

                if "read" in labels:
                    status = "read"
                elif "delivered" in labels:
                    status = "delivered"
                elif "sent" in labels:
                    status = "sent"

            # SVG-title fallback. Note: current WhatsApp uses wds-ic-read
            # for both Delivered and Read, so aria-label above remains primary.
            if status == "unknown":
                titles = [
                    (el.get_attribute("textContent") or "").strip().lower()
                    for el in row.find_elements(By.CSS_SELECTOR, "svg title")
                ]

                if "wds-ic-delivered" in titles:
                    status = "sent"
                elif "wds-ic-read" in titles:
                    status = "delivered"

            # Extract the actual message body while ignoring quoted-message text.
            try:
                text = driver.execute_script(
                    """
                    const row = arguments[0];
                    const nodes = Array.from(
                        row.querySelectorAll(
                            "span[data-testid='selectable-text']"
                        )
                    ).filter(el => !el.closest(
                        "[data-testid='quoted-message']"
                    ));

                    const values = [];
                    for (const el of nodes) {
                        const value = (el.innerText || el.textContent || "").trim();
                        if (value && !values.includes(value)) {
                            values.push(value);
                        }
                    }
                    return values.join(" ").trim();
                    """,
                    row,
                ) or ""
            except Exception:
                text = ""

            # Fallback to copyable text if the selectable-text structure changes.
            if not text:
                try:
                    copyables = row.find_elements(
                        By.CSS_SELECTOR,
                        "div.copyable-text[data-pre-plain-text]"
                    )
                    if copyables:
                        text = (
                            copyables[-1].get_attribute("innerText")
                            or copyables[-1].text
                            or ""
                        ).strip()
                except Exception:
                    text = ""

            return MessageSnapshot(
                message_id=message_id,
                status=status,
                text=text,
            )

        except StaleElementReferenceException:
            continue
        except Exception:
            continue

    return None


def _event_rank(status: str) -> int:
    return {
        "unknown": -1,
        "pending": 0,
        "sent": 1,
        "delivered": 2,
        "read": 3,
    }.get(status, -1)


def _notify_transition(
    driver: Chrome,
    *,
    account: str,
    contact: str,
    snapshot: MessageSnapshot,
    event: str,
) -> None:
    screenshot_path: Path | None = None

    try:
        if event in {"delivered", "read", "seen"}:
            screenshot_path = take_screenshot(
                driver, account=account, contact=contact, event=event,
            )
    except Exception as exc:
        log_error("take_screenshot", exc)

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    row = log_event(
        account=account,
        contact=contact,
        event=event,
        status=snapshot.status,
        message_id=snapshot.message_id,
        message_preview=snapshot.text,
        screenshot=str(screenshot_path) if screenshot_path else None,
    )

    try:
        notify_event(
            account=account,
            contact=contact,
            event=event,
            status=snapshot.status,
            message_preview=snapshot.text,
            timestamp=row["timestamp"],
            screenshot_path=screenshot_path,
        )
    except Exception as exc:
        log_error("notify_event", exc)



def _notify_online_manual(
    driver: Chrome,
    *,
    account: str,
    contact: str,
) -> None:
    """
    Send ONLINE notification for a MANUAL status refresh only.
    """
    screenshot_path: Path | None = None

    try:
        screenshot_path = take_screenshot(
            driver,
            account=account,
            contact=contact,
            event="online",
        )
    except Exception as exc:
        log_error("online_manual_screenshot", exc)

    row = log_event(
        account=account,
        contact=contact,
        event="online",
        status="online",
        message_id=None,
        message_preview="Current chat status is online",
        screenshot=str(screenshot_path) if screenshot_path else None,
    )

    try:
        notify_event(
            account=account,
            contact=contact,
            event="online",
            status="online",
            message_preview="Current chat status is online",
            timestamp=row["timestamp"],
            screenshot_path=screenshot_path,
        )
    except Exception as exc:
        log_error("online_manual_notify", exc)


def _notify_presence_change(
    driver: Chrome,
    *,
    account: str,
    contact: str,
    previous_status: str,
    current_status: str,
    event: str,
) -> None:
    screenshot_path: Path | None = None

    try:
        screenshot_path = take_screenshot(
            driver,
            account=account,
            contact=contact,
            event=event,
        )
    except Exception as exc:
        log_error("presence_change_screenshot", exc)

    preview = f"{previous_status} -> {current_status}"

    row = log_event(
        account=account,
        contact=contact,
        event=event,
        status=current_status,
        message_id=None,
        message_preview=preview,
        screenshot=str(screenshot_path) if screenshot_path else None,
    )
    log_presence_change(
        account=account,
        contact=contact,
        previous_status=previous_status,
        current_status=current_status,
        event=event,
        screenshot=str(screenshot_path) if screenshot_path else None,
    )

    try:
        notify_event(
            account=account,
            contact=contact,
            event=event,
            status=current_status,
            message_preview=preview,
            timestamp=row["timestamp"],
            screenshot_path=screenshot_path,
        )
    except Exception as exc:
        log_error("presence_change_notify", exc)


def watch_chat_combined(driver, *, account: str, contact: str) -> None:
    """Compatibility entry point: one message tick, never a competing driver loop.

    Continuous scheduling is owned by PlatformManager.
    """
    from platform_manager import MessageTracker
    tracker = getattr(driver, "_social_message_tracker", None)
    if tracker is None:
        tracker = driver._social_message_tracker = MessageTracker()
    current_contact = get_current_chat_name(driver)
    if current_contact:
        tracker.observe("whatsapp", account, current_contact,
                        get_last_outgoing_message(driver),
                        lambda snapshot: _notify_transition(
                            driver, account=account, contact=current_contact,
                            snapshot=snapshot, event=snapshot.status))


def watch_last_outgoing_message(driver, *, account: str, contact: str) -> None:
    watch_chat_combined(driver, account=account, contact=contact)
````

## instagram_watcher.py

````python
"""Conservative Instagram UI readers; never infer delivery from bubble colour."""
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from whatsapp_watcher import MessageSnapshot


def is_logged_in(driver):
    return bool(driver.execute_script(r"""
      return !document.querySelector('input[name="password"]') &&
        !!document.querySelector('a[href="/direct/inbox/"], a[href^="/direct/t/"]');
    """))


def wait_until_logged_in(driver, timeout=180):
    try:
        WebDriverWait(driver, timeout).until(is_logged_in)
        return True
    except TimeoutException:
        return False


def _header(driver):
    return driver.execute_script(r"""
      if (!location.pathname.startsWith('/direct/t/')) return null;
      const composer = document.querySelector('[contenteditable="true"][role="textbox"], textarea');
      if (!composer) return null;
      let root = composer.parentElement;
      while (root && !root.querySelector('header, [role="banner"], [role="heading"]')) root = root.parentElement;
      if (!root) return null;
      const heading = root.querySelector('header, [role="banner"]') ||
                      root.querySelector('[role="heading"]').parentElement;
      return heading;
    """)


def get_current_chat_name(driver):
    header = _header(driver)
    if header is None:
        return None
    return driver.execute_script(r"""
      for (const a of arguments[0].querySelectorAll('a[href]')) {
        const path = new URL(a.href).pathname;
        const m = path.match(/^\/([A-Za-z0-9._]+)\/$/);
        if (m && !['direct','explore','accounts','reels'].includes(m[1])) return '@' + m[1];
      }
      const h = arguments[0].querySelector('[role="heading"], h1, h2');
      const text = h ? h.innerText.trim() : '';
      return text && !/^active /i.test(text) ? text : null;
    """, header)


def get_current_chat_presence(driver, **_):
    header = _header(driver)
    if header is None:
        return None
    return driver.execute_script(r"""
      const lines = arguments[0].innerText.split('\n').map(s => s.trim());
      return lines.find(s => /^Active (now|.* ago|today|yesterday)$/i.test(s)) || null;
    """, header)


def get_last_outgoing_message(driver):
    if '/direct/t/' not in driver.current_url:
        return None
    data = driver.execute_script(r"""
      const rows = [...document.querySelectorAll('main [role="row"], [role="main"] [role="row"]')];
      for (const row of rows.reverse()) {
        if (!row.getClientRects().length) continue;
        const label = row.getAttribute('aria-label') || '';
        // Require explicit authorship. Unknown layouts return unavailable.
        if (!/^(You:|You sent|You replied)/i.test(label) &&
            !row.querySelector('[aria-label="You:"]')) continue;
        const id = row.getAttribute('data-message-id') || row.getAttribute('data-item-id') || row.id;
        if (!id) continue;
        const lines = row.innerText.split('\n').map(s => s.trim());
        const seen = lines.some(s => /^Seen(?: .*)?$/.test(s)) ||
                     !!row.querySelector('[aria-label="Seen"]');
        const sent = lines.includes('Sent') || /^You sent/i.test(label);
        return {id, status: seen ? 'seen' : sent ? 'sent' : 'unknown',
                text: lines.filter(s => !/^(Seen(?: .*)?|Sent)$/.test(s)).join(' ')};
      }
      return null;
    """)
    return MessageSnapshot(data['id'], data['status'], data['text']) if data else None
````

## telegram_controller.py

````python
"""Long polling remote UI. Never accesses the Selenium driver."""
from pathlib import Path
from threading import Event, Thread
import json
import time
from uuid import uuid4
import requests
import config
from notifier import send_telegram_photo, telegram_is_configured
from event_logger import log_error


def format_result(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and any(p in value for p in ('whatsapp', 'instagram')):
        blocks = []
        for p, row in value.items():
            if not isinstance(row, dict):
                blocks.append(f'{p.title()}: {row}')
                continue
            blocks.append(p.title() + '\n' + '\n'.join(
                f'{key.replace("_", " ").title()}: {val}' for key, val in row.items()))
        return '\n\n'.join(blocks)
    return json.dumps(value, ensure_ascii=False, indent=2)


def menu(page='main'):
    if page in {'whatsapp', 'instagram'}:
        p = page
        rows = [[('Current Chat' if p == 'whatsapp' else 'Current DM', f'status:{p}')],
                [('Current Status' if p == 'whatsapp' else 'Activity Status', f'status:{p}')],
                [('Refresh Status', f'refresh:{p}')],
                [('Message Status' if p == 'whatsapp' else 'Seen Status', f'status:{p}')],
                [('Screenshot', f'screenshot:{p}')],
                [('Start Watch', f'watch:{p}'), ('Stop Watch', f'stop:{p}')],
                [('Save session', f'save:{p}')], [('Back', 'menu:main')]]
    elif page == 'watchers':
        rows = [[('Start WhatsApp', 'watch:whatsapp'), ('Stop WhatsApp', 'stop:whatsapp')],
                [('Start Instagram', 'watch:instagram'), ('Stop Instagram', 'stop:instagram')],
                [('Start All', 'watch:all'), ('Stop All', 'stop:all')], [('Back', 'menu:main')]]
    else:
        rows = [[('WhatsApp', 'menu:whatsapp'), ('Instagram', 'menu:instagram')],
                [('Status All', 'status:all')], [('Refresh All', 'refresh:all')],
                [('Screenshots', 'screenshot:all')], [('Watchers', 'menu:watchers')],
                [('Accounts', 'accounts:all')], [('Logs', 'logs:all')],
                [('Settings', 'settings:all')]]
    return {'inline_keyboard': [[{'text': label, 'callback_data': data} for label, data in row] for row in rows]}


class TelegramController:
    def __init__(self, manager):
        self.manager = manager
        self.stop_event = Event()
        self.thread = None
        self.account_choices = {}
        self.pending = []
        self.offset = 0
        self.started_at = int(time.time())
        self.pages = {}

    def start(self):
        if not telegram_is_configured():
            return 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env'
        if self.thread and self.thread.is_alive():
            return 'Telegram control already running'
        self.stop_event.clear()
        self.thread = Thread(target=self._run, name='telegram-controller', daemon=True)
        self.thread.start()
        return 'Telegram control started'

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=20)
        return 'Telegram control stopped'

    def _api(self, method, **payload):
        try:
            response = requests.post(f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}',
                                     json=payload, timeout=(5, 15))
            data = response.json()
            if not data.get('ok'):
                if 'message is not modified' in data.get('description', ''):
                    return None
                raise RuntimeError('Telegram API rejected ' + method + ': ' + str(data.get('error_code')))
            return data.get('result')
        except requests.RequestException as exc:
            raise RuntimeError('Telegram network error: ' + type(exc).__name__) from None

    def _reply(self, text, message_id=None, keyboard=None):
        payload = dict(chat_id=config.TELEGRAM_CHAT_ID, text=text[:3900], reply_markup=keyboard or menu())
        if message_id:
            try:
                return self._api('editMessageText', message_id=message_id, **payload)
            except RuntimeError:
                pass
        return self._api('sendMessage', **payload)

    def _authorized(self, update):
        query = update.get('callback_query')
        message = query.get('message', {}) if query else update.get('message', {})
        sender = query.get('from', {}) if query else message.get('from', {})
        return (message.get('chat', {}).get('type') == 'private' and
                str(message.get('chat', {}).get('id')) == config.TELEGRAM_CHAT_ID and
                str(sender.get('id')) == config.TELEGRAM_CHAT_ID and not sender.get('is_bot'))

    def _handle(self, update):
        if not self._authorized(update):
            return
        query = update.get('callback_query')
        message = query['message'] if query else update['message']
        mid = message.get('message_id') if query else None
        if query:
            self._api('answerCallbackQuery', callback_query_id=query['id'])
            command = query.get('data', '')
        else:
            if message.get('date', 0) < self.started_at:
                return
            text = message.get('text', '').split()
            command = text[0].split('@')[0].lstrip('/') if text else 'help'
            command = {'start': 'menu:main', 'menu': 'menu:main',
                       'whatsapp': 'menu:whatsapp', 'instagram': 'menu:instagram'}.get(command, command)
            if ':' not in command:
                command += ':all'
        action, _, p = command.partition(':')
        if action == 'menu':
            self.pages[mid] = p
            if p in {'whatsapp', 'instagram'}:
                self.pending.append((self.manager.submit('focus', p), mid, menu(p), 'focus'))
            else:
                self._reply('Social Watcher — ' + p, mid, menu(p))
            return
        if action == 'choose':
            selection = self.account_choices.get(p)
            if not selection:
                self._reply('Account menu expired. Open Accounts again.', mid)
                return
            platform, name = selection
            future = self.manager.submit('select', platform, account=name)
        elif action in {'status', 'refresh', 'screenshot', 'watch', 'stop', 'accounts', 'logs', 'settings', 'save'}:
            future = self.manager.submit(action, p)
        else:
            self._reply('/start /menu /status /whatsapp /instagram /refresh /screenshot '
                        '/watch /stop /accounts /logs /help\nPresence is refreshed manually. '
                        'Log in inside Chrome; use Save session afterwards.', mid)
            return
        page = self.pages.get(mid, p if p in {'whatsapp', 'instagram'} else 'main')
        self.pending.append((future, mid, menu(page), action))

    def _complete(self):
        remaining = []
        for future, mid, keyboard, action in self.pending:
            if not future.done():
                remaining.append((future, mid, keyboard, action))
                continue
            try:
                value = future.result()
                if action == 'accounts':
                    self.account_choices.clear()
                    rows = []
                    for p, accounts in value.items():
                        for name in accounts['saved']:
                            key = uuid4().hex[:16]
                            self.account_choices[key] = (p, name)
                            rows.append([{'text': f'{p}: {name}'[:60], 'callback_data': 'choose:' + key}])
                    rows.append([{'text': 'Back', 'callback_data': 'menu:main'}])
                    keyboard = {'inline_keyboard': rows}
                if action == 'screenshot':
                    for p, path in value.items():
                        if isinstance(path, str):
                            ok, info = send_telegram_photo(Path(path), p.title())
                            value[p] = info
                self._reply(format_result(value), mid, keyboard)
            except Exception as exc:
                log_error('telegram_result', exc)
                self._reply('Command failed. Check local errors.json.', mid, keyboard)
        self.pending = remaining

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self._complete()
                updates = self._api('getUpdates', offset=self.offset, timeout=1 if self.pending else 10,
                                    allowed_updates=['message', 'callback_query']) or []
                for update in updates:
                    self.offset = update['update_id'] + 1
                    try:
                        self._handle(update)
                    except Exception as exc:
                        log_error('telegram_update', exc)
            except Exception as exc:
                log_error('telegram_poll', exc)
                self.stop_event.wait(5)
````

## platform_manager.py

````python
"""The sole owner of Selenium. Both UIs submit commands, never driver calls."""
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Queue, Empty
from threading import Thread, Lock
from datetime import datetime
from hashlib import sha256
import json
import time
from copy import deepcopy

import config
import whatsapp_watcher as whatsapp
import instagram_watcher as instagram
from account_manager import list_accounts, save_cookies, load_cookies, safe_account_name, delete_account
from browser import create_driver
from session_manager import (has_session_snapshot, save_session_snapshot,
                             cleanup_temp_profile, restore_session_snapshot)
from event_logger import log_error, log_event, log_presence_change, _read_json_array
from screenshot_manager import take_screenshot
from notifier import notify_event

PLATFORMS = {'whatsapp': whatsapp, 'instagram': instagram}


class MessageTracker:
    def __init__(self):
        self.ranks = {}
        self.chats = set()

    def observe(self, platform, account, contact, snapshot, emit):
        if not snapshot or not snapshot.message_id:
            return
        rank = {'pending': 0, 'sent': 1, 'delivered': 2, 'read': 3, 'seen': 3}.get(snapshot.status)
        if rank is None:
            return
        chat = (platform, account, contact)
        key = (*chat, snapshot.message_id)
        previous = self.ranks.get(key)
        first = chat not in self.chats
        self.chats.add(chat)
        self.ranks[key] = max(rank, previous if previous is not None else -1)
        if not first and rank > (previous if previous is not None else -1) and rank > 0:
            emit(snapshot)


class PlatformManager:
    def __init__(self):
        config.ensure_directories()
        self.selenium_command_queue = Queue(maxsize=100)
        self.thread = Thread(target=self._run, name='selenium-worker')
        self.notifications = ThreadPoolExecutor(max_workers=1, thread_name_prefix='notifications')
        self.driver = None
        self.handles = {}
        self.active = {p: (list_accounts(p)[0].stem if list_accounts(p) else
                           ('default' if p == 'whatsapp' else 'instagram_main')) for p in PLATFORMS}
        self.active_file = config.DATA_DIR / 'active_accounts.json'
        try:
            saved = json.loads(self.active_file.read_text(encoding='utf-8'))
            for p in PLATFORMS:
                if isinstance(saved.get(p), str):
                    self.active[p] = safe_account_name(saved[p])
        except (OSError, ValueError, AttributeError):
            pass
        self.watching = dict.fromkeys(PLATFORMS, False)
        self.cache = {p: {} for p in PLATFORMS}
        self.presence = {}
        self.messages = MessageTracker()
        self.accepting = True
        self.submit_lock = Lock()
        self.error_times = {}
        self.thread.start()

    def submit(self, action, platform='all', **kwargs):
        future = Future()
        with self.submit_lock:
            if not self.accepting:
                future.set_exception(RuntimeError('Worker has stopped'))
            else:
                self.selenium_command_queue.put_nowait((action, platform, kwargs, future))
        return future

    def call(self, action, platform='all', **kwargs):
        return self.submit(action, platform, **kwargs).result()

    def close(self):
        with self.submit_lock:
            self.accepting = False
            future = Future()
            self.selenium_command_queue.put(('exit', 'all', {}, future))
        try:
            future.result()
        finally:
            self.thread.join()
            self.notifications.shutdown(wait=True)

    def _session_key(self):
        return 'social_' + sha256(json.dumps(self.active, sort_keys=True).encode()).hexdigest()[:24]

    def _open(self):
        self.session_key = self._session_key()
        # Legacy WhatsApp snapshots remain intact and seed a pair on first use.
        seed = self.session_key if has_session_snapshot(self.session_key) else self.active['whatsapp']
        seed_pair = None
        if seed != self.session_key:
            candidates = sorted(config.SESSIONS_DIR.glob('social_*/accounts.json'),
                                key=lambda path: path.stat().st_mtime, reverse=True)
            for metadata in candidates:
                try:
                    pair = json.loads(metadata.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if pair.get('whatsapp') == self.active['whatsapp']:
                    seed = metadata.parent.name
                    seed_pair = pair
                    break
        self.driver = create_driver(seed)
        if seed_pair and seed_pair.get('instagram') != self.active['instagram']:
            # Retain the matching WhatsApp database, but never open the wrong IG account.
            try:
                for origin in ('https://www.instagram.com', 'https://instagram.com'):
                    self.driver.execute_cdp_cmd('Storage.clearDataForOrigin',
                                                {'origin': origin, 'storageTypes': 'all'})
            except Exception:
                self.driver.quit()
                temp = self.driver._wa_temp_profile
                self.driver = None
                cleanup_temp_profile(temp)
                raise
        tmp = self.active_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.active), encoding='utf-8')
        tmp.replace(self.active_file)
        self.handles = {}
        for index, p in enumerate(PLATFORMS):
            if index:
                self.driver.switch_to.new_window('tab')
            self.handles[p] = self.driver.current_window_handle
            setattr(self, p + '_handle', self.handles[p])
            try:
                self.driver.get(config.WHATSAPP_URL if p == 'whatsapp' else config.INSTAGRAM_URL)
                restored = has_session_snapshot(self.session_key) or (p == 'whatsapp' and has_session_snapshot(seed))
                if not restored and not PLATFORMS[p].is_logged_in(self.driver):
                    path = next((x for x in list_accounts(p) if x.stem == self.active[p]), None)
                    if path:
                        load_cookies(self.driver, path, p)
            except Exception as exc:
                self._error(p, exc)

    def _close_browser(self):
        if self.driver is None:
            return
        driver = self.driver
        temp = driver._wa_temp_profile
        for p in PLATFORMS:
            try:
                self._switch(p)
                if PLATFORMS[p].is_logged_in(driver):
                    save_cookies(driver, self.active[p], platform=p)
            except Exception as exc:
                self._error(p, exc)
        # A failed quit must not cause another Chrome instance to be launched.
        driver.quit()
        self.driver = None
        try:
            save_session_snapshot(self.session_key, temp, accounts=self.active)
        except Exception:
            log_error('session_save', 'Snapshot failed; temporary profile retained at ' + str(temp))
            raise
        else:
            cleanup_temp_profile(temp)

    def _switch(self, p):
        if self.driver is None:
            raise RuntimeError('Browser unavailable; select an account to retry')
        self.driver.switch_to.window(self.handles[p])

    def _error(self, p, exc):
        self.cache[p]['error'] = type(exc).__name__ + ': UI unavailable; retry refresh'
        key = (p, type(exc).__name__)
        if time.monotonic() - self.error_times.get(key, -60) > 60:
            log_error(p, exc)
            self.error_times[key] = time.monotonic()

    def _capture(self, p, contact, event):
        return take_screenshot(self.driver, self.active[p], contact or 'current', event, p)

    def _emit(self, p, contact, status, snapshot=None, previous=None):
        screenshot = None
        if status in {'delivered', 'read', 'seen', 'online', 'offline', 'unavailable'}:
            try:
                screenshot = self._capture(p, contact, status)
            except Exception as exc:
                self._error(p, exc)
        label = snapshot.status if snapshot else self.presence[(p, self.active[p], contact)]
        args = dict(platform=p, account=self.active[p], contact=contact,
                    event='presence_changed' if previous is not None else status,
                    status=label, message_id=snapshot.message_id if snapshot else None,
                    message_preview=snapshot.text if snapshot else '',
                    screenshot=str(screenshot) if screenshot else None)
        if previous is not None:
            args.update(previous_status=previous, current_status=label)
        row = log_event(**args)
        if previous is not None:
            log_presence_change(platform=p, account=self.active[p], contact=contact,
                                previous_status=previous, current_status=label,
                                event='presence_changed', screenshot=args['screenshot'])
        self.notifications.submit(notify_event, platform=p, account=self.active[p],
                                  contact=contact, event=status, status=label,
                                  message_preview=args['message_preview'], timestamp=row['timestamp'],
                                  screenshot_path=screenshot, previous_status=previous)

    def _read(self, p, refresh=False, watch=False):
        self._switch(p)
        module = PLATFORMS[p]
        logged_in = module.is_logged_in(self.driver)
        contact = module.get_current_chat_name(self.driver) if logged_in else None
        old = self.cache[p]
        same = old.get('contact') == contact
        result = dict(account=self.active[p], contact=contact, logged_in=logged_in,
                      presence=old.get('presence', 'Not refreshed') if same else 'Not refreshed',
                      presence_at=old.get('presence_at') if same else None,
                      message='Unavailable', watching=self.watching[p])
        self.cache[p] = result
        if not contact:
            return result
        snapshot = module.get_last_outgoing_message(self.driver)
        if module.get_current_chat_name(self.driver) != contact:
            raise RuntimeError('Chat changed during read')
        result['message'] = snapshot.status if snapshot else 'Unavailable'
        if watch:
            self.messages.observe(p, self.active[p], contact, snapshot,
                                  lambda item: self._emit(p, contact, item.status, item))
        if refresh:
            self._refresh_presence(p, contact)
        return result

    def _refresh_presence(self, p, contact):
        module = PLATFORMS[p]
        candidate, count = None, 0
        # Bounded manual debounce. No state reads from the message timer.
        for index in range(config.PRESENCE_CONFIRMATIONS * 3):
            if index:
                time.sleep(config.PRESENCE_CHECK_DELAY)
            if module.get_current_chat_name(self.driver) != contact:
                raise RuntimeError('Chat changed during refresh')
            value = module.get_current_chat_presence(self.driver, attempts=1, delay=0)
            value = ' '.join((value or 'Not visible').split()) or 'Not visible'
            if module.get_current_chat_name(self.driver) != contact:
                raise RuntimeError('Chat changed during refresh')
            if p == 'whatsapp' and whatsapp._normalize_presence(value).key == 'unknown':
                candidate, count = None, 0
                continue
            count = count + 1 if value == candidate else 1
            candidate = value
            if count >= config.PRESENCE_CONFIRMATIONS:
                break
        else:
            self.cache[p]['error'] = 'Unstable presence; refresh again'
            return
        key = (p, self.active[p], contact)
        previous = self.presence.get(key, 'Not visible')
        self.presence[key] = candidate
        self.cache[p].update(presence=candidate, presence_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        online = 'online' if p == 'whatsapp' else 'active now'
        if candidate.lower() == online and previous.lower() != online:
            self._emit(p, contact, 'online', previous=previous)
        elif previous.lower() == online and (candidate == 'Not visible' or
              candidate.lower().startswith(('last seen', 'active '))):
            self._emit(p, contact, 'unavailable' if candidate == 'Not visible' else 'offline', previous=previous)

    def _execute(self, action, platform, kwargs):
        targets = list(PLATFORMS) if platform == 'all' else [platform]
        if any(p not in PLATFORMS for p in targets):
            raise ValueError('Unknown platform')
        if action == 'accounts':
            return {p: {'active': self.active[p], 'saved': [x.stem for x in list_accounts(p)]} for p in targets}
        if action == 'logs':
            return _read_json_array(config.EVENTS_FILE)[-10:]
        if action == 'history':
            return _read_json_array(config.PRESENCE_HISTORY_FILE)[-50:]
        if action == 'settings':
            return {'check_interval': config.CHECK_INTERVAL, 'presence': 'Manual refresh only',
                    'confirmations': config.PRESENCE_CONFIRMATIONS, 'delay': config.PRESENCE_CHECK_DELAY}
        if action == 'select':
            if platform == 'all':
                raise ValueError('Select one platform')
            name = safe_account_name(kwargs['account'])
            if self.active[platform] == name and self.driver is not None:
                return self._read(platform)
            self._close_browser()
            self.active[platform] = name
            self.cache = {p: {} for p in PLATFORMS}
            self._open()
            return 'Account selected. Complete login in Chrome if needed, then choose Save session.'
        if action == 'delete':
            if platform == 'all' or kwargs['account'] == self.active[platform]:
                raise ValueError('Select another account before deleting this one')
            path = next((x for x in list_accounts(platform) if x.stem == kwargs['account']), None)
            if path is None:
                raise ValueError('Account not found')
            delete_account(path)
            return 'Saved account and associated session snapshots deleted'
        if action in {'watch', 'stop'}:
            for p in targets:
                self.watching[p] = action == 'watch'
            return dict(self.watching)
        results = {}
        for p in targets:
            try:
                if action in {'status', 'refresh', 'focus'}:
                    results[p] = self._read(p, refresh=action == 'refresh')
                elif action == 'screenshot':
                    self._switch(p)
                    results[p] = str(self._capture(p, PLATFORMS[p].get_current_chat_name(self.driver), 'manual'))
                elif action == 'save':
                    self._switch(p)
                    if not PLATFORMS[p].is_logged_in(self.driver):
                        raise RuntimeError('Login not detected')
                    save_cookies(self.driver, self.active[p], platform=p)
                    results[p] = 'Cookies saved; full lightweight snapshot saved on exit/switch.'
                else:
                    raise ValueError('Unknown command')
            except Exception as exc:
                self._error(p, exc)
                results[p] = dict(self.cache[p])
        return results

    def _run(self):
        try:
            self._open()
        except Exception as exc:
            log_error('browser_start', exc)
        next_check = time.monotonic()
        try:
            while True:
                try:
                    action, p, kwargs, future = self.selenium_command_queue.get(timeout=max(0, next_check-time.monotonic()))
                except Empty:
                    action = None
                if action:
                    if action == 'exit':
                        try:
                            self._close_browser()
                            future.set_result(None)
                        except Exception as exc:
                            future.set_exception(exc)
                        return
                    if future.set_running_or_notify_cancel():
                        try:
                            future.set_result(deepcopy(self._execute(action, p, kwargs)))
                        except Exception as exc:
                            log_error('command_' + action, exc)
                            future.set_exception(RuntimeError(type(exc).__name__ + ': command failed; see local errors.json'))
                if time.monotonic() >= next_check:
                    for platform, enabled in self.watching.items():
                        if enabled:
                            try:
                                self._read(platform, watch=True)
                            except Exception as exc:
                                self._error(platform, exc)
                    next_check = time.monotonic() + config.CHECK_INTERVAL
        finally:
            self.accepting = False
````

## notifier.py

````python
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
        return False, type(exc).__name__


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
        return False, type(exc).__name__


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
        return False, type(exc).__name__


def notify_event(
    *,
    account: str,
    contact: str,
    event: str,
    status: str,
    message_preview: str,
    timestamp: str,
    screenshot_path: Path | None,
    platform: str = "whatsapp",
    previous_status: str | None = None,
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

    brand = "WhatsApp" if platform == "whatsapp" else "Instagram"
    icon = {"online": "🟢", "offline": "⚪", "unavailable": "⚪",
            "delivered": "✅", "read": "🔵", "seen": "📸"}.get(event, "💬")
    text = f"{icon} {brand} {event.upper()}\n\n👤 {contact}\n📱 {account}\n🕒 {timestamp}"
    if previous_status is not None:
        text += f"\n\nPrevious: {previous_status}\nCurrent: {status}"
    else:
        text += f"\n💬 {preview}"

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
        title=f"{brand} - {contact}",
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
````

## event_logger.py

````python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
import re

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
        path.parent.mkdir(parents=True, exist_ok=True)
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
    platform: str = "whatsapp",
    **extra,
) -> dict:
    item = {
        "id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": platform,
        **extra,
        "account": account,
        "contact": contact,
        "event": event,
        "status": status,
        "message_id": message_id,
        "message_preview": message_preview,
        "message": message_preview,
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
    platform: str = "whatsapp",
    **extra,
) -> dict:
    item = {
        "id": str(uuid4()),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": platform,
        **extra,
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
        "error": re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED]", str(error)),
    }
    _append(ERRORS_FILE, item)
    return item
````

## screenshot_manager.py

````python
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
````

## session_manager.py

````python
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import json
from pathlib import Path

from config import SESSIONS_DIR


def safe_session_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(" ._")
    value = value or "whatsapp_account"
    if value.upper().split('.')[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "account_" + value
    return value


def session_dir(account_name: str) -> Path:
    path = SESSIONS_DIR / safe_session_name(account_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def has_session_snapshot(account_name: str) -> bool:
    root = session_dir(account_name)
    return (root / "Local State").exists() or (root / "Default").exists()


def create_temp_profile(account_name: str) -> Path:
    """
    Create a disposable Chrome profile and restore only the lightweight
    WhatsApp/session-related snapshot if one exists.
    """
    temp_root = Path(
        tempfile.mkdtemp(prefix=f"wa_{safe_session_name(account_name)}_")
    )

    restore_session_snapshot(account_name, temp_root)
    return temp_root


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_dir(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(
        "Cache", "CacheStorage", "Code Cache", "GPUCache", "Media Cache", "ScriptCache"))


def restore_session_snapshot(account_name: str, temp_root: Path) -> None:
    """
    Restore only session-relevant Chrome files.

    We deliberately do NOT restore Cache, Code Cache, GPUCache, history,
    downloads, media cache, crash reports, etc.
    """
    saved = session_dir(account_name)

    # Root-level encryption/material metadata used by Chromium.
    _copy_file(saved / "Local State", temp_root / "Local State")

    saved_default = saved / "Default"
    temp_default = temp_root / "Default"
    temp_default.mkdir(parents=True, exist_ok=True)

    # Small profile metadata that can help Chrome reopen storage correctly.
    for filename in (
        "Preferences",
        "Secure Preferences",
    ):
        _copy_file(saved_default / filename, temp_default / filename)

    # WhatsApp/session-relevant storage only.
    for dirname in (
        "IndexedDB",
        "Local Storage",
        "Session Storage",
        "Service Worker",
        "WebStorage",
        "Storage",
    ):
        _copy_dir(saved_default / dirname, temp_default / dirname)

    # Cookie DB (plus journal) lives in Network/.
    for filename in (
        "Cookies",
        "Cookies-journal",
    ):
        _copy_file(
            saved_default / "Network" / filename,
            temp_default / "Network" / filename,
        )


def save_session_snapshot(account_name: str, temp_root: Path, accounts: dict | None = None) -> Path:
    """
    Save only lightweight session data after Chrome has been closed.

    The destination is replaced atomically-ish via a staging directory so
    stale IndexedDB files from an older session do not accumulate forever.
    """
    target = session_dir(account_name)
    staging = target.with_name(target.name + ".__new__")

    if staging.exists():
        _remove_session_tree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    if accounts is not None:
        (staging / 'accounts.json').write_text(json.dumps(accounts), encoding='utf-8')

    # Root metadata.
    _copy_file(temp_root / "Local State", staging / "Local State")

    src_default = temp_root / "Default"
    dst_default = staging / "Default"
    dst_default.mkdir(parents=True, exist_ok=True)

    for filename in (
        "Preferences",
        "Secure Preferences",
    ):
        _copy_file(src_default / filename, dst_default / filename)

    for dirname in (
        "IndexedDB",
        "Local Storage",
        "Session Storage",
        "Service Worker",
        "WebStorage",
        "Storage",
    ):
        _copy_dir(src_default / dirname, dst_default / dirname)

    for filename in (
        "Cookies",
        "Cookies-journal",
    ):
        _copy_file(
            src_default / "Network" / filename,
            dst_default / "Network" / filename,
        )

    # Replace previous snapshot.
    old = target.with_name(target.name + ".__old__")
    if old.exists():
        _remove_session_tree(old)

    # target currently exists because session_dir() creates it.
    # Move the old one aside first.
    if target.exists():
        try:
            target.rename(old)
        except OSError:
            raise RuntimeError("Could not preserve previous session; snapshot not replaced")

    try:
        staging.rename(target)
    except OSError:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    _remove_session_tree(old)

    return target


def cleanup_temp_profile(temp_root: Path | None) -> None:
    if temp_root is None:
        return

    temp_root = Path(temp_root).resolve()
    expected_root = Path(tempfile.gettempdir()).resolve()
    if temp_root.parent != expected_root or not temp_root.name.startswith("wa_"):
        raise ValueError("Refusing cleanup outside the disposable profile directory")

    # Chrome may need a tiny moment to release SQLite/LevelDB file handles.
    for attempt in range(6):
        try:
            shutil.rmtree(temp_root)
            return
        except Exception:
            time.sleep(0.35)

    shutil.rmtree(temp_root, ignore_errors=True)


def delete_session_snapshot(account_name: str) -> None:
    _remove_session_tree(SESSIONS_DIR / safe_session_name(account_name))


def _remove_session_tree(path: Path) -> None:
    resolved = path.resolve()
    root = SESSIONS_DIR.resolve()
    if resolved.parent != root:
        raise ValueError("Refusing removal outside sessions directory")
    shutil.rmtree(resolved, ignore_errors=True)
````

## requirements.txt

````text
selenium>=4.25,<5
questionary>=2.1,<3
requests>=2.32,<3
python-dotenv>=1.0,<2
winotify>=1.1,<2
````

## .env.example

````text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_CONTROL=true
CHECK_INTERVAL=2
LOGIN_TIMEOUT=180
PRESENCE_CONFIRMATIONS=2
PRESENCE_CHECK_DELAY=0.3
SEND_SCREENSHOT_TO_TELEGRAM=true
WINDOWS_NOTIFICATIONS=true
CHROME_HEADLESS=false
````

## .gitignore

````text
# =========================
# Python
# =========================
__pycache__/
*.py[cod]
*.pyo
*.pyd

# Virtual environments
.venv/
venv/
env/

# =========================
# Secrets / Environment
# =========================
.env
!.env.example

# =========================
# WhatsApp private accounts
# =========================
accounts/
sessions/

# =========================
# Private runtime data
# =========================
screenshots/
data/

# =========================
# IDE / OS
# =========================
.vscode/
.idea/
.DS_Store
Thumbs.db

# =========================
# Logs / temp files
# =========================
*.log
*.tmp
*.bak
````

## README.md

````markdown
# Social Watcher

Extension of the existing WhatsApp project: one temporary Chrome profile, one driver,
two tabs and one Selenium worker. Terminal and Telegram submit queued commands.
The existing cookie, lightweight session, DOM, screenshot and notification helpers
are reused. No permanent full Chrome profile is introduced.

## Running

Python 3.10+, Google Chrome and the existing requirements are needed.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Preserve your existing `.env`. On first installation only, copy `.env.example` to
`.env`. Configure TELEGRAM_BOT_TOKEN and a positive private TELEGRAM_CHAT_ID.
Only that private chat and sender can control the application. No webhook is used.
If your bot already has a webhook, remove it before using long polling.
Run only one application process for this workspace and bot at a time.

## First use and controls

The last account labels are restored from data/active_accounts.json. Initially,
the first saved WhatsApp account and instagram_main are selected. Use Accounts to
select a saved account or add a local label. Log in inside Chrome when needed,
then choose Save session cookies. Open a chat or DM yourself in the appropriate tab.
Account labels are local names, not verified identity claims.

Terminal includes WhatsApp, Instagram, Status All, Refresh All, Screenshots,
Watchers, Accounts, Logs, Presence History, Settings, Telegram Control and Exit.
Telegram supports /start /menu /status /whatsapp /instagram /refresh /screenshot
/watch /stop /accounts /logs /help, with inline menus and Back buttons.
Callback menus edit the existing message. Adding a new account label is local;
selecting saved accounts is available remotely. Settings displays effective values;
edit .env and restart to change settings. Stop stops message watchers only.

Status reads the current chat/message but displays presence from the last manual
Refresh, including its timestamp. Screenshots captures both tabs; Telegram sends
the images. Logs shows 10 recent events; Presence History shows 50 transitions.
Telegram Control locally starts/stops the bot controller or tests notifications.

## Presence and messages

Presence is read only on explicit Refresh. A bounded series requires
PRESENCE_CONFIRMATIONS consecutive matching readings, separated by
PRESENCE_CHECK_DELAY. A changed chat cancels the refresh. Confirmed online to
missing produces unavailable; missing after offline is silent. Transient missing
and repeated online readings produce no duplicate notification. Unknown WhatsApp
subtitles such as typing do not overwrite confirmed presence. Instagram activity
also uses manual refresh only. State is isolated by platform/account/contact.

Message checks run every CHECK_INTERVAL (minimum one second). They track the
latest rendered outgoing message in each open conversation, not all history.
The first message establishes a baseline; new messages and increasing statuses
produce events. Unknown/decreasing states do not reset progress. Message IDs
prevent duplicate events. WhatsApp supports Sent/Delivered/Read; Instagram supports
Sent/Seen when the UI exposes explicit authorship, a stable ID and receipt evidence.

Instagram has no stable public DOM contract. The reader uses conversation headers,
profile links, semantic message rows and explicit outgoing labels. Unknown layouts
return Unavailable instead of guessing. Activity/receipt recognition currently
targets English UI labels. Real account validation is still needed; fixture tests
cannot establish compatibility with every Instagram version or localization.

Existing WhatsApp public reader/watcher names remain available.
watch_chat_combined and watch_last_outgoing_message now perform one message tick;
PlatformManager owns scheduling, avoiding competing Selenium loops.

## Lightweight sessions

Legacy accounts/*.pkl and sessions/<account>/ remain compatible and are not deleted.
Instagram cookies use accounts/instagram/<label>.pkl. The temporary profile contains
both domains; each selected account pair has sessions/social_<pair-hash>/.
Legacy WhatsApp snapshots seed a new pair. Both sessions are saved after Chrome
closes and the same pair is restored next launch.
When creating another pair with the same WhatsApp account, its newest saved pair
can seed the profile; Instagram origin data is cleared before restoring the chosen
Instagram account. This preserves WhatsApp IndexedDB without mixing databases.

Account selection closes/saves Chrome before opening its replacement with two tabs.
Two drivers are never active together. No LevelDB databases from separate profiles
are merged. A previously unused pair may need an initial login; a valid saved pair
is reused on subsequent launches. Cookies remain a fallback, not the sole source
of WhatsApp authentication.

Snapshots retain IndexedDB, Local Storage, Session Storage, Service Worker database,
WebStorage/Storage, cookies, Local State and small profile preferences. Cache,
CacheStorage, ScriptCache, Code Cache, GPUCache, media cache, History and Downloads
are excluded. Save session cookies updates .pkl on demand. Full lightweight snapshots
are saved only on clean Exit/account switch. Abrupt process termination may lose
changes since the last snapshot. A failed snapshot leaves the temporary profile
available for recovery, with its path in errors.json. Encrypted session material
can be tied to this Windows account and machine.

## Events, notifications and privacy

Existing data/events.json, data/errors.json and data/presence_history.json remain.
New events include platform. Presence entries use event=presence_changed with
previous_status/current_status. Message entries include message, message_preview,
message_id and status. Error strings redact Telegram bot-token URLs.

Screenshots use screenshots/<platform>/<account>/ for Delivered, Read, Seen,
confirmed Online/Offline and explicit screenshot commands. Sent has no automatic
screenshot. Telegram and Windows notifications show platform/contact/account/time
and message or previous/current presence. A platform failure is isolated, and
repeated errors are rate-limited. Notification networking runs outside Selenium.

The original .gitignore is unchanged: .env, accounts/, sessions/, screenshots/,
data/ and __pycache__/ stay ignored. .env.example contains no real credentials.
Never load untrusted pickle files. Presence/message tracking is in memory; restarting
establishes new message baselines.

## Verification and complete source

```powershell
python -m unittest discover -s tests -v
# Include real Chrome tests against local synthetic HTML, never account data:
$env:SOCIAL_BROWSER_TESTS='1'
python -m unittest discover -s tests -v
```

Tests cover debounce, deduplication, account/chat separation, chat switching,
manual-only presence, single-worker ownership, platform error isolation, Telegram
authorization/callback queueing, session cache filtering and DOM fixtures.
Live account login/restore, real Instagram variants and actual Telegram delivery
still require verification with your configured accounts. Implementation testing
did not send messages to real Telegram chats or read your saved session contents.

FULL_CODE.md contains complete files for copy/paste. Social-Watcher-source.zip
contains source, example configuration and tests only, without private runtime data.

References: [Telegram Bot API](https://core.telegram.org/bots/api#getupdates),
[Selenium tabs](https://www.selenium.dev/documentation/webdriver/interactions/windows/).
````

## tests/test_social_watcher.py

````python
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import get_ident
from unittest.mock import patch, Mock
from tempfile import TemporaryDirectory
from pathlib import Path
import time

import config
import platform_manager as pm
from whatsapp_watcher import MessageSnapshot
from telegram_controller import TelegramController


class TrackingTests(unittest.TestCase):
    def test_message_dedup_regression_and_new_message(self):
        tracker = pm.MessageTracker()
        events = []
        for mid, state in [('a', 'sent'), ('a', 'read'), ('a', 'sent'),
                           ('a', 'read'), ('b', 'sent'), ('b', 'seen')]:
            tracker.observe('instagram', 'me', '@user', MessageSnapshot(mid, state, 'hello'),
                            lambda s: events.append((s.message_id, s.status)))
        self.assertEqual(events, [('a', 'read'), ('b', 'sent'), ('b', 'seen')])

    def test_chat_and_account_baselines_are_independent(self):
        tracker = pm.MessageTracker()
        emit = Mock()
        for account, contact in [('a', 'one'), ('a', 'two'), ('b', 'one')]:
            tracker.observe('whatsapp', account, contact, MessageSnapshot('1', 'read', ''), emit)
        emit.assert_not_called()

    def presence_manager(self, initial):
        manager = pm.PlatformManager.__new__(pm.PlatformManager)
        manager.active = {'whatsapp': 'me'}
        manager.driver = object()
        manager.cache = {'whatsapp': {}}
        manager.presence = {('whatsapp', 'me', 'Papa'): initial}
        manager._emit = Mock()
        return manager

    def refresh(self, manager, values):
        with patch.object(pm.whatsapp, 'get_current_chat_name', return_value='Papa'), \
             patch.object(pm.whatsapp, 'get_current_chat_presence', side_effect=values), \
             patch.object(config, 'PRESENCE_CONFIRMATIONS', 2), \
             patch.object(config, 'PRESENCE_CHECK_DELAY', 0):
            manager._refresh_presence('whatsapp', 'Papa')

    def test_transient_invisibility_is_not_offline(self):
        manager = self.presence_manager('online')
        self.refresh(manager, [None, 'online', 'online'])
        manager._emit.assert_not_called()

    def test_confirmed_invisibility_after_online_once(self):
        manager = self.presence_manager('online')
        self.refresh(manager, [None, ''])
        self.refresh(manager, [None, None])
        manager._emit.assert_called_once_with('whatsapp', 'Papa', 'unavailable', previous='online')

    def test_invisible_after_offline_is_silent(self):
        manager = self.presence_manager('last seen today at 20:08')
        self.refresh(manager, [None, None])
        manager._emit.assert_not_called()

    def test_online_and_offline_confirmations(self):
        manager = self.presence_manager('last seen today at 20:08')
        self.refresh(manager, ['online', 'online'])
        self.refresh(manager, ['online', 'online'])
        self.refresh(manager, ['last seen today at 20:09'] * 2)
        self.assertEqual([c.args[2] for c in manager._emit.call_args_list], ['online', 'offline'])

    def test_switch_during_refresh_aborts(self):
        manager = self.presence_manager('online')
        with patch.object(pm.whatsapp, 'get_current_chat_name', side_effect=['Papa', 'Other']), \
             patch.object(pm.whatsapp, 'get_current_chat_presence', return_value=None):
            with self.assertRaises(RuntimeError):
                manager._refresh_presence('whatsapp', 'Papa')
        manager._emit.assert_not_called()

    def test_message_tick_never_reads_presence(self):
        manager = self.presence_manager('online')
        manager._switch = Mock()
        manager.watching = {'whatsapp': True}
        manager.messages = pm.MessageTracker()
        with patch.object(pm.whatsapp, 'is_logged_in', return_value=True), \
             patch.object(pm.whatsapp, 'get_current_chat_name', return_value='Papa'), \
             patch.object(pm.whatsapp, 'get_last_outgoing_message', return_value=None), \
             patch.object(pm.whatsapp, 'get_current_chat_presence') as presence:
            manager._read('whatsapp', watch=True)
        presence.assert_not_called()

    def test_platform_failure_does_not_block_other_platform(self):
        manager = pm.PlatformManager.__new__(pm.PlatformManager)
        manager.cache = {'whatsapp': {}, 'instagram': {}}
        manager.error_times = {}
        manager._read = Mock(side_effect=[RuntimeError('DOM changed'), {'contact': '@user'}])
        with patch.object(pm, 'log_error'):
            result = manager._execute('refresh', 'all', {})
        self.assertIn('error', result['whatsapp'])
        self.assertEqual(result['instagram']['contact'], '@user')

    def test_telegram_auth_private_owner_only(self):
        controller = TelegramController(Mock())
        with patch.object(config, 'TELEGRAM_CHAT_ID', '123'):
            message = {'chat': {'id': 123, 'type': 'private'}, 'from': {'id': 123}}
            self.assertTrue(controller._authorized({'message': message}))
            message['from']['id'] = 456
            self.assertFalse(controller._authorized({'message': message}))
            message['from']['id'] = 123
            message['chat']['type'] = 'group'
            self.assertFalse(controller._authorized({'message': message}))

    def test_one_worker_for_concurrent_ui_commands(self):
        ids = []
        class FakeManager(pm.PlatformManager):
            def _open(self):
                ids.append(get_ident())
            def _execute(self, action, platform, kwargs):
                ids.append(get_ident())
                return action
            def _close_browser(self):
                ids.append(get_ident())
        with TemporaryDirectory() as temp, patch.object(config, 'DATA_DIR', Path(temp)), \
             patch.object(config, 'ensure_directories'), patch.object(pm, 'list_accounts', return_value=[]):
            manager = FakeManager()
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: manager.call('status'), range(30)))
                self.assertEqual(results, ['status'] * 30)
            finally:
                manager.close()
        self.assertEqual(len(set(ids)), 1)
        self.assertNotEqual(ids[0], get_ident())

    def test_telegram_callback_queues_refresh_and_edits_menu(self):
        from concurrent.futures import Future
        manager = Mock()
        future = Future()
        future.set_result({'whatsapp': {'contact': 'Papa', 'presence': 'online'}})
        manager.submit.return_value = future
        controller = TelegramController(manager)
        controller._api = Mock()
        with patch.object(config, 'TELEGRAM_CHAT_ID', '123'):
            controller._handle({'callback_query': {'id': 'q', 'data': 'refresh:whatsapp',
                'from': {'id': 123}, 'message': {'message_id': 9,
                'chat': {'id': 123, 'type': 'private'}}}})
            controller._complete()
        manager.submit.assert_called_once_with('refresh', 'whatsapp')
        self.assertEqual(controller._api.call_args_list[0].args, ('answerCallbackQuery',))
        self.assertEqual(controller._api.call_args_list[-1].args, ('editMessageText',))

    def test_snapshot_excludes_cache_and_restores_storage(self):
        import session_manager as sm
        with TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / 'profile'
            default = profile / 'Default'
            for relative in ['IndexedDB/db/value', 'Local Storage/leveldb/value',
                             'Service Worker/Database/value', 'Service Worker/CacheStorage/value',
                             'Cache/value', 'GPUCache/value']:
                path = default / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            (profile / 'Local State').write_text('{}')
            with patch.object(sm, 'SESSIONS_DIR', root / 'sessions'):
                saved = sm.save_session_snapshot('pair', profile)
                self.assertTrue((saved / 'Default/IndexedDB/db/value').exists())
                self.assertFalse((saved / 'Default/Service Worker/CacheStorage').exists())
                self.assertFalse((saved / 'Default/Cache').exists())
                sm.restore_session_snapshot('pair', root / 'restored')
                self.assertTrue((root / 'restored/Default/Local Storage/leveldb/value').exists())


if __name__ == '__main__':
    unittest.main()
````

## tests/test_dom.py

````python
"""Opt-in real Chrome checks against local HTML fixtures, never user accounts."""
import os
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import whatsapp_watcher as wa
import instagram_watcher as ig

HTML = b'''<html><body>
<div id="side"></div><div id="main"><header>
<span data-testid="chat-subtitle">online</span>
<span data-testid="conversation-info-header-chat-title">Papa</span>
</header></div>
<a href="/direct/inbox/">Inbox</a>
<main><header><a href="/username/">User Name</a><h2>Username</h2>
<span>Active now</span></header>
<div role="row" data-message-id="msg-42" aria-label="You sent hello">
<div>hello</div><span>Seen</span></div>
<div role="textbox" contenteditable="true"></div></main>
</body></html>'''


@unittest.skipUnless(os.getenv('SOCIAL_BROWSER_TESTS') == '1', 'Opt-in Chrome fixture tests')
class DOMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(HTML)
            def log_message(self, *_):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.get(f'http://127.0.0.1:{cls.server.server_port}/direct/t/1/')

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def test_whatsapp_contact_separate_from_subtitle(self):
        self.assertEqual(wa.get_current_chat_name(self.driver), 'Papa')
        self.assertEqual(wa.get_current_chat_presence(self.driver, attempts=1), 'online')

    def test_instagram_header_and_seen(self):
        self.assertEqual(ig.get_current_chat_name(self.driver), '@username')
        self.assertEqual(ig.get_current_chat_presence(self.driver), 'Active now')
        snapshot = ig.get_last_outgoing_message(self.driver)
        self.assertEqual((snapshot.message_id, snapshot.status, snapshot.text), ('msg-42', 'seen', 'hello'))


if __name__ == '__main__':
    unittest.main()
````
