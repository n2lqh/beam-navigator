"""QRZ XML Data replies, spec 1.34 (requirements 4.9; tests/fixtures/qrz_xml_spec_1.34.txt).

Pure: bytes in, dataclasses out. Following the spec, nodes are matched by name and anything
unknown is ignored. Python 3.12+ ships expat with entity-amplification limits, and replies
are capped at MAX_REPLY bytes.
"""

import math
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from beam_navigator.core.callsign import is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import is_grid

MAX_REPLY = 200_000
UNREADABLE = "QRZ sent a reply Beam Navigator cannot read."
Precision = Literal["station", "address", "approximate", "none"]
# The spec's "About Lat/Long and Grid Data": where QRZ's position came from.
_PRECISION: dict[str, Precision] = {
    "user": "station",
    "grid": "station",
    "geocode": "address",
    "zip": "approximate",
    "state": "approximate",
    "dxcc": "approximate",
}


@dataclass(frozen=True)
class QrzSession:
    key: str | None
    count: int | None
    sub_exp: str | None
    message: str | None
    error: str | None


@dataclass(frozen=True)
class QrzRecord:
    call: str
    name: str | None
    grid: str | None
    qth: str | None
    lat: float | None
    lon: float | None
    geoloc: str | None

    @property
    def precision(self) -> Precision:
        return _PRECISION.get((self.geoloc or "").strip().lower(), "none")


@dataclass(frozen=True)
class QrzResponse:
    session: QrzSession
    record: QrzRecord | None


def page_url(callsign: str) -> str | None:
    """The station's QRZ.com page, for the browser; None for anything not a callsign."""
    call = normalize_callsign(callsign)
    return f"https://www.qrz.com/db/{quote(call, safe='')}" if is_callsign(call) else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fields(node: ElementTree.Element) -> dict[str, str]:
    """Child text by local tag name; blank text counts as absent."""
    return {
        _local(child.tag): child.text.strip()
        for child in node
        if child.text is not None and child.text.strip()
    }


def _number(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _real_position(lat: float | None, lon: float | None) -> bool:
    return (
        lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon)
        and abs(lat) <= 90 and abs(lon) <= 180
    )  # fmt: skip


def _record(fields: dict[str, str]) -> QrzRecord | None:
    call = fields.get("call")
    if not call:
        return None
    name = fields.get("name_fmt") or " ".join(
        part for part in (fields.get("fname"), fields.get("name")) if part
    )
    place = fields.get("addr2")
    region = fields.get("state") or fields.get("country")
    qth = ", ".join(part for part in (place, region) if part)
    grid = fields.get("grid")
    lat, lon = _number(fields.get("lat")), _number(fields.get("lon"))
    if not _real_position(lat, lon):
        lat = lon = None  # never invent a location from a bad number (invariant 5)
    return QrzRecord(
        call=call.upper(),
        name=name or None,
        grid=grid if grid and is_grid(grid) else None,
        qth=qth or None,
        lat=lat,
        lon=lon,
        geoloc=fields.get("geoloc"),
    )


def parse_response(data: bytes) -> QrzResponse:
    if len(data) > MAX_REPLY:
        raise ValueError(UNREADABLE)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise ValueError(UNREADABLE) from exc
    if _local(root.tag) != "QRZDatabase":
        raise ValueError(UNREADABLE)
    session: dict[str, str] = {}
    record = None
    for node in root:
        if _local(node.tag) == "Session":
            session = _fields(node)
        elif _local(node.tag) == "Callsign":
            record = _record(_fields(node))
    count = session.get("Count")
    return QrzResponse(
        QrzSession(
            key=session.get("Key"),
            count=int(count) if count is not None and count.isdigit() else None,
            sub_exp=session.get("SubExp"),
            message=session.get("Message"),
            error=session.get("Error"),
        ),
        record,
    )
