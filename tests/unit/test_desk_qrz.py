"""QRZ results on the dashboard: labelled, graded, and never overwriting (spec 4.9)."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from beam_navigator.core.models import OperatorProfile, Station
from beam_navigator.core.qrz import QrzRecord, parse_response
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import ProfileRepository

WHEN = "2026-10-28T20:00:00+00:00"


@pytest.fixture
def desk() -> Iterator[Desk]:
    conn: sqlite3.Connection = open_db(":memory:")
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "UTC", "NJ", False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    yield Desk(conn, RotateService(conn))
    conn.close()


@pytest.fixture
def aa7bq(qrz_examples: list[bytes]) -> QrzRecord:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    return record


def test_qrz_view_reads_cache(desk: Desk, aa7bq: QrzRecord) -> None:
    assert desk.qrz_view("AA7BQ") is None
    desk.qrz.save(aa7bq, WHEN)
    view = desk.qrz_view("aa7bq")
    assert view is not None
    assert view.source_text == "from QRZ, 2026-10-28"
    assert (view.name, view.grid, view.qth) == ('FRED "The Boss" LLOYD', "DM32af", "SCOTTSDALE, AZ")
    assert view.precision_text == "Location entered by the station on QRZ."
    assert view.can_use


def test_qrz_store_saves_and_returns_view(desk: Desk, aa7bq: QrzRecord) -> None:
    view = desk.qrz_store(aa7bq, "limited data")
    assert view.notice == "limited data"
    assert desk.qrz.get("AA7BQ") is not None


def test_look_up_with_qrz_labels_source(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(aa7bq, WHEN)
    view = desk.look_up_with_qrz("AA7BQ", None)
    assert view.title == "AA7BQ — QRZ" and view.bearing_deg is not None
    assert desk.stations.get("AA7BQ") is None  # nothing saved to stations


def test_qrz_never_overwrites_saved_grid(desk: Desk, aa7bq: QrzRecord) -> None:  # 36
    desk.stations.save(Station("AA7BQ", "FRED", "FN20ok", None, None, "saved", ""))
    desk.qrz_store(aa7bq, None)
    record = desk.stations.get("AA7BQ")
    assert record is not None and record.grid == "FN20ok"
    view = desk.look_up("AA7BQ", None)
    assert view.title is not None and "QRZ" not in view.title
    assert view.bearing_deg == desk.look_up("FN20ok", None).bearing_deg


def test_address_precision_noted(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(replace(aa7bq, geoloc="geocode"), WHEN)
    qrz = desk.qrz_view("AA7BQ")
    assert qrz is not None and qrz.can_use
    view = desk.look_up_with_qrz("AA7BQ", None)
    assert view.coarse_note == (
        "Location from the station's postal address; may not be where they operate."
    )


def test_approximate_location_labelled(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(replace(aa7bq, geoloc="state"), WHEN)
    qrz = desk.qrz_view("AA7BQ")
    assert qrz is not None and not qrz.can_use and qrz.grid is None  # never offered as a grid
    assert qrz.precision_text == "Approximate: QRZ only knows the zip code, state or country."
    view = desk.look_up_with_qrz("AA7BQ", None)
    assert view.title == "AA7BQ — QRZ (approximate)"
    assert view.coarse_note == qrz.precision_text and view.bearing_deg is not None


def test_no_location_no_bearing(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(replace(aa7bq, geoloc="none", lat=None, lon=None, grid=None), WHEN)
    qrz = desk.qrz_view("AA7BQ")
    assert qrz is not None and qrz.precision_text == "QRZ has no location for this station."
    view = desk.look_up_with_qrz("AA7BQ", None)
    assert view.bearing_deg is None and view.error == "QRZ has no location for this station."


def test_look_up_with_qrz_needs_a_lookup_first(desk: Desk) -> None:
    view = desk.look_up_with_qrz("K9ZZZ", None)
    assert view.error == "No QRZ result for K9ZZZ yet."


def test_qrz_auto_for_a_call_with_nothing_stored(desk: Desk) -> None:  # owner, 2026-10-29
    assert desk.qrz_auto("AA7BQ") is True


def test_no_qrz_auto_when_a_grid_is_saved(desk: Desk) -> None:
    desk.stations.save(Station("AA7BQ", "FRED", "DM32af", None, None, "saved", ""))
    assert desk.qrz_auto("aa7bq") is False


def test_qrz_auto_when_the_saved_record_has_no_grid(desk: Desk) -> None:
    desk.stations.save(Station("AA7BQ", "FRED", None, None, None, "saved", ""))
    assert desk.qrz_auto("AA7BQ") is True


def test_no_qrz_auto_when_qrz_already_answered(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(aa7bq, WHEN)
    assert desk.qrz_auto("AA7BQ") is False


def test_no_qrz_auto_when_switched_off(desk: Desk) -> None:
    desk.settings.set("qrz_auto", "off")
    assert desk.qrz_auto("AA7BQ") is False


def test_lookup_falls_back_to_a_usable_qrz_answer(desk: Desk, aa7bq: QrzRecord) -> None:
    assert desk.look_up_or_qrz("AA7BQ", None).needs_grid_for == "AA7BQ"
    desk.qrz.save(aa7bq, WHEN)
    view = desk.look_up_or_qrz("AA7BQ", None)
    assert view.title == "AA7BQ — QRZ" and view.bearing_deg is not None


def test_lookup_keeps_a_saved_grid_over_qrz(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.stations.save(Station("AA7BQ", "FRED", "FN20ok", None, None, "saved", ""))
    desk.qrz.save(aa7bq, WHEN)
    assert desk.look_up_or_qrz("AA7BQ", None).title == "AA7BQ — saved"


def test_lookup_never_falls_back_to_an_approximate_answer(
    desk: Desk, aa7bq: QrzRecord
) -> None:
    desk.qrz.save(replace(aa7bq, geoloc="zip"), WHEN)
    assert desk.look_up_or_qrz("AA7BQ", None).needs_grid_for == "AA7BQ"


def test_save_qrz_station_creates_a_record(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(aa7bq, WHEN)
    assert desk.can_save_qrz("AA7BQ")
    saved = desk.save_qrz_station("aa7bq")
    assert (saved.name, saved.grid, saved.qth, saved.source) == (
        'FRED "The Boss" LLOYD', "DM32af", "SCOTTSDALE, AZ", "saved"
    )
    assert desk.stations.get("AA7BQ") == saved
    assert not desk.can_save_qrz("AA7BQ")  # now stored


def test_save_qrz_station_fills_blanks_only(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.stations.save(Station("AA7BQ", "FRED", None, None, None, "saved", "Runs 1 kW"))
    desk.qrz.save(aa7bq, WHEN)
    saved = desk.save_qrz_station("AA7BQ")
    assert (saved.name, saved.grid, saved.qth, saved.notes) == (
        "FRED", "DM32af", "SCOTTSDALE, AZ", "Runs 1 kW"
    )


def test_save_qrz_station_refuses_an_approximate_answer(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(replace(aa7bq, geoloc="state"), WHEN)
    assert not desk.can_save_qrz("AA7BQ")
    with pytest.raises(ValueError, match="QRZ has no exact location for AA7BQ"):
        desk.save_qrz_station("AA7BQ")


def test_save_qrz_station_keeps_a_position_without_a_grid(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.qrz.save(replace(aa7bq, grid=None), WHEN)
    saved = desk.save_qrz_station("AA7BQ")
    assert saved.grid is None and saved.latlon is not None
    assert (saved.latlon.lat, saved.latlon.lon) == (34.23456, -112.34356)
    assert desk.look_up_or_qrz("AA7BQ", None).title == "AA7BQ — saved"


def test_qrz_missing_picks_incomplete_records(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.stations.add_from_roster("K1AAA", "AL", "FN20aa", None)  # complete
    desk.stations.add_from_roster("K1BBB", None, "FN20aa", None)  # no name
    desk.stations.add_from_roster("K1CCC", "CY", None, None)  # no grid
    desk.stations.add_from_roster("AA7BQ", None, None, None)  # QRZ already answered
    desk.qrz.save(aa7bq, WHEN)
    assert desk.qrz_missing(["K1AAA", "K1BBB", "K1CCC", "AA7BQ"]) == ["K1BBB", "K1CCC"]


def test_qrz_missing_respects_the_switch(desk: Desk) -> None:
    desk.stations.add_from_roster("K1BBB", None, "FN20aa", None)
    desk.settings.set("qrz_auto", "off")
    assert desk.qrz_missing(["K1BBB"]) == []
