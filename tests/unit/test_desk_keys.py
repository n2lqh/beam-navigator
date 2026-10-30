"""The keymap saved as the operator's overrides only (spec 4.5; decision 33)."""

import json
import sqlite3
from collections.abc import Iterator

import pytest

from beam_navigator.core.keymap import DEFAULTS, parse_chord, stored
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db


@pytest.fixture
def desk() -> Iterator[Desk]:
    conn: sqlite3.Connection = open_db(":memory:")
    yield Desk(conn, RotateService(conn))
    conn.close()


def test_default_keymap(desk: Desk) -> None:
    assert desk.keymap() == DEFAULTS and not desk.keymap_discarded()


def test_set_key_stores_only_the_override(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    assert json.loads(desk.settings.get("keymap") or "{}") == {"rotate": "F9"}
    assert stored(desk.keymap()["rotate"]) == "F9"


def test_set_key_refused_keeps_the_old_binding(desk: Desk) -> None:
    with pytest.raises(ValueError, match="already used for Snap back to net control"):
        desk.set_key("rotate", parse_chord("Home"))
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]
    with pytest.raises(ValueError, match="Unknown action nonsense."):
        desk.set_key("nonsense", parse_chord("F9"))


def test_setting_a_default_back_drops_the_override(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("rotate", parse_chord("Ctrl+Enter"))
    assert json.loads(desk.settings.get("keymap") or "{}") == {}


def test_reset(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("log", parse_chord("F2"))
    desk.reset_key("rotate")
    assert json.loads(desk.settings.get("keymap") or "{}") == {"log": "F2"}
    desk.reset_key(None)
    assert desk.keymap() == DEFAULTS


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '{"rotate": 5}', '{"rotate": "Home"}'])
def test_corrupt_setting_falls_back(desk: Desk, raw: str) -> None:
    desk.settings.set("keymap", raw)
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]
    assert desk.keymap_discarded()


def test_two_step_swap_is_kept(desk: Desk) -> None:  # final review C2
    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("snap_back", parse_chord("Ctrl+Enter"))
    desk.set_key("rotate", parse_chord("Home"))
    keymap = desk.keymap()
    assert stored(keymap["rotate"]) == "Home" and stored(keymap["snap_back"]) == "Ctrl+Enter"
    assert not desk.keymap_discarded()


def test_reset_refused_when_it_would_clash(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("snap_back", parse_chord("Ctrl+Enter"))
    with pytest.raises(ValueError, match=r"Ctrl\+Enter is already used for Snap back"):
        desk.reset_key("rotate")
    assert stored(desk.keymap()["rotate"]) == "F9"


def test_saved_ctrl_n_falls_back(desk: Desk) -> None:
    # An override saved before Ctrl+N was refused is dropped, and Settings says so.
    desk.settings.set("keymap", '{"note": "Ctrl+KeyN"}')
    assert stored(desk.keymap()["note"]) == "Alt+KeyN"
    assert desk.keymap_discarded()
