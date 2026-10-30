"""Acceptance 34-36 (requirements 4.9), end to end through the pages with a replayed QRZ.
No test here reaches the network or the real credential store."""

import logging
import sqlite3
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError

import pytest
from nicegui.testing import User

from beam_navigator.core.models import Net, OperatorProfile, Station
from beam_navigator.desk import Desk
from beam_navigator.export import export_session
from beam_navigator.qrz_client import QrzClient
from beam_navigator.qrz_login import save_login
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository
from beam_navigator.ui.app import register_pages

PASSWORD = "Unique-QRZ-pw-7781"


class Replay:
    def __init__(self, replies: list[bytes | Exception]) -> None:
        self.replies = list(replies)

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
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


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "beamnav.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = open_db(db_path)
    yield connection
    connection.close()


@pytest.fixture
def desk(conn: sqlite3.Connection) -> Desk:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "UTC", "NJ", False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    return Desk(conn, RotateService(conn))


def counts(conn: sqlite3.Connection) -> tuple[int, ...]:
    tables = ("station", "qrz_record", "checkin", "setting")
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables)


async def dashboard_lookup(user: User, call: str) -> None:
    target = user.find(marker="target")
    target.clear()
    target.type(call).trigger("keydown.enter")  # nothing stored: QRZ is asked at once


async def test_offline_lookup_changes_nothing(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # acceptance 34
    save_login("xx1xxx", PASSWORD)
    register_pages(lambda: desk, QrzClient(transport=Replay([URLError("offline")])))
    await user.open("/")
    before = counts(conn)
    await dashboard_lookup(user, "AA7BQ")
    await user.should_see("QRZ can't be reached. Everything else works offline.")
    assert counts(conn) == before


async def test_password_never_persisted(
    user: User,
    desk: Desk,
    conn: sqlite3.Connection,
    db_path: Path,
    qrz_examples: list[bytes],
    caplog: pytest.LogCaptureFixture,
    memory_keyring: object,
) -> None:  # acceptance 35
    caplog.set_level(logging.DEBUG)
    refused = with_error(qrz_examples[4], f"password incorrect for {PASSWORD}")
    replies: list[bytes | Exception] = [refused, qrz_examples[0], qrz_examples[1]]
    register_pages(lambda: desk, QrzClient(transport=Replay(replies)))
    await user.open("/settings")
    user.find("QRZ").click()
    [username] = user.find(marker="qrz-username").elements
    [password] = user.find(marker="qrz-password").elements
    username.set_value("xx1xxx")  # type: ignore[attr-defined]
    password.set_value(PASSWORD)  # type: ignore[attr-defined]
    user.find(marker="qrz-save").click()
    user.find(marker="qrz-test").click()  # fails: QRZ "echoes" the password back
    await user.should_see("QRZ login failed")
    await user.should_not_see(PASSWORD)
    await user.open("/")
    await dashboard_lookup(user, "AA7BQ")  # logs in and looks up
    await user.should_see("from QRZ, ")

    nets = NetRepository(conn)
    net = nets.save_net(Net(None, "Test net", None, None, None, 144.2, None, None, "2 m",
                            None, None, False))  # fmt: skip
    assert net.id is not None
    session = nets.start_session(net.id, "2026-10-28")
    nets.add_checkin(session.id, "AA7BQ", grid="DM32af")
    exports = [export_session(conn, desk, session.id, fmt, include_heard=True)
               for fmt in ("text", "csv", "json")]  # fmt: skip
    conn.commit()

    in_store = memory_keyring.store  # type: ignore[attr-defined]
    assert in_store[("beam-navigator-qrz", "password")] == PASSWORD  # there, and only there
    stored = b"".join(path.read_bytes() for path in db_path.parent.iterdir() if path.is_file())
    assert PASSWORD.encode() not in stored
    rows = conn.execute("SELECT key, value FROM setting").fetchall()
    assert all(PASSWORD not in f"{r['key']}={r['value']}" for r in rows)
    assert PASSWORD not in caplog.text
    assert all(PASSWORD not in text for text in exports)


async def test_qrz_grid_never_overwrites(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:  # acceptance 36
    from beam_navigator.core.qrz import parse_response

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    desk.qrz_store(record, None)  # QRZ answered before the station was saved
    desk.stations.save(Station("AA7BQ", "FRED", "FN20ok", None, None, "saved", ""))
    save_login("xx1xxx", PASSWORD)
    register_pages(lambda: desk, QrzClient(transport=Replay([])))
    await user.open("/")
    await dashboard_lookup(user, "AA7BQ")
    await user.should_see("DM32af")  # shown, labelled from QRZ
    await user.should_see("from QRZ, ")
    await user.should_see("AA7BQ — saved")  # the bearing still uses the saved grid
    await user.should_not_see(marker="qrz-save")  # nothing to save over
    saved = desk.stations.get("AA7BQ")
    assert saved is not None and saved.grid == "FN20ok"
