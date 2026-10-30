"""The QRZ login lives only in the OS credential store (requirements 4.9)."""

from typing import Any

import keyring
import pytest

from beam_navigator.qrz_login import SERVICE, clear_login, load_login, save_login, saved_username


def test_tests_never_reach_the_real_store(memory_keyring: Any) -> None:
    assert keyring.get_keyring() is memory_keyring


def test_round_trip(memory_keyring: Any) -> None:
    save_login(" n2lqh ", "secret pw")
    assert load_login() == ("n2lqh", "secret pw")
    assert saved_username() == "n2lqh"
    assert set(memory_keyring.store) == {(SERVICE, "username"), (SERVICE, "password")}


@pytest.mark.parametrize(("username", "password"), [("", "pw"), ("  ", "pw"), ("n2lqh", "")])
def test_blank_refused(username: str, password: str, memory_keyring: Any) -> None:
    with pytest.raises(ValueError, match="QRZ needs both a username and a password."):
        save_login(username, password)
    assert memory_keyring.store == {}


def test_clear_removes_both(memory_keyring: Any) -> None:
    save_login("n2lqh", "pw")
    clear_login()
    assert memory_keyring.store == {} and load_login() is None
    clear_login()  # already clear: no error


def test_half_saved_is_no_login(memory_keyring: Any) -> None:
    keyring.set_password(SERVICE, "username", "n2lqh")
    assert load_login() is None


def test_no_credential_store() -> None:  # review I1: e.g. a headless Raspberry Pi
    from keyring.backends.fail import Keyring as NoStore

    from beam_navigator.qrz_login import NO_STORE, LoginUnavailable

    keyring.set_keyring(NoStore())  # the autouse fixture restores the previous backend
    assert saved_username() is None
    with pytest.raises(LoginUnavailable, match=NO_STORE):
        load_login()
    with pytest.raises(ValueError, match=NO_STORE):
        save_login("n2lqh", "pw")
    clear_login()  # nothing to clear: no error
