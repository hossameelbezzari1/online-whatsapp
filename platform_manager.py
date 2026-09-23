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
