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
