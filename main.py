"""Local UI; Selenium belongs exclusively to PlatformManager."""
import questionary
from questionary import Choice
import config
from platform_manager import PlatformManager
from telegram_controller import TelegramController, format_result
from notifier import test_notifications


def choose(title, items):
    return questionary.select(title, choices=[Choice(label, value) for label, value in items]).ask()


def show(manager, action, platform='all', **kwargs):
    try:
        print(format_result(manager.call(action, platform, **kwargs)))
    except Exception as exc:
        print(str(exc))


def platform_menu(manager, platform):
    show(manager, 'focus', platform)
    while True:
        action = choose(platform.title(), [
            ('Current Chat / DM', 'status'), ('Current Status (cached presence)', 'status'),
            ('Refresh Status', 'refresh'), ('Message Status', 'status'),
            ('Screenshot', 'screenshot'), ('Start Watch', 'watch'), ('Stop Watch', 'stop'),
            ('Save session cookies', 'save'), ('Back', 'back')])
        if action in {None, 'back'}:
            return
        show(manager, action, platform)


def accounts_menu(manager):
    while True:
        accounts = manager.call('accounts')
        print(format_result(accounts))
        items = [(f'{p}: {name}', (p, name)) for p, row in accounts.items() for name in row['saved']]
        selection = choose('Accounts', items + [('Add account', 'add'), ('Delete saved account', 'delete'), ('Back', 'back')])
        if selection in {None, 'back'}:
            return
        if selection == 'delete':
            target = choose('Delete saved account', items + [('Back', None)])
            if target and questionary.confirm(f'Delete {target[0]} account {target[1]} and its saved sessions?', default=False).ask():
                show(manager, 'delete', target[0], account=target[1])
            continue
        if selection == 'add':
            platform = choose('Platform', [('WhatsApp', 'whatsapp'), ('Instagram', 'instagram'), ('Back', None)])
            if not platform:
                continue
            name = questionary.text('Local account label:').ask()
            if not name or not name.strip():
                continue
        else:
            platform, name = selection
        show(manager, 'select', platform, account=name)
        print('Log in inside Chrome, then choose Save session cookies in the platform menu.')


def main():
    manager = PlatformManager()
    telegram = TelegramController(manager)
    if config.TELEGRAM_CONTROL:
        print(telegram.start())
    try:
        while True:
            action = choose('Social Watcher', [
                ('WhatsApp', 'whatsapp'), ('Instagram', 'instagram'), ('Status All', 'status'),
                ('Refresh All', 'refresh'), ('Screenshots', 'screenshot'), ('Watchers', 'watchers'),
                ('Accounts', 'accounts'), ('Logs', 'logs'), ('Presence History', 'history'),
                ('Settings', 'settings'), ('Telegram Control', 'telegram'), ('Exit', 'exit')])
            if action in {None, 'exit'}:
                break
            if action in {'whatsapp', 'instagram'}:
                platform_menu(manager, action)
            elif action == 'accounts':
                accounts_menu(manager)
            elif action == 'watchers':
                selected = choose('Watchers', [(f'{a.title()} {p.title()}', (a, p))
                    for p in ('whatsapp', 'instagram', 'all') for a in ('watch', 'stop')] + [('Back', None)])
                if selected:
                    show(manager, *selected)
            elif action == 'telegram':
                selected = choose('Telegram Control', [('Start', 'start'), ('Stop', 'stop'),
                    ('Test notifications', 'test'), ('Back', None)])
                if selected == 'test':
                    print(test_notifications())
                elif selected:
                    print(getattr(telegram, selected)())
            else:
                show(manager, action)
    except (KeyboardInterrupt, EOFError):
        print('Closing Social Watcher...')
    finally:
        telegram.stop()
        manager.close()


if __name__ == '__main__':
    main()
