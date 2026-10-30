import re
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture
def qrz_examples() -> list[bytes]:
    """The five example replies in QRZ's XML spec 1.34 (owner-supplied fixture), in order:
    login, AA7BQ callsign, DXCC 291, Not found, Session Timeout."""
    spec = Path(__file__).parent / "fixtures" / "qrz_xml_spec_1.34.txt"
    if not spec.exists():
        # QRZ's copyrighted spec is kept out of the public repo; paste it here to run these.
        pytest.skip(f"QRZ XML spec 1.34 not present at {spec}")
    text = spec.read_text(encoding="utf-8")
    blocks = re.findall(r"<\?xml.*?</QRZDatabase>", text, re.S)
    assert len(blocks) == 5
    return [block.encode("utf-8") for block in blocks]


class MemoryKeyring(KeyringBackend):
    """Stands in for the OS credential store in every test (requirements 4.9)."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 31: no test may reach QRZ or any other service."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("network disabled in tests")

    from beam_navigator import qrz_client

    monkeypatch.setattr(qrz_client, "urlopen", refuse)


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    """No test may ever touch the real Windows Credential Manager or macOS Keychain."""
    previous = keyring.get_keyring()
    fake = MemoryKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(previous)
