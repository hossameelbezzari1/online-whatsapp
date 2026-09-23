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
