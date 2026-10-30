"""The QRZ login (requirements 4.9). It is kept only in the operating system's credential
store through keyring: never in the database, settings, logs or exports."""

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "beam-navigator-qrz"
NO_STORE = "This computer has no credential store, so QRZ lookup is unavailable."
_USERNAME = "username"
_PASSWORD = "password"


class LoginUnavailable(Exception):
    """No credential store (e.g. a headless Raspberry Pi): QRZ cannot be used here."""


def save_login(username: str, password: str) -> None:
    name = username.strip()
    if not name or not password:
        raise ValueError("QRZ needs both a username and a password.")
    try:
        keyring.set_password(SERVICE, _USERNAME, name)
        keyring.set_password(SERVICE, _PASSWORD, password)
    except KeyringError:
        raise ValueError(NO_STORE) from None


def saved_username() -> str | None:
    try:
        return keyring.get_password(SERVICE, _USERNAME)
    except KeyringError:
        return None


def load_login() -> tuple[str, str] | None:
    try:
        username = keyring.get_password(SERVICE, _USERNAME)
        password = keyring.get_password(SERVICE, _PASSWORD)
    except KeyringError:
        raise LoginUnavailable(NO_STORE) from None
    if not username or not password:
        return None
    return username, password


def clear_login() -> None:
    for entry in (_USERNAME, _PASSWORD):
        try:
            keyring.delete_password(SERVICE, entry)
        except (PasswordDeleteError, KeyringError):
            pass  # already clear, or no store to clear
