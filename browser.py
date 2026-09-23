from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from config import CHROME_HEADLESS
from session_manager import create_temp_profile


def create_driver(account_name: str):
    """
    Lightweight Chrome:
      - disposable temp user-data-dir for this run
      - restores only a small WhatsApp session snapshot
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

    # Attach path so main.py can snapshot it AFTER driver.quit().
    driver._wa_temp_profile = temp_profile
    return driver
