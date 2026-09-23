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
