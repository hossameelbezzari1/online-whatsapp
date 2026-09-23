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
