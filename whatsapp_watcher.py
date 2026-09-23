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
    attempts: int = 10,
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
            """
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
                if (node.closest("[data-testid='chat-subtitle']")) continue;
                const value = (node.getAttribute("title")
                  || node.innerText
                  || node.textContent
                  || "").trim();
                if (value) return value;
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
                        "قرئت",
                        "مقروء",
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
        screenshot_path = take_screenshot(
            driver,
            account=account,
            contact=contact,
            event=event,
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


def watch_chat_combined(
    driver: Chrome,
    *,
    account: str,
    contact: str,
) -> None:
    """
    Combined mode:
      - Automatically watches the latest outgoing message for Delivered/Read.
      - ONLINE/last-seen is checked ONLY when the user presses R.
      - Q returns to the account menu.

    On Windows, msvcrt is used so keyboard input does not block message-status
    monitoring.
    """
    print()
    print("=" * 64)
    print(f"[WATCHING] Account : {account}")
    print(f"[WATCHING] Contact : {contact}")
    print("[AUTO] Delivered / Read monitoring is active.")
    print("[AUTO] Chat subtitle changes are sent to Telegram.")
    print("[MANUAL] Press R = refresh ONLINE / last seen")
    print("[EXIT]   Press Q = return to menu")
    print("=" * 64)
    print()

    previous_message: MessageSnapshot | None = None
    confirmed_presence: PresenceState | None = None
    pending_presence: PresenceState | None = None
    pending_presence_count = 0
    next_message_check = 0.0
    next_presence_check = 0.0

    # Windows keyboard polling without blocking Selenium checks.
    if os.name == "nt":
        import msvcrt
    else:
        msvcrt = None

    while True:
        try:
            now = time.monotonic()

            # Automatic monitoring of the user's latest outgoing message.
            if now >= next_message_check:
                current = get_last_outgoing_message(driver)

                if current is not None:
                    if previous_message is None:
                        previous_message = current
                        print(
                            f"[MESSAGE BASELINE] status={current.status} "
                            f"id={current.message_id or 'n/a'}"
                        )

                    elif (
                        current.message_id
                        and previous_message.message_id
                        and current.message_id != previous_message.message_id
                    ):
                        previous_message = current
                        print(
                            f"[NEW MESSAGE] tracking latest outgoing message "
                            f"(status={current.status})"
                        )

                    else:
                        old_rank = _event_rank(previous_message.status)
                        new_rank = _event_rank(current.status)

                        if new_rank > old_rank:
                            if current.status in {"delivered", "read"}:
                                print(
                                    f"[MESSAGE EVENT] "
                                    f"{previous_message.status} -> {current.status}"
                                )
                                _notify_transition(
                                    driver,
                                    account=account,
                                    contact=contact,
                                    snapshot=current,
                                    event=current.status,
                                )

                            previous_message = current

                        elif current.status != previous_message.status:
                            if current.status != "unknown":
                                previous_message = current

                next_message_check = now + CHECK_INTERVAL

            # Automatic monitoring of the chat subtitle:
            # #main [data-testid='chat-subtitle'] span[data-testid='selectable-text']
            if now >= next_presence_check:
                try:
                    contact_name = get_current_chat_name(driver) or contact
                    presence = get_current_chat_presence(
                        driver,
                        attempts=1,
                        delay=0,
                    )
                except Exception as exc:
                    log_error("combined_presence_auto_check", exc)
                    contact_name = contact
                    presence = None

                contact = contact_name
                current_presence = _normalize_presence(presence)

                if current_presence.key != "unknown":
                    same_pending = (
                        pending_presence is not None
                        and pending_presence.key == current_presence.key
                    )

                    if same_pending:
                        pending_presence = current_presence
                        pending_presence_count += 1
                    else:
                        pending_presence = current_presence
                        pending_presence_count = 1

                    if pending_presence_count >= 2:
                        stable_presence = pending_presence

                        if confirmed_presence is None:
                            confirmed_presence = stable_presence
                            print(f"[STATUS BASELINE] {stable_presence.label}")

                        elif stable_presence.key == confirmed_presence.key:
                            confirmed_presence = stable_presence

                        elif (
                            confirmed_presence.key == "online"
                            and stable_presence.key == "offline"
                        ):
                            previous_status = confirmed_presence.label
                            confirmed_presence = stable_presence
                            print(
                                f"[STATUS EVENT] {previous_status} -> "
                                f"{stable_presence.label}"
                            )
                            _notify_presence_change(
                                driver,
                                account=account,
                                contact=contact_name,
                                previous_status=previous_status,
                                current_status=stable_presence.label,
                                event="offline",
                            )

                        elif (
                            confirmed_presence.key == "online"
                            and stable_presence.key == "not_visible"
                        ):
                            previous_status = confirmed_presence.label
                            confirmed_presence = stable_presence
                            print(
                                f"[STATUS EVENT] {previous_status} -> "
                                f"{stable_presence.label}"
                            )
                            _notify_presence_change(
                                driver,
                                account=account,
                                contact=contact_name,
                                previous_status=previous_status,
                                current_status=stable_presence.label,
                                event="unavailable",
                            )

                        elif (
                            confirmed_presence.key != "online"
                            and stable_presence.key == "online"
                        ):
                            previous_status = confirmed_presence.label
                            confirmed_presence = stable_presence
                            print(
                                f"[STATUS EVENT] {previous_status} -> "
                                f"{stable_presence.label}"
                            )
                            _notify_presence_change(
                                driver,
                                account=account,
                                contact=contact_name,
                                previous_status=previous_status,
                                current_status=stable_presence.label,
                                event="online",
                            )

                        elif stable_presence.key != "not_visible":
                            confirmed_presence = stable_presence

                next_presence_check = now + PRESENCE_CHECK_INTERVAL

            # Manual presence/status refresh.
            key = None

            if msvcrt is not None and msvcrt.kbhit():
                key = msvcrt.getwch().lower()

            if key == "q":
                print("\n[STOPPED] Retour au menu.")
                return

            if key == "r":
                try:
                    contact_name = get_current_chat_name(driver) or contact
                    presence = get_current_chat_presence(driver)
                except Exception as exc:
                    log_error("combined_presence_refresh", exc)
                    presence = None
                    contact_name = contact

                contact = contact_name
                current_presence = _normalize_presence(presence)

                print()
                print("-" * 64)
                print(f"[STATUS] Chat   : {contact_name}")
                print(f"[STATUS] Actuel : {current_presence.label}")
                print("-" * 64)

                if current_presence.key == "online":
                    print("[STATUS] ONLINE detecte. Confirmation automatique active.")
                elif current_presence.key == "not_visible":
                    print("[STATUS] Not visible - ignore sauf confirmation apres ONLINE.")
                else:
                    print("[STATUS] Pas ONLINE pour le moment.")

                print()
                print("[MANUAL] R = refresh status | Q = retour")

            # Non-Windows fallback: keep behavior safe and explicit.
            if msvcrt is None:
                time.sleep(min(PRESENCE_CHECK_INTERVAL, 0.25))
            else:
                time.sleep(min(PRESENCE_CHECK_INTERVAL, 0.10))

        except KeyboardInterrupt:
            print("\n[STOPPED] Retour au menu.")
            return
        except StaleElementReferenceException:
            time.sleep(0.25)
        except WebDriverException as exc:
            log_error("combined_watcher_webdriver", exc)
            print(f"\n[WebDriver error] {exc}")
            return
        except Exception as exc:
            log_error("combined_watcher_loop", exc)
            print(f"\n[Watcher error] {exc}")
            time.sleep(0.5)

def watch_last_outgoing_message(
    driver: Chrome,
    *,
    account: str,
    contact: str,
) -> None:
    print()
    print(f"[WATCHING] Account: {account}")
    print(f"[WATCHING] Contact: {contact}")

    try:
        presence = get_current_chat_presence(driver)
    except Exception:
        presence = None

    if presence:
        print(f"[CURRENT STATUS] {presence}")
    else:
        print("[CURRENT STATUS] Not visible")

    print("[WATCHING] Press CTRL+C to stop and return to menu.")
    print()

    previous: MessageSnapshot | None = None

    while True:
        try:
            if not is_logged_in(driver):
                print("[!] WhatsApp session is no longer logged in.")
                return

            current = get_last_outgoing_message(driver)

            if current is None:
                print("\r[WAIT] No outgoing message found in this chat...", end="")
                time.sleep(CHECK_INTERVAL)
                continue

            if previous is None:
                previous = current
                print(
                    f"[BASELINE] status={current.status} "
                    f"id={current.message_id or 'n/a'}"
                )
                time.sleep(CHECK_INTERVAL)
                continue

            # User sent a new outgoing message while the watcher was running.
            if (
                current.message_id
                and previous.message_id
                and current.message_id != previous.message_id
            ):
                previous = current
                print(
                    f"[NEW MESSAGE] tracking latest outgoing message "
                    f"(status={current.status})"
                )
                time.sleep(CHECK_INTERVAL)
                continue

            old_rank = _event_rank(previous.status)
            new_rank = _event_rank(current.status)

            if new_rank > old_rank:
                # Notify only for useful delivery/read transitions.
                if current.status in {"delivered", "read"}:
                    print(f"[EVENT] {previous.status} -> {current.status}")
                    _notify_transition(
                        driver,
                        account=account,
                        contact=contact,
                        snapshot=current,
                        event=current.status,
                    )

                previous = current

            elif current.status != previous.status:
                # DOM glitches can briefly report "unknown"; keep the last
                # reliable state instead of generating duplicate events.
                if current.status != "unknown":
                    previous = current

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\n[STOPPED] Watcher stopped.")
            return
        except StaleElementReferenceException:
            time.sleep(0.5)
        except WebDriverException as exc:
            log_error("watcher_webdriver", exc)
            print(f"\n[WebDriver error] {exc}")
            return
        except Exception as exc:
            log_error("watcher_loop", exc)
            print(f"\n[Watcher error] {exc}")
            time.sleep(max(CHECK_INTERVAL, 1))
