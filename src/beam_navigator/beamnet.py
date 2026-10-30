"""*.beamnet.json, schema 1 (requirements 4.6; decision 26): net definitions only, never
ids, the archive flag, a rotator or history. Import adds new nets and never overwrites."""

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from beam_navigator.core.models import Net
from beam_navigator.core.schedule import WEEKDAYS
from beam_navigator.nets import NetBook, NetForm

FORMAT = "beamnet"
SCHEMA = 1
MAX_BYTES = 1_000_000
NOT_BEAMNET = "This is not a beamnet file"
EXISTS = "a net with this name already exists; not changed"
_TEXT_FIELDS = ("start_time", "timezone", "channel", "mode", "band",
                "default_controller_call", "default_controller_grid")  # fmt: skip


class BeamnetError(ValueError):
    pass


@dataclass(frozen=True)
class ImportReport:
    added: list[str]
    skipped: list[str]


def write_beamnet(nets: list[Net]) -> bytes:
    entries = [
        {
            "name": net.name,
            "weekday": WEEKDAYS[net.weekday] if net.weekday is not None else None,
            "start_time": net.start_time,
            "timezone": net.timezone,
            "frequency_mhz": net.frequency_mhz,
            "channel": net.channel,
            "mode": net.mode,
            "band": net.band,
            "default_controller_call": net.default_controller_call,
            "default_controller_grid": net.default_controller_grid,
            **({"unverified": True} if net.unverified else {}),
        }
        for net in nets
    ]
    document = {"format": FORMAT, "schema": SCHEMA, "nets": entries}
    return json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")


def _document(data: bytes) -> list[Any]:
    if len(data) > MAX_BYTES:
        raise BeamnetError(f"{NOT_BEAMNET}: it is larger than 1 MB.")
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:  # deep nesting too
        raise BeamnetError(f"{NOT_BEAMNET}: it is not readable JSON.") from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise BeamnetError(f"{NOT_BEAMNET}.")
    schema = document.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise BeamnetError(f"{NOT_BEAMNET}: its schema number is missing.")
    if schema > SCHEMA:
        raise BeamnetError(f"This file was made by a newer Beam Navigator (schema {schema}).")
    nets = document.get("nets")
    if not isinstance(nets, list):
        raise BeamnetError(f"{NOT_BEAMNET}: it has no list of nets.")
    return nets


def _form(entry: dict[str, Any]) -> NetForm | str:
    """The entry as a form, or the reason it cannot be one. Unknown keys are ignored."""
    name = entry.get("name")
    if not isinstance(name, str):
        return "name must be text"
    for key in _TEXT_FIELDS:
        if entry.get(key) is not None and not isinstance(entry[key], str):
            return f"{key} must be text"
    frequency = entry.get("frequency_mhz")
    if frequency is not None and (
        not isinstance(frequency, int | float) or isinstance(frequency, bool)
    ):
        return "frequency_mhz must be a number"
    day = entry.get("weekday")
    weekday = None
    if day is not None:
        if not isinstance(day, str) or day.strip().lower() not in WEEKDAYS:
            return f"unknown weekday {day!r}"
        weekday = WEEKDAYS.index(day.strip().lower())
    unverified = entry.get("unverified", False)
    if not isinstance(unverified, bool):
        return "unverified must be true or false"
    return NetForm(
        name=name,
        weekday=weekday,
        start_time=entry.get("start_time") or "",
        timezone=entry.get("timezone") or "",
        frequency=str(frequency) if frequency is not None else "",
        channel=entry.get("channel") or "",
        mode=entry.get("mode") or "",
        band=entry.get("band"),
        controller_call=entry.get("default_controller_call") or "",
        controller_grid=entry.get("default_controller_grid") or "",
        rotator_id=None,
        unverified=unverified,
    )


def read_beamnet(data: bytes) -> list[tuple[str, NetForm | str]]:
    """Raises BeamnetError for a bad file; a bad net comes back with its reason."""
    entries: list[tuple[str, NetForm | str]] = []
    for number, entry in enumerate(_document(data), start=1):
        label = f"net {number}"
        if not isinstance(entry, dict):
            entries.append((label, "not a net entry"))
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            label = name.strip()
        entries.append((label, _form(entry)))
    return entries


def import_beamnet(book: NetBook, data: bytes) -> ImportReport:
    added: list[str] = []
    skipped: list[str] = []
    for label, form in read_beamnet(data):
        if isinstance(form, str):
            skipped.append(f"{label}: {form}")
        elif form.name.strip() and book.name_taken(form.name):
            skipped.append(f"{label}: {EXISTS}")
        else:
            try:
                added.append(book.save(form).name)
            except ValueError as exc:
                skipped.append(f"{label}: {exc}")
    return ImportReport(added, skipped)


def beamnet_filename(nets: list[Net], today: date) -> str:
    if len(nets) != 1:
        return f"nets-{today.isoformat()}.beamnet.json"
    slug = re.sub(r"[^a-z0-9]+", "-", nets[0].name.lower()).strip("-")
    return f"{slug or 'net'}.beamnet.json"
