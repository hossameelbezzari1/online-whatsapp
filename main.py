from __future__ import annotations

import sys
import time
from pathlib import Path

import questionary
from questionary import Choice
from selenium.common.exceptions import WebDriverException

from account_manager import (
    account_label,
    delete_account,
    list_accounts,
    load_cookies,
    save_cookies,
    safe_account_name,
)
from browser import create_driver
from session_manager import (
    cleanup_temp_profile,
    has_session_snapshot,
    save_session_snapshot,
)
from config import LOGIN_TIMEOUT, WHATSAPP_URL, ensure_directories
from event_logger import (
    log_error,
    log_event,
    presence_history_contacts,
    read_presence_history,
)
from notifier import notify_event, test_notifications
from screenshot_manager import take_screenshot
from whatsapp_watcher import (
    get_current_chat_name,
    get_current_chat_presence,
    is_logged_in,
    wait_until_logged_in,
    watch_chat_combined,
    watch_last_outgoing_message,
)


def heading() -> None:
    print()
    print("=" * 62)
    print(" WhatsApp Watcher - Selenium + Telegram + Windows")
    print("=" * 62)
    print()


def pause() -> None:
    questionary.press_any_key_to_continue(
        "Appuyez sur une touche pour revenir..."
    ).ask()


def view_presence_history(account_name: str | None = None) -> None:
    if account_name is None:
        rows = read_presence_history()
        accounts = sorted(
            {
                str(row.get("account", "")).strip()
                for row in rows
                if str(row.get("account", "")).strip()
            },
            key=str.lower,
        )

        if not accounts:
            print("[i] Aucun history de statut pour le moment.")
            pause()
            return

        choices = [Choice(title=account, value=account) for account in accounts]
        choices.append(Choice(title="< Retour", value=None))

        account_name = questionary.select(
            "Choisissez un compte :",
            choices=choices,
        ).ask()

        if account_name is None:
            return

    contacts = presence_history_contacts(account_name)

    if not contacts:
        print("[i] Aucun history de statut pour ce compte.")
        pause()
        return

    choices = [Choice(title=contact, value=contact) for contact in contacts]
    choices.append(Choice(title="< Retour", value=None))

    contact = questionary.select(
        "Choisissez un user/contact :",
        choices=choices,
    ).ask()

    if contact is None:
        return

    rows = read_presence_history(account=account_name, contact=contact)
    rows = rows[-50:]

    print()
    print("=" * 70)
    print(f" History statut - {account_name} / {contact}")
    print("=" * 70)

    for row in rows:
        timestamp = row.get("timestamp", "")
        previous_status = row.get("previous_status", row.get("old_presence", ""))
        current_status = row.get("current_status", row.get("new_presence", ""))
        event = row.get("event", "presence_changed")
        print(f"{timestamp} | {event} | {previous_status} -> {current_status}")

    print("=" * 70)
    print(f"[i] Affichage des {len(rows)} derniers changements.")
    pause()


def choose_account() -> Path | None:
    accounts = list_accounts()

    if not accounts:
        print("[!] Aucun compte trouve dans accounts/*.pkl")
        pause()
        return None

    choices = [
        Choice(title=f"[WhatsApp] {account_label(path)}", value=path)
        for path in accounts
    ]
    choices.append(Choice(title="< Retour", value=None))

    return questionary.select(
        "Choisissez un compte WhatsApp :",
        choices=choices,
    ).ask()


def auto_save_cookies(driver, account_name: str) -> None:
    """
    Best-effort automatic .pkl refresh.
    No confirmation is requested from the user.
    """
    try:
        if is_logged_in(driver):
            path = save_cookies(driver, account_name, overwrite=True)
            print(f"[AUTO] Cookies sauvegardes : {path.name}")
    except Exception as exc:
        log_error("auto_save_cookies", exc)


def ensure_saved_account_session(driver, account_path: Path) -> str | None:
    account_name = account_label(account_path)

    # The lightweight session snapshot is primary. Unlike cookie-only restore,
    # it includes WhatsApp IndexedDB/local storage without keeping a permanent
    # full Chrome profile.
    driver.get(WHATSAPP_URL)

    if has_session_snapshot(account_name):
        print("[i] Restauration de la session legere WhatsApp...")
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            WebDriverWait(driver, 12, poll_frequency=0.25).until(
                lambda d: is_logged_in(d)
            )
            print("[+] Session restauree sans QR.")
            auto_save_cookies(driver, account_name)
            return account_name
        except Exception:
            print("[!] Snapshot present mais session non restauree.")

    # Compatibility fallback for older cookie-only accounts.
    print("[i] Tentative avec le fichier .pkl...")
    try:
        loaded_name, loaded, failed = load_cookies(driver, account_path)
        account_name = loaded_name or account_name
        print(
            f"[+] Cookies charges : {loaded} | echecs : {failed} "
            f"| compte : {account_name}"
        )
    except Exception as exc:
        log_error("load_cookies", exc)
        print(f"[!] Impossible de charger le .pkl : {exc}")

    try:
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(driver, 5, poll_frequency=0.25).until(
            lambda d: is_logged_in(d)
        )
        print("[+] Session restauree depuis le .pkl.")
        auto_save_cookies(driver, account_name)
        return account_name
    except Exception:
        pass

    print()
    print("[!] Ce compte doit etre initialise une seule fois.")
    print("[i] Scannez le QR maintenant.")
    print("[i] A la fermeture, le script sauvegardera une session legere")
    print("    (sans cache/historique Chrome) pour les prochains lancements.")
    print(f"[i] Delai : {LOGIN_TIMEOUT} secondes.")

    if not wait_until_logged_in(driver, LOGIN_TIMEOUT):
        print("[!] Connexion non detectee avant le delai.")
        return None

    print("[+] Connexion detectee.")
    auto_save_cookies(driver, account_name)
    return account_name


