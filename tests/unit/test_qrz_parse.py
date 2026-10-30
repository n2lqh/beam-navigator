"""QRZ XML replies, read from the five examples in the owner-supplied spec 1.34 fixture."""

from dataclasses import replace

import pytest

from beam_navigator.core.qrz import MAX_REPLY, Precision, page_url, parse_response


def test_login_example(qrz_examples: list[bytes]) -> None:
    reply = parse_response(qrz_examples[0])
    assert reply.session.key == "2331uf894c4bd29f3923f3bacf02c532d7bd9"
    assert reply.session.count == 123
    assert reply.session.sub_exp == "Wed Jan 1 12:34:03 2013"
    assert reply.session.error is None and reply.record is None


def test_callsign_example(qrz_examples: list[bytes]) -> None:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    assert record.call == "AA7BQ"
    assert record.name == 'FRED "The Boss" LLOYD'
    assert record.grid == "DM32af"
    assert record.qth == "SCOTTSDALE, AZ"
    assert (record.lat, record.lon) == (34.23456, -112.34356)
    assert record.geoloc == "user" and record.precision == "station"


def test_name_without_name_fmt(qrz_examples: list[bytes]) -> None:
    text = qrz_examples[1].replace(b'<name_fmt>FRED "The Boss" LLOYD</name_fmt>', b"")
    record = parse_response(text).record
    assert record is not None and record.name == "FRED L LLOYD"


def test_dxcc_example_has_no_record(qrz_examples: list[bytes]) -> None:
    reply = parse_response(qrz_examples[2])
    assert reply.record is None
    assert reply.session.key == "d0cf9d7b3b937ed5f5de28ddf5a0122d"


def test_not_found_example(qrz_examples: list[bytes]) -> None:
    reply = parse_response(qrz_examples[3])
    assert reply.session.error == "Not found: g1srdd"
    assert reply.session.key == "1232u4eaf13b8336d61982c1fd1099c9a38ac"


def test_session_timeout_example(qrz_examples: list[bytes]) -> None:
    reply = parse_response(qrz_examples[4])
    assert reply.session.error == "Session Timeout" and reply.session.key is None


@pytest.mark.parametrize(
    ("geoloc", "precision"),
    [
        ("user", "station"),
        ("grid", "station"),
        ("geocode", "address"),
        ("zip", "approximate"),
        ("state", "approximate"),
        ("dxcc", "approximate"),
        ("none", "none"),
        (None, "none"),
    ],
)
def test_precision_from_geoloc(
    qrz_examples: list[bytes], geoloc: str | None, precision: Precision
) -> None:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    assert replace(record, geoloc=geoloc).precision == precision


def test_bad_grid_dropped(qrz_examples: list[bytes]) -> None:
    text = qrz_examples[1].replace(b"<grid>DM32af</grid>", b"<grid>ZZ99</grid>")
    record = parse_response(text).record
    assert record is not None and record.grid is None


@pytest.mark.parametrize("data", [b"", b"<html>", b"\x00", b" " * (MAX_REPLY + 1)])
def test_unreadable_replies(data: bytes) -> None:
    with pytest.raises(ValueError, match="QRZ sent a reply Beam Navigator cannot read."):
        parse_response(data)


def test_other_root_refused() -> None:
    with pytest.raises(ValueError, match="cannot read"):
        parse_response(b"<html><body>Not QRZ</body></html>")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"<lat>34.23456</lat>", b"<lat>nan</lat>"),
        (b"<lat>34.23456</lat>", b"<lat>999</lat>"),
        (b"<lon>-112.34356</lon>", b"<lon>inf</lon>"),
        (b"<lon>-112.34356</lon>", b"<lon>-181</lon>"),
    ],
)
def test_impossible_position_dropped(
    qrz_examples: list[bytes], old: bytes, new: bytes
) -> None:  # review I2: never invent a location (invariant 5)
    record = parse_response(qrz_examples[1].replace(old, new)).record
    assert record is not None and (record.lat, record.lon) == (None, None)
    assert record.grid == "DM32af"  # the grid is checked on its own


def test_page_url() -> None:  # owner, 2026-10-29: Look up on QRZ opens the QRZ.com page
    assert page_url(" k2wb ") == "https://www.qrz.com/db/K2WB"
    assert page_url("FN20ok") is None and page_url("") is None
    assert page_url("K1X/P") == "https://www.qrz.com/db/K1X%2FP"
