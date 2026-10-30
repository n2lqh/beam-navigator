"""The QRZ client against replayed spec 1.34 examples; no test reaches the network."""

import xml.etree.ElementTree as ElementTree
from urllib.error import URLError

import pytest

from beam_navigator.qrz_client import OFFLINE, URL, QrzClient, QrzError
from beam_navigator.qrz_login import save_login

PASSWORD = "s3cret-Pw!"
LOGIN, CALLSIGN, DXCC, NOT_FOUND, TIMEOUT = range(5)


class FakeTransport:
    def __init__(self, replies: list[bytes | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
        self.calls.append((url, dict(fields)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def with_error(example: bytes, text: str) -> bytes:
    """A spec example with its Session Error text changed (derived, never handwritten)."""
    root = ElementTree.fromstring(example)
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "Error":
            node.text = text
    return ElementTree.tostring(root)


@pytest.fixture(autouse=True)
def login() -> None:
    save_login("xx1xxx", PASSWORD)


def client_for(examples: list[bytes], order: list[int | bytes | Exception]) -> tuple[
    QrzClient, FakeTransport
]:  # fmt: skip
    replies = [examples[item] if isinstance(item, int) else item for item in order]
    transport = FakeTransport(replies)
    return QrzClient(transport=transport), transport


def test_login_posts_fields(qrz_examples: list[bytes]) -> None:
    client, transport = client_for(qrz_examples, [LOGIN])
    session = client.login()
    assert session.sub_exp == "Wed Jan 1 12:34:03 2013"
    [(url, fields)] = transport.calls
    assert url == URL == "https://xmldata.qrz.com/xml/current/"
    assert fields["username"] == "xx1xxx" and fields["password"] == PASSWORD
    assert fields["agent"].startswith("BeamNav")
    assert PASSWORD not in url


def test_lookup_reuses_key(qrz_examples: list[bytes]) -> None:
    client, transport = client_for(qrz_examples, [LOGIN, CALLSIGN, CALLSIGN])
    record, notice = client.lookup("aa7bq")
    assert record.call == "AA7BQ" and notice is None
    client.lookup("AA7BQ")
    assert [("username" in f, f.get("callsign")) for _, f in transport.calls] == [
        (True, None), (False, "AA7BQ"), (False, "AA7BQ")
    ]  # fmt: skip
    assert transport.calls[1][1]["s"] == "2331uf894c4bd29f3923f3bacf02c532d7bd9"


def test_session_timeout_relogs_once(qrz_examples: list[bytes]) -> None:
    client, transport = client_for(qrz_examples, [LOGIN, TIMEOUT, LOGIN, CALLSIGN])
    record, _ = client.lookup("AA7BQ")
    assert record.call == "AA7BQ" and len(transport.calls) == 4
    client, transport = client_for(qrz_examples, [LOGIN, TIMEOUT, LOGIN, TIMEOUT])
    with pytest.raises(QrzError, match="Session Timeout"):
        client.lookup("AA7BQ")
    assert len(transport.calls) == 4 and transport.replies == []


def test_not_found_message(qrz_examples: list[bytes]) -> None:
    client, _ = client_for(qrz_examples, [LOGIN, NOT_FOUND])
    with pytest.raises(QrzError, match="QRZ has no record for G1SRDD."):
        client.lookup("g1srdd")


def test_login_failed_message(qrz_examples: list[bytes]) -> None:
    client, _ = client_for(qrz_examples, [with_error(qrz_examples[TIMEOUT], "password incorrect")])
    with pytest.raises(QrzError, match="QRZ login failed: password incorrect"):
        client.login()


@pytest.mark.parametrize("failure", [URLError("no route"), TimeoutError(), OSError("dns")])
def test_offline_message(qrz_examples: list[bytes], failure: Exception) -> None:
    client, _ = client_for(qrz_examples, [failure])
    with pytest.raises(QrzError) as caught:
        client.lookup("AA7BQ")
    assert str(caught.value) == OFFLINE == "QRZ can't be reached. Everything else works offline."


def test_unreadable_reply(qrz_examples: list[bytes]) -> None:
    client, _ = client_for(qrz_examples, [b"<html>maintenance</html>"])
    with pytest.raises(QrzError, match="cannot read"):
        client.login()


def test_no_login_message(qrz_examples: list[bytes]) -> None:
    from beam_navigator.qrz_login import clear_login

    clear_login()
    client, transport = client_for(qrz_examples, [])
    with pytest.raises(QrzError, match="Set up your QRZ login in Settings → QRZ."):
        client.lookup("AA7BQ")
    assert transport.calls == []


def test_connection_refused_stops(qrz_examples: list[bytes]) -> None:
    refused = with_error(qrz_examples[TIMEOUT], "Connection refused")
    client, transport = client_for(qrz_examples, [refused])
    with pytest.raises(QrzError, match="QRZ refused service for this login; try again tomorrow."):
        client.lookup("AA7BQ")
    with pytest.raises(QrzError, match="refused service"):
        client.lookup("AA7BQ")
    assert len(transport.calls) == 1


def test_non_subscriber_notice(qrz_examples: list[bytes]) -> None:
    limited = qrz_examples[CALLSIGN].replace(
        b"<SubExp>Wed Jan 1 12:34:03 2013</SubExp>", b"<SubExp>non-subscriber</SubExp>"
    )
    client, _ = client_for(qrz_examples, [LOGIN, limited])
    _, notice = client.lookup("AA7BQ")
    assert notice == (
        "Your QRZ login has no XML Data subscription, so QRZ sends limited data."
    )


def test_blank_callsign(qrz_examples: list[bytes]) -> None:
    client, transport = client_for(qrz_examples, [])
    with pytest.raises(QrzError, match="Type a callsign first."):
        client.lookup("  ")
    assert transport.calls == []


def test_password_never_in_errors(qrz_examples: list[bytes]) -> None:
    echo = with_error(qrz_examples[TIMEOUT], f"bad login {PASSWORD}")
    cases: list[list[int | bytes | Exception]] = [
        [echo], [URLError(PASSWORD)], [LOGIN, NOT_FOUND], [LOGIN, TIMEOUT, LOGIN, TIMEOUT],
        [b"junk"],
    ]  # fmt: skip
    for order in cases:
        client, _ = client_for(qrz_examples, order)
        with pytest.raises(QrzError) as caught:
            client.lookup("G1SRDD")
        assert PASSWORD not in str(caught.value) and PASSWORD not in repr(caught.value)
        assert caught.value.__cause__ is None or PASSWORD not in repr(caught.value.__cause__)


def test_no_credential_store_message(qrz_examples: list[bytes]) -> None:  # review I1
    import keyring
    from keyring.backends.fail import Keyring as NoStore

    keyring.set_keyring(NoStore())
    client, transport = client_for(qrz_examples, [])
    with pytest.raises(QrzError, match="no credential store"):
        client.lookup("AA7BQ")
    assert transport.calls == []


def test_http_protocol_errors_are_offline(qrz_examples: list[bytes]) -> None:  # review I4
    from http.client import BadStatusLine, IncompleteRead

    for failure in (IncompleteRead(b""), BadStatusLine("junk")):
        client, _ = client_for(qrz_examples, [failure])
        with pytest.raises(QrzError) as caught:
            client.lookup("AA7BQ")
        assert str(caught.value) == OFFLINE


def test_forget_session_never_waits_for_a_lookup(qrz_examples: list[bytes]) -> None:  # I3
    import threading

    client, transport = client_for(qrz_examples, [LOGIN, CALLSIGN, LOGIN, CALLSIGN])
    client.lookup("AA7BQ")
    with client._lock:  # a lookup in progress in a worker thread
        done = threading.Event()
        threading.Thread(target=lambda: (client.forget_session(), done.set())).start()
        assert done.wait(0.5), "forget_session blocked on the lookup lock"
    client.lookup("AA7BQ")  # the next lookup logs in afresh
    assert ["username" in fields for _, fields in transport.calls] == [True, False, True, False]


def test_tests_cannot_reach_the_network() -> None:  # review: acceptance 31 guard
    import urllib.request

    from beam_navigator import qrz_client

    assert qrz_client.urlopen is not urllib.request.urlopen


def test_agent_version_without_package_metadata() -> None:
    # The .exe must not bundle the install records (one held the project's local path),
    # so the version lives in the package and must match pyproject (decision 38).
    import tomllib
    from pathlib import Path

    from beam_navigator import __version__
    from beam_navigator.qrz_client import default_agent

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert __version__ == tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert default_agent() == f"BeamNav{__version__}"
