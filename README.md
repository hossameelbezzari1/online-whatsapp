# WhatsApp Watcher

A local Python + Selenium tool for monitoring a WhatsApp Web chat and sending
notifications when useful events are detected.

The app currently supports:

- multiple saved WhatsApp accounts
- lightweight WhatsApp session restore from `sessions/`
- Telegram notifications
- Windows toast notifications
- screenshots for notification events
- JSON event logs
- JSON presence history per contact
- latest outgoing message status monitoring (`delivered`, `read`)
- chat presence monitoring (`online`, `last seen ...`, unavailable)

## Project Structure

```text
online-whatsapp/
  account_manager.py       # account cookie save/load/delete helpers
  browser.py               # Chrome/Selenium driver setup
  config.py                # environment variables and runtime paths
  event_logger.py          # JSON event/error/presence history logging
  main.py                  # CLI menus and app entry point
  notifier.py              # Telegram and Windows notifications
  screenshot_manager.py    # screenshot file creation
  session_manager.py       # lightweight WhatsApp session snapshots
  whatsapp_watcher.py      # WhatsApp DOM readers and watcher logic
  requirements.txt
  .env.example
  .gitignore

  accounts/                # private local account cookie files, ignored by Git
  data/                    # private local JSON logs, ignored by Git
  screenshots/             # private local screenshots, ignored by Git
  sessions/                # private local WhatsApp session snapshots, ignored by Git
```

Do not commit `accounts/`, `data/`, `screenshots/`, `sessions/`, or `.env`.
They may contain private account data, chat names, screenshots, tokens, or
runtime history.

## Requirements

- Python 3.10+
- Google Chrome
- Windows if you want native toast notifications

Selenium Manager can usually resolve ChromeDriver automatically.

## Installation

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Configure `.env` with your own private values:

```env
TELEGRAM_BOT_TOKEN=replace-with-your-bot-token
TELEGRAM_CHAT_ID=replace-with-your-chat-id

CHECK_INTERVAL=2
PRESENCE_CHECK_INTERVAL=0.25
LOGIN_TIMEOUT=180

SEND_SCREENSHOT_TO_TELEGRAM=true
WINDOWS_NOTIFICATIONS=true
CHROME_HEADLESS=false
```

Telegram setup:

1. Create a Telegram bot with `@BotFather`.
2. Put the bot token in `TELEGRAM_BOT_TOKEN`.
3. Send one message to your bot.
4. Get your private chat ID and put it in `TELEGRAM_CHAT_ID`.

Never commit `.env`.

## Running

```powershell
python main.py
```

Main menu actions:

- use a saved WhatsApp account
- add a new WhatsApp account
- show presence history
- test Telegram and Windows notifications
- delete a saved account
- quit

When adding an account, Chrome opens WhatsApp Web. Scan the QR code once. The
app saves local account/session data so the account can usually be reused later
without scanning again.

## Watch Mode

Open a WhatsApp chat in the Chrome window, then choose:

```text
Surveiller le chat + statut ONLINE
```

Inside watch mode:

- latest outgoing message status is monitored automatically
- `delivered` and `read` transitions send notifications
- chat presence is monitored automatically
- press `R` to print the currently visible chat status
- press `Q` to return to the account menu

## Presence Logic

Presence status is read from the current WhatsApp chat subtitle. The watcher
separates the chat/contact name from the presence text so the contact name stays
stable.

Handled presence values include:

- `online`
- `last seen today at HH:MM`
- `last seen yesterday at HH:MM`
- other `last seen ...` values
- `Not visible`
- empty or missing values

To reduce false notifications from temporary WhatsApp DOM changes, a new
presence state must appear at least twice in a row before the app accepts it.

Notification behavior:

- confirmed non-online/unavailable to `online` sends one `online` event
- confirmed `online` to `last seen ...` sends one `offline` event
- confirmed `online` to `Not visible` sends one `unavailable` event
- `Not visible` before a confirmed online state is ignored for notifications
- repeated unchanged status does not create duplicate notifications

## Message Status Logic

The app tracks the latest outgoing message in the open chat.

Notifications are sent when the latest outgoing message progresses to:

- `delivered`
- `read`

The first detected message status is used as a baseline, so starting the watcher
does not immediately send a duplicate event for an already delivered/read
message.

## Runtime Data

Runtime files are local and ignored by Git:

```text
accounts/
  <account-name>.pkl

sessions/
  <account-name>/
    Local State
    Default/
      IndexedDB/
      Local Storage/
      Session Storage/
      Service Worker/
      Network/

data/
  events.json
  errors.json
  presence_history.json

screenshots/
  <account-name>/
    <event-screenshot>.png
```

`presence_history.json` entries include:

```json
{
  "id": "generated-id",
  "timestamp": "generated-timestamp",
  "account": "account-name",
  "contact": "chat-name",
  "previous_status": "previous status",
  "current_status": "current status",
  "event": "online|offline|unavailable",
  "screenshot": "optional screenshot path"
}
```

## GitHub Safety Checklist

Before publishing the project:

1. Confirm `.env` is not committed.
2. Confirm `accounts/` is not committed.
3. Confirm `sessions/` is not committed.
4. Confirm `screenshots/` is not committed.
5. Confirm `data/` is not committed.
6. Review README examples and screenshots for private names, phone numbers, or
   tokens.

The included `.gitignore` already excludes the private runtime folders and
`.env`.

## Security Notes

- `.pkl` files are private. Do not load pickle files from untrusted sources.
- WhatsApp Web is not a stable public Selenium API. Selectors can break after a
  WhatsApp update.
- Use automation only with accounts and chats you are authorized to access.
- Telegram bot tokens and chat IDs are secrets.
