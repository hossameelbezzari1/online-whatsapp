from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import json
from pathlib import Path

from config import SESSIONS_DIR


def safe_session_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", "_", value).strip(" ._")
    value = value or "whatsapp_account"
    if value.upper().split('.')[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "account_" + value
    return value


def session_dir(account_name: str) -> Path:
    path = SESSIONS_DIR / safe_session_name(account_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def has_session_snapshot(account_name: str) -> bool:
    root = session_dir(account_name)
    return (root / "Local State").exists() or (root / "Default").exists()


def create_temp_profile(account_name: str) -> Path:
    """
    Create a disposable Chrome profile and restore only the lightweight
    WhatsApp/session-related snapshot if one exists.
    """
    temp_root = Path(
        tempfile.mkdtemp(prefix=f"wa_{safe_session_name(account_name)}_")
    )

    restore_session_snapshot(account_name, temp_root)
    return temp_root


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_dir(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(
        "Cache", "CacheStorage", "Code Cache", "GPUCache", "Media Cache", "ScriptCache"))


def restore_session_snapshot(account_name: str, temp_root: Path) -> None:
    """
    Restore only session-relevant Chrome files.

    We deliberately do NOT restore Cache, Code Cache, GPUCache, history,
    downloads, media cache, crash reports, etc.
    """
    saved = session_dir(account_name)

    # Root-level encryption/material metadata used by Chromium.
    _copy_file(saved / "Local State", temp_root / "Local State")

    saved_default = saved / "Default"
    temp_default = temp_root / "Default"
    temp_default.mkdir(parents=True, exist_ok=True)

    # Small profile metadata that can help Chrome reopen storage correctly.
    for filename in (
        "Preferences",
        "Secure Preferences",
    ):
        _copy_file(saved_default / filename, temp_default / filename)

    # WhatsApp/session-relevant storage only.
    for dirname in (
        "IndexedDB",
        "Local Storage",
        "Session Storage",
        "Service Worker",
        "WebStorage",
        "Storage",
    ):
        _copy_dir(saved_default / dirname, temp_default / dirname)

    # Cookie DB (plus journal) lives in Network/.
    for filename in (
        "Cookies",
        "Cookies-journal",
    ):
        _copy_file(
            saved_default / "Network" / filename,
            temp_default / "Network" / filename,
        )


def save_session_snapshot(account_name: str, temp_root: Path, accounts: dict | None = None) -> Path:
    """
    Save only lightweight session data after Chrome has been closed.

    The destination is replaced atomically-ish via a staging directory so
    stale IndexedDB files from an older session do not accumulate forever.
    """
    target = session_dir(account_name)
    staging = target.with_name(target.name + ".__new__")

    if staging.exists():
        _remove_session_tree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    if accounts is not None:
        (staging / 'accounts.json').write_text(json.dumps(accounts), encoding='utf-8')

    # Root metadata.
    _copy_file(temp_root / "Local State", staging / "Local State")

    src_default = temp_root / "Default"
    dst_default = staging / "Default"
    dst_default.mkdir(parents=True, exist_ok=True)

    for filename in (
        "Preferences",
        "Secure Preferences",
    ):
        _copy_file(src_default / filename, dst_default / filename)

    for dirname in (
        "IndexedDB",
        "Local Storage",
        "Session Storage",
        "Service Worker",
        "WebStorage",
        "Storage",
    ):
        _copy_dir(src_default / dirname, dst_default / dirname)

    for filename in (
        "Cookies",
        "Cookies-journal",
    ):
        _copy_file(
            src_default / "Network" / filename,
            dst_default / "Network" / filename,
        )

    # Replace previous snapshot.
    old = target.with_name(target.name + ".__old__")
    if old.exists():
        _remove_session_tree(old)

    # target currently exists because session_dir() creates it.
    # Move the old one aside first.
    if target.exists():
        try:
            target.rename(old)
        except OSError:
            raise RuntimeError("Could not preserve previous session; snapshot not replaced")

    try:
        staging.rename(target)
    except OSError:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    _remove_session_tree(old)

    return target


def cleanup_temp_profile(temp_root: Path | None) -> None:
    if temp_root is None:
        return

    temp_root = Path(temp_root).resolve()
    expected_root = Path(tempfile.gettempdir()).resolve()
    if temp_root.parent != expected_root or not temp_root.name.startswith("wa_"):
        raise ValueError("Refusing cleanup outside the disposable profile directory")

    # Chrome may need a tiny moment to release SQLite/LevelDB file handles.
    for attempt in range(6):
        try:
            shutil.rmtree(temp_root)
            return
        except Exception:
            time.sleep(0.35)

    shutil.rmtree(temp_root, ignore_errors=True)


def delete_session_snapshot(account_name: str) -> None:
    _remove_session_tree(SESSIONS_DIR / safe_session_name(account_name))


def _remove_session_tree(path: Path) -> None:
    resolved = path.resolve()
    root = SESSIONS_DIR.resolve()
    if resolved.parent != root:
        raise ValueError("Refusing removal outside sessions directory")
    shutil.rmtree(resolved, ignore_errors=True)
