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
