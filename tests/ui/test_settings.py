"""Settings screens through NiceGUI's simulated user. Rotator tests use a fake that
answers like a rotator: nothing here may reach the real rotator on this PC."""

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import OperatorProfile, RotatorProfile, Station
from beam_navigator.desk import Desk
from beam_navigator.rotators.base import Capabilities, CommandResult, ConnectionResult
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    BandRepository,
    CommandLog,
    ProfileRepository,
    RotatorRepository,
)
from beam_navigator.ui.app import register_pages
from beam_navigator.ui.settings import ROTATOR_HELP, SIMULATION_LABEL


class FakeRotator:
    """Answers a connection test with a position; records any move it is sent."""

    def __init__(self) -> None:
        self.moves: list[float] = []
        self.last_sent: str | None = None
        self.last_reply: str | None = None

    def connect(self) -> ConnectionResult:
        return ConnectionResult(True, "connected")

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=True, has_stop=True)

    def get_position(self) -> float | None:
        return 12.0

    def set_azimuth(self, deg: float) -> CommandResult:
        self.moves.append(deg)
        return CommandResult(True, "sent")

    def stop(self) -> CommandResult:
        self.moves.append(-1)
        return CommandResult(True, "stopped")

    def disconnect(self) -> None:
        pass


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def fake() -> FakeRotator:
    return FakeRotator()


@pytest.fixture
def desk(conn: sqlite3.Connection, fake: FakeRotator) -> Desk:
    service = RotateService(conn, adapter_for=lambda p: fake, tester_for=lambda p: fake)
    return Desk(conn, service)


def add_profile(conn: sqlite3.Connection) -> None:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "km", "UTC", None, False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)


def add_pst(conn: sqlite3.Connection) -> int:
    saved = RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "pstrotator", "127.0.0.1", 12000, 0.0, 450.0, 0.0, None,
                       ("2 m",), False, False)  # fmt: skip
    )
    assert saved.id is not None
    return saved.id


def element(user: User, marker: str) -> ui.element:
    [found] = user.find(marker=marker).elements
    return found


async def eventually(condition: Callable[[], bool]) -> None:
    """ui.refreshable re-renders in a background task; wait for it."""
    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.01)
    assert condition()


async def open_tab(user: User, desk: Desk, tab: str) -> None:
    register_pages(lambda: desk)
    await user.open("/settings")
    user.find(tab).click()


