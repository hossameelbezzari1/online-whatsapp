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
