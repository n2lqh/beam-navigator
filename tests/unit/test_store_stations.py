from collections.abc import Iterator

import pytest

from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import LatLon, Station
from beam_navigator.core.targets import resolve
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import StationRepository


@pytest.fixture
def stations() -> Iterator[StationRepository]:
    conn = open_db(":memory:")
    yield StationRepository(conn)
    conn.close()


def saved(callsign: str, grid: str | None = "FN20ok", **extra: object) -> Station:
    fields: dict[str, object] = {
        "callsign": callsign, "name": "DAVE", "grid": grid, "qth": "HOPEWELL, NJ",
        "latlon": None, "source": "saved", "notes": "",
    }  # fmt: skip
    fields.update(extra)
    return Station(**fields)  # type: ignore[arg-type]


def test_callsign_case_gives_one_record(stations: StationRepository) -> None:  # Focus 2
    stations.save(saved("n2lqh", grid="FM29pt"))
    stations.save(saved("N2LQH", grid="FM29pt"))
    station = stations.get("n2lqh")
    assert station is not None and station.callsign == "N2LQH"
    assert stations.add_from_roster("N2LQH", "TERRY", "FM29pt", "TABERNACLE, NJ") is False


def test_roster_never_changes_a_saved_record(stations: StationRepository) -> None:  # spec 7
    assert stations.add_from_roster("K3WGR", "AL", "FN10xh", "WERNERSVILLE, PA") is True
    assert stations.add_from_roster("K3WGR", "AL", "FN10xi", "WERNERSVILLE, PA") is False
    station = stations.get("K3WGR")
    assert station is not None
    assert station.grid == "FN10xh"
    assert station.source == "roster"


def test_saved_station_feeds_resolver(stations: StationRepository) -> None:
    stations.save(saved("W2KV"))
    result = resolve("W2KV", stations=stations.lookup)
    assert result.location == grid_center("FN20ok")
    assert result.source == "saved"


def test_roster_station_feeds_resolver(stations: StationRepository) -> None:
    stations.add_from_roster("W2KV", "DAVE", "FN20OK", "HOPEWELL, NJ")
    result = resolve("w2kv", stations=stations.lookup)
    assert result.location == grid_center("FN20ok")
    assert result.source == "roster"


def test_exact_coordinates_kept(stations: StationRepository) -> None:
    stations.save(saved("W2KV", latlon=LatLon(40.44, -74.79)))
    assert resolve("W2KV", stations=stations.lookup).location == LatLon(40.44, -74.79)


def test_unknown_station_needs_grid(stations: StationRepository) -> None:  # invariant 5
    assert stations.lookup("K1ABC") is None
    assert resolve("K1ABC", stations=stations.lookup).needs_grid


def test_saving_overwrites_every_field(stations: StationRepository) -> None:
    stations.add_from_roster("AF3G", "GLEN", "FN20LE", "HOLLAND, PA")
    stations.save(saved("AF3G", grid=None, name="GLENN", qth=None))
    station = stations.get("AF3G")
    assert station is not None
    assert (station.name, station.grid, station.qth) == ("GLENN", None, None)
    assert station.source == "saved"
    assert resolve("AF3G", stations=stations.lookup).needs_grid


def test_non_ascii_round_trips(stations: StationRepository) -> None:  # Review Focus 5
    stations.save(saved("VE2XX", name="José", qth="Québec"))
    stations.set_notes("ve2xx", "🙂 good copy")
    station = stations.get("VE2XX")
    assert station is not None
    assert (station.name, station.qth, station.notes) == ("José", "Québec", "🙂 good copy")


def test_notes_for_unknown_station_rejected(stations: StationRepository) -> None:
    with pytest.raises(ValueError):
        stations.set_notes("K1ABC", "hello")