async def test_add_station_profile(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    await open_tab(user, desk, "Station")
    user.find(marker="profile-name").type("Home")
    user.find(marker="profile-grid").type("FM29pt")
    user.find(marker="profile-timezone").type("America/New_York")
    user.find("Save station").click()
    await user.should_see("Activate")
    user.find("Activate").click()
    await user.should_see("Active")
    assert desk.look_up("FN20ok", "2 m").error is None


async def test_bad_grid_shown_not_saved(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    await open_tab(user, desk, "Station")
    user.find(marker="profile-name").type("Home")
    user.find(marker="profile-grid").type("ZZ99")
    user.find("Save station").click()
    await user.should_see("ZZ99")
    assert ProfileRepository(conn).list() == []


async def test_live_switch_needs_test(
    user: User, desk: Desk, conn: sqlite3.Connection, fake: FakeRotator
) -> None:  # acceptance 25
    rotator = add_pst(conn)
    await open_tab(user, desk, "Rotators")
    live = element(user, f"live-{rotator}")
    assert not live.enabled
    user.find(marker=f"test-connection-{rotator}").click()
    await user.should_see("Rotator answered: 12.0°.")
    await eventually(lambda: element(user, f"live-{rotator}").enabled)
    user.find(marker=f"edit-{rotator}").click()
    user.find(marker="rotator-port").clear().type("12002")
    user.find("Save rotator").click()
    await user.should_see("Saved VHF")
    await eventually(lambda: not element(user, f"live-{rotator}").enabled)
    assert RotatorRepository(conn).get(rotator).live is False
    assert fake.moves == []


async def test_going_live_says_so(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    rotator = add_pst(conn)
    RotatorRepository(conn).record_connection_test(rotator, True)
    await open_tab(user, desk, "Rotators")
    switch = element(user, f"live-{rotator}")
    assert isinstance(switch, ui.switch)
    switch.set_value(True)
    await user.should_see("Live: Rotate turns the real antenna")
    assert RotatorRepository(conn).get(rotator).live is True


async def test_test_move_in_simulation(
    user: User, desk: Desk, conn: sqlite3.Connection, fake: FakeRotator
) -> None:
    rotator = add_pst(conn)
    await open_tab(user, desk, "Rotators")
    user.find(marker=f"test-heading-{rotator}").type("90")
    user.find(marker=f"test-move-{rotator}").click()
    await user.should_see("Simulated: Commanded 90.0°, measured 90.0°")
    assert fake.moves == []
    assert CommandLog(conn).recent(rotator) == []


async def test_add_rotator_starts_simulated(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # acceptance 25
    await open_tab(user, desk, "Rotators")
    user.find(marker="rotator-name").type("UHF")
    preset = element(user, "rotator-preset")
    assert isinstance(preset, ui.select)
    preset.set_value("Yaesu 450° (0–450°)")
    user.find("Save rotator").click()
    await user.should_see("Saved UHF")
    [saved] = RotatorRepository(conn).list()
    assert (saved.adapter, saved.az_min, saved.az_max, saved.live) == (
        "simulation", 0.0, 450.0, False
    )


async def test_band_long_path_toggle(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    await open_tab(user, desk, "Bands")
    switch = element(user, "long-path-2m")
    assert isinstance(switch, ui.switch)
    switch.set_value(True)
    await user.should_see("2 m")
    band = BandRepository(conn).get("2 m")
    assert band is not None and band.long_path


async def test_delete_band_in_use_refused(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # Focus 4
    add_pst(conn)
    await open_tab(user, desk, "Bands")
    user.find(marker="delete-band-2m").click()
    await user.should_see("2 m is served by VHF; remove it from that rotator first.")
    assert BandRepository(conn).get("2 m") is not None


async def test_alias_round_trip(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    add_profile(conn)
    await open_tab(user, desk, "Aliases")
    user.find(marker="alias-name").type("CLUB")
    user.find(marker="alias-value").type("FM29jw")
    user.find("Add alias").click()
    await user.should_see("CLUB")
    club = desk.look_up("CLUB", "2 m")
    grid = desk.look_up("FM29jw", "2 m")
    assert club.bearing_text == grid.bearing_text and club.bearing_text is not None


def assert_rotator_hints(user: User) -> None:
    for marker, text in ROTATOR_HELP.items():
        assert element(user, marker).props.get("hint") == text, marker


async def test_every_rotator_field_has_help(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # owner request 2026-10-28
    saved = RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, None, (),
                       False, False)  # fmt: skip
    )
    await open_tab(user, desk, "Rotators")
    assert_rotator_hints(user)
    user.find(marker=f"edit-{saved.id}").click()
    assert_rotator_hints(user)


async def test_about_travel_panel(user: User, desk: Desk) -> None:
    await open_tab(user, desk, "Rotators")
    await user.should_see(marker="rotator-about")
    await user.should_see("180–540")
    await user.should_see("Test connection passes")


def test_help_copy() -> None:
    assert set(ROTATOR_HELP) == {
        "rotator-name", "rotator-adapter", "rotator-host", "rotator-port", "rotator-preset",
        "rotator-speed", "rotator-min", "rotator-max", "rotator-offset", "rotator-bands",
    }  # fmt: skip
    assert "true bearing + offset" in ROTATOR_HELP["rotator-offset"]
    assert "12000" in ROTATOR_HELP["rotator-port"] and "4533" in ROTATOR_HELP["rotator-port"]
    assert ROTATOR_HELP["rotator-min"] == ROTATOR_HELP["rotator-max"]
    # Review: speed also drives the simulator; a net's own rotator comes before the band's.
    speed = ROTATOR_HELP["rotator-speed"]
    assert "simulat" in speed and "only" not in speed
    assert "unless the net names its own rotator" in ROTATOR_HELP["rotator-bands"]


class ReplayQrz:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = list(replies)

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
        return self.replies.pop(0)


async def open_qrz_tab(user: User, desk: Desk, replies: list[bytes]) -> None:
    from beam_navigator.qrz_client import QrzClient

    register_pages(lambda: desk, QrzClient(transport=ReplayQrz(replies)))
    await user.open("/settings")
    user.find("QRZ").click()


async def test_qrz_tab_save_and_test_login(
    user: User, desk: Desk, qrz_examples: list[bytes], memory_keyring: Any
) -> None:  # requirements 4.9
    from beam_navigator.qrz_login import load_login

    await open_qrz_tab(user, desk, [qrz_examples[0]])
    element(user, "qrz-username").set_value("xx1xxx")
    element(user, "qrz-password").set_value("pw-123")
    user.find(marker="qrz-save").click()
    await user.should_see("Saved QRZ login for xx1xxx")
    assert load_login() == ("xx1xxx", "pw-123")
    assert element(user, "qrz-password").value == ""  # never shown back
    user.find(marker="qrz-test").click()
    await user.should_see("Logged in. Subscription until Wed Jan 1 12:34:03 2013")


async def test_qrz_tab_clear(user: User, desk: Desk, qrz_examples: list[bytes]) -> None:
    from beam_navigator.qrz_login import load_login, save_login

    save_login("xx1xxx", "pw-123")
    await open_qrz_tab(user, desk, [])
    await user.should_see("Saved login: xx1xxx")
    user.find(marker="qrz-clear").click()
    await user.should_see("No QRZ login saved.")
    assert load_login() is None


async def test_qrz_test_login_without_login(user: User, desk: Desk) -> None:
    await open_qrz_tab(user, desk, [])
    user.find(marker="qrz-test").click()
    await user.should_see("Set up your QRZ login in Settings → QRZ.")


async def test_auto_switch_persists(user: User, desk: Desk) -> None:
    await open_qrz_tab(user, desk, [])
    assert element(user, "qrz-auto").value is True  # on by default (owner, 2026-10-29)
    element(user, "qrz-auto").set_value(False)
    await eventually(lambda: desk.settings.get("qrz_auto") == "off")
    element(user, "qrz-auto").set_value(True)
    await eventually(lambda: desk.settings.get("qrz_auto") == "on")
    element(user, "qrz-auto").set_value(False)
    await eventually(lambda: desk.settings.get("qrz_auto") == "off")


async def test_settings_open_without_a_credential_store(user: User, desk: Desk) -> None:
    import keyring
    from keyring.backends.fail import Keyring as NoStore

    keyring.set_keyring(NoStore())  # review I1: e.g. a headless Raspberry Pi
    await open_qrz_tab(user, desk, [])
    await user.should_see("No QRZ login saved.")
    element(user, "qrz-username").set_value("xx1xxx")
    element(user, "qrz-password").set_value("pw")
    user.find(marker="qrz-save").click()
    await user.should_see("no credential store")
    user.find("Station").click()
    await user.should_see(marker="profile-name")


# Keys (decision 33) ------------------------------------------------------------------


def press(user: User, code: str, ctrl: bool = False) -> None:
    """One fresh keydown, as the browser reports it, to the key-recording dialog."""
    user.find(kind=ui.keyboard).trigger(
        "key",
        {"action": "keydown", "repeat": False, "altKey": False, "ctrlKey": ctrl,
         "metaKey": False, "shiftKey": False, "key": code, "code": code, "location": 0},
    )  # fmt: skip


async def test_keys_tab_lists_every_action(user: User, desk: Desk) -> None:
    from beam_navigator.core.keymap import ACTIONS

    await open_tab(user, desk, "Keys")
    for action in ACTIONS:
        await user.should_see(marker=f"key-{action.id}")
    await user.should_see("Ctrl+Enter")
    await user.should_see("Rotate to the target")


async def test_record_a_new_key(user: User, desk: Desk) -> None:
    from beam_navigator.core.keymap import stored

    await open_tab(user, desk, "Keys")
    user.find(marker="key-change-rotate").click()
    await user.should_see("Press the new key for Rotate to the target")
    press(user, "F9")
    await eventually(lambda: stored(desk.keymap()["rotate"]) == "F9")
    await user.should_see("F9")


async def test_refused_key_keeps_listening(user: User, desk: Desk) -> None:
    from beam_navigator.core.keymap import DEFAULTS

    await open_tab(user, desk, "Keys")
    user.find(marker="key-change-rotate").click()
    press(user, "KeyR", ctrl=True)
    await user.should_see("The browser keeps Ctrl+R for itself.")
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]
    press(user, "Escape")
    await user.should_not_see("Press the new key for Rotate to the target")
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]


async def test_reset_one_and_all(user: User, desk: Desk) -> None:
    from beam_navigator.core.keymap import DEFAULTS, parse_chord

    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("log", parse_chord("F2"))
    await open_tab(user, desk, "Keys")
    user.find(marker="key-reset-rotate").click()
    await eventually(lambda: desk.keymap()["rotate"] == DEFAULTS["rotate"])
    assert desk.keymap()["log"] != DEFAULTS["log"]
    user.find(marker="keys-reset-all").click()
    await eventually(lambda: desk.keymap() == DEFAULTS)


async def test_discarded_keys_notice(user: User, desk: Desk) -> None:
    desk.settings.set("keymap", "{not json")
    await open_tab(user, desk, "Keys")
    await user.should_see("Some saved keys were not valid and were reset to their defaults.")


# Data: backup and restore (decision 34) ------------------------------------------------


@pytest.fixture
def file_desk(tmp_path: Path, fake: FakeRotator) -> Iterator[Desk]:
    connection = open_db(tmp_path / "beamnav.db")
    service = RotateService(connection, adapter_for=lambda p: fake, tester_for=lambda p: fake)
    yield Desk(connection, service)
    connection.close()


def add_station(desk: Desk, callsign: str) -> None:
    desk.stations.save(Station(callsign, None, "FM29pt", None, None, "saved", ""))


def dialog_open(user: User) -> bool:
    dialog = element(user, "restore-dialog")
    assert isinstance(dialog, ui.dialog)
    return bool(dialog.value)


async def upload_backup(user: User, data: bytes) -> None:
    upload = element(user, "backup-restore")
    assert isinstance(upload, ui.upload)
    await upload.handle_uploads(
        [ui.upload.SmallFileUpload("beamnav-backup.db", "application/octet-stream", data)]
    )


async def test_backup_downloads(user: User, file_desk: Desk) -> None:
    await open_tab(user, file_desk, "Data")
    user.find(marker="backup-download").click()
    response = await user.download.next()
    assert response.content.startswith(b"SQLite format 3\x00")


async def test_restore_after_confirm(user: User, file_desk: Desk, fake: FakeRotator) -> None:
    _, data = file_desk.backup()
    add_station(file_desk, "K2NEW")
    await open_tab(user, file_desk, "Data")
    await upload_backup(user, data)
    await eventually(lambda: dialog_open(user))
    await user.should_see("Restore replaces all your stations")
    await user.should_see("put in simulation mode")
    user.find(marker="restore-confirm").click()
    await user.should_see("Restored.")
    await user.should_see("Rotators are back in simulation")
    assert file_desk.stations.get("K2NEW") is None
    assert fake.moves == []


async def test_restore_cancel_changes_nothing(user: User, file_desk: Desk) -> None:
    _, data = file_desk.backup()
    add_station(file_desk, "K2NEW")
    await open_tab(user, file_desk, "Data")
    await upload_backup(user, data)
    await eventually(lambda: dialog_open(user))
    user.find(marker="restore-cancel").click()
    await eventually(lambda: not dialog_open(user))
    await user.should_not_see("Restored.")
    assert file_desk.stations.get("K2NEW") is not None
    assert not (file_desk.data_dir() / "backups").exists()  # type: ignore[operator]


async def test_restore_garbage_reports(user: User, file_desk: Desk) -> None:
    await open_tab(user, file_desk, "Data")
    await upload_backup(user, b"\x00garbage")
    await user.should_see("This is not a Beam Navigator backup.")
    assert not dialog_open(user)


async def test_restore_redraws_the_page(user: User, file_desk: Desk) -> None:
    # Final review I3: the page that restored must not keep showing "Live".
    repo = RotatorRepository(file_desk.conn)
    profile = repo.save(
        RotatorProfile(None, "Tower", "pstrotator", "127.0.0.1", 12000, 0, 360, 0, None, (),
                       False, False)  # fmt: skip
    )
    assert profile.id is not None
    repo.record_connection_test(profile.id, True)
    repo.set_live(profile.id, True)
    _, data = file_desk.backup()
    await open_tab(user, file_desk, "Data")
    switch = element(user, f"live-{profile.id}")
    assert isinstance(switch, ui.switch) and switch.value
    await upload_backup(user, data)
    await eventually(lambda: dialog_open(user))
    user.find(marker="restore-confirm").click()
    await user.should_see("Rotators are back in simulation")
    await eventually(lambda: element(user, f"live-{profile.id}") is not switch)
    redrawn = element(user, f"live-{profile.id}")
    assert isinstance(redrawn, ui.switch) and not redrawn.value
    await user.should_see(SIMULATION_LABEL)