def check_current_status_and_notify(driver, account_name: str) -> None:
    """
    Manual status-refresh mode.

    No automatic polling is used:
      - the current chat/status is read once
      - the user chooses "Refresh" to check again
      - "Retour" returns to the account menu

    An ONLINE notification is sent on a manual refresh when the state has
    changed to ONLINE. Repeated refreshes while the same contact remains
    ONLINE do not create duplicate notifications.
    """
    previous_contact = None
    previous_presence = None

    while True:
        try:
            contact = get_current_chat_name(driver)
        except Exception as exc:
            log_error("get_current_chat_name_status_check", exc)
            contact = None

        if not contact:
            print()
            print("[!] Aucun chat WhatsApp n'est actuellement ouvert.")
            print("[i] Ouvrez une conversation dans Chrome puis appuyez sur Refresh.")

            action = questionary.select(
                "Action :",
                choices=[
                    Choice("Refresh", "refresh"),
                    Choice("< Retour", "back"),
                ],
            ).ask()

            if action in {None, "back"}:
                return

            previous_contact = None
            previous_presence = None
            continue

        try:
            presence = get_current_chat_presence(driver)
        except Exception as exc:
            log_error("get_current_chat_presence_status_check", exc)
            presence = None

        current_presence = (presence or "Not visible").strip()
        normalized_presence = current_presence.lower()

        print()
        print("=" * 58)
        print(f"[+] Chat : {contact}")
        print(f"[+] Statut actuel : {current_presence}")
        print("=" * 58)

        became_online = (
            normalized_presence == "online"
            and (
                previous_contact != contact
                or (previous_presence or "").lower() != "online"
            )
        )

        if became_online:
            screenshot_path = None

            try:
                screenshot_path = take_screenshot(
                    driver,
                    account=account_name,
                    contact=contact,
                    event="online",
                )
            except Exception as exc:
                log_error("online_status_screenshot", exc)

            row = log_event(
                account=account_name,
                contact=contact,
                event="online",
                status="online",
                message_id=None,
                message_preview="Current chat status is online",
                screenshot=str(screenshot_path) if screenshot_path else None,
            )

            try:
                results = notify_event(
                    account=account_name,
                    contact=contact,
                    event="online",
                    status="online",
                    message_preview="Current chat status is online",
                    timestamp=row["timestamp"],
                    screenshot_path=screenshot_path,
                )

                print("[+] ONLINE notification sent.")
                print(f"    Telegram: {results['telegram']['info']}")
                print(f"    Windows : {results['windows']['info']}")
            except Exception as exc:
                log_error("online_status_notify", exc)
                print(f"[!] Notification error: {exc}")

        elif normalized_presence == "online":
            print("[i] Toujours ONLINE - notification deja envoyee.")
        else:
            print("[i] Pas ONLINE pour le moment.")

        previous_contact = contact
        previous_presence = normalized_presence

        action = questionary.select(
            "Action :",
            choices=[
                Choice("Refresh", "refresh"),
                Choice("< Retour", "back"),
            ],
        ).ask()

        if action in {None, "back"}:
            return


def account_session_menu(
    driver,
    account_name: str,
    account_path: Path | None,
) -> None:
    while True:
        action = questionary.select(
            f"Compte : {account_name}",
            choices=[
                Choice("Surveiller le chat + statut ONLINE", "watch"),
                Choice("Afficher history statut d'un user", "history"),
                Choice("Sauvegarder les cookies .pkl maintenant", "save"),
                Choice("Tester les notifications", "test"),
                Choice("< Fermer le compte et revenir", "back"),
            ],
        ).ask()

        if action == "back" or action is None:
            auto_save_cookies(driver, account_name)
            return

        if action == "history":
            view_presence_history(account_name)
            continue

        if action == "save":
            auto_save_cookies(driver, account_name)
            pause()
            continue

        if action == "test":
            results = test_notifications()
            print(results)
            pause()
            continue

        if action == "watch":
            try:
                contact = get_current_chat_name(driver)
            except Exception as exc:
                log_error("get_current_chat_name", exc)
                contact = None

            if not contact:
                print()
                print("[!] Aucun chat WhatsApp n'est actuellement ouvert.")
                print("[i] Ouvrez d'abord une conversation dans Chrome,")
                print("    puis choisissez de nouveau l'option de surveillance.")
                pause()
                continue

            print()
            print(f"[+] Chat detecte automatiquement : {contact}")

            watch_chat_combined(
                driver,
                account=account_name,
                contact=contact.strip(),
            )

            # Refresh cookies after returning from combined mode.
            auto_save_cookies(driver, account_name)


def use_saved_account() -> None:
    path = choose_account()
    if path is None:
        return

    account_name = account_label(path)
    driver = None
    temp_profile = None

    try:
        driver = create_driver(account_name)
        temp_profile = getattr(driver, "_wa_temp_profile", None)

        active_name = ensure_saved_account_session(driver, path)
        if not active_name:
            return

        account_name = active_name
        account_session_menu(driver, active_name, path)

    except WebDriverException as exc:
        log_error("saved_account_webdriver", exc)
        print(f"[!] Erreur Selenium/Chrome : {exc}")
        pause()
    except Exception as exc:
        log_error("saved_account", exc)
        print(f"[!] Erreur : {exc}")
        pause()
    finally:
        if driver is not None:
            try:
                auto_save_cookies(driver, account_name)
            except Exception:
                pass

            try:
                driver.quit()
            except Exception:
                pass

        if temp_profile is not None:
            try:
                saved = save_session_snapshot(account_name, temp_profile)
                print(f"[AUTO] Session legere sauvegardee : {saved.name}")
            except Exception as exc:
                log_error("save_session_snapshot_saved_account", exc)
                print(f"[!] Sauvegarde session legere impossible : {exc}")
            finally:
                cleanup_temp_profile(temp_profile)


def add_new_account() -> None:
    account_name = questionary.text(
        "Nom a donner a ce compte (ex: personal, business) :",
        validate=lambda x: True if x.strip() else "Entrez un nom de compte.",
    ).ask()

    if not account_name:
        return

    account_name = safe_account_name(account_name)
    driver = None
    temp_profile = None

    try:
        driver = create_driver(account_name)
        temp_profile = getattr(driver, "_wa_temp_profile", None)
        driver.get(WHATSAPP_URL)

        # If a lightweight session already exists under this name, reuse it.
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            WebDriverWait(driver, 8, poll_frequency=0.25).until(
                lambda d: is_logged_in(d)
            )
            print("[+] Session existante restauree.")
        except Exception:
            print()
            print("[i] Scannez le QR code dans la fenetre Chrome.")
            print("[i] Le script gardera seulement les donnees de session utiles,")
            print("    pas le cache/historique d'un profil Chrome complet.")
            print(f"[i] Delai de connexion : {LOGIN_TIMEOUT} secondes.")

            if not wait_until_logged_in(driver, LOGIN_TIMEOUT):
                print("[!] Delai de connexion depasse.")
                pause()
                return

        path = save_cookies(driver, account_name, overwrite=True)
        print(f"[+] Cookies .pkl sauvegardes : {path.name}")

        account_session_menu(driver, account_name, path)

    except WebDriverException as exc:
        log_error("new_account_webdriver", exc)
        print(f"[!] Erreur Selenium/Chrome : {exc}")
        pause()
    except Exception as exc:
        log_error("new_account", exc)
        print(f"[!] Erreur : {exc}")
        pause()
    finally:
        if driver is not None:
            try:
                auto_save_cookies(driver, account_name)
            except Exception:
                pass

            try:
                driver.quit()
            except Exception:
                pass

        if temp_profile is not None:
            try:
                saved = save_session_snapshot(account_name, temp_profile)
                print(f"[AUTO] Session legere sauvegardee : {saved.name}")
            except Exception as exc:
                log_error("save_session_snapshot_new_account", exc)
                print(f"[!] Sauvegarde session legere impossible : {exc}")
            finally:
                cleanup_temp_profile(temp_profile)


def delete_saved_account() -> None:
    path = choose_account()
    if path is None:
        return

    confirm = questionary.confirm(
        f"Supprimer le fichier de compte {path.name} ?",
        default=False,
    ).ask()

    if confirm:
        delete_account(path)
        print("[+] Compte supprime (.pkl + session legere).")
        pause()


def main() -> None:
    ensure_directories()

    while True:
        heading()

        action = questionary.select(
            "Que voulez-vous faire ?",
            choices=[
                Choice("Utiliser un compte sauvegarde (.pkl)", "saved"),
                Choice("Ajouter un nouveau compte WhatsApp", "new"),
                Choice("Afficher history statut", "history"),
                Choice("Tester Telegram + notifications Windows", "test"),
                Choice("Supprimer un compte sauvegarde", "delete"),
                Choice("Quitter", "exit"),
            ],
        ).ask()

        if action in {None, "exit"}:
            print("Bye.")
            return

        if action == "saved":
            use_saved_account()
        elif action == "new":
            add_new_account()
        elif action == "history":
            view_presence_history()
        elif action == "test":
            print(test_notifications())
            pause()
        elif action == "delete":
            delete_saved_account()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(0)
