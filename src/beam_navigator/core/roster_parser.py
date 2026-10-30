"""Deterministic roster parser (requirements 4.3, 7).

Lines are matched against the record shapes seen in real net rosters. Anything
that is not a record is narrative; a non-record line between records becomes an
"unparsed text" row. Rows are flagged, never invented or dropped.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from beam_navigator.core.callsign import base_callsign, is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import is_grid

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class RosterRow:
    line: int
    text: str
    sequence: int | None = None
    callsign: str | None = None
    name: str | None = None
    qth: str | None = None
    grid: str | None = None
    published_bearing: str | None = None
    is_controller: bool = False
    confidence: Confidence = "low"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    rows: tuple[RosterRow, ...]
    controller: str | None
    stated_checkins: int | None
    stated_grids: int | None
    warnings: tuple[str, ...]

    @property
    def checkins(self) -> tuple[RosterRow, ...]:
        return tuple(row for row in self.rows if row.callsign is not None)


@dataclass(frozen=True)
class _Record:
    start: int  # index into lines
    length: int  # lines consumed
    rows: tuple[RosterRow, ...]


_NUMBERED = re.compile(r"(\d{1,3})[.)]?\s*(\S+)(?:\s+(.*))?")
_TAG_WORDS = re.compile(
    r"[-–]?\s*[(\[]?\s*net\s*control(?:\s+station)?\s*[)\]]?$", re.IGNORECASE
)
_TAG_SHORT = re.compile(r"NCS?", re.IGNORECASE)
_TAG_BRACKETED = re.compile(r"[(\[]NCS?[)\]]", re.IGNORECASE)
_BEARING = re.compile(r"\d{1,3}(?:\.\d+)?°")
_BEARING_AFTER_GRID = re.compile(r"\d{1,3}(?:\.\d+)?°?")  # the ° is sometimes lost
_MAX_WORDS_AFTER_GRID = 3
_EDGE_LINE_MAX_WORDS = 6
_STATED_CHECKINS = re.compile(r"\b(\d+)\s+(?:check-?ins|stations)\b", re.IGNORECASE)
_STATED_GRIDS = re.compile(r"\b(\d+)\s+grids\b", re.IGNORECASE)
_SIGN_OFF = re.compile(r"73\b")


def _is_link(word: str) -> bool:
    # Plain string checks, not a regex: a long unbroken paste must stay linear.
    if "://" in word:
        return True
    at = word.find("@")
    return at > 0 and "." in word[at + 1 :]


def _normalize(text: str) -> list[str]:
    lines = []
    for raw in text.replace("﻿", "").splitlines():
        line = "".join(" " if c.isspace() else c for c in raw)
        lines.append(" ".join(word for word in line.split(" ") if not _is_link(word)).strip())
    return lines


def _split_tag(text: str) -> tuple[str, bool]:
    """Remove a trailing controller tag. A bare NC right after a comma is a state."""
    match = _TAG_WORDS.search(text)
    if match:
        return text[: match.start()].rstrip(), True
    words = text.split()
    if words and _TAG_BRACKETED.fullmatch(words[-1]):
        return " ".join(words[:-1]), True
    after_comma = len(words) > 1 and words[-2].endswith(",")
    if words and _TAG_SHORT.fullmatch(words[-1]) and not after_comma:
        return " ".join(words[:-1]), True
    return text, False


def _numbered(lines: list[str], i: int, end: int) -> _Record | None:
    """N[.)] CALL NAME QTH... [GRID] [B°] [TAG] — N3RG, WB2RVX."""
    match = _NUMBERED.fullmatch(lines[i])
    if match is None or not is_callsign(match[2]):
        return None
    rest, tagged = _split_tag(match[3] or "")
    words = rest.split()
    bearing = grid = None
    warnings: tuple[str, ...] = ()
    # The grid is usually last, but a bearing or stray word may follow it.
    first_candidate = max(1, len(words) - 1 - _MAX_WORDS_AFTER_GRID)
    grid_at = next(
        (j for j in range(len(words) - 1, first_candidate - 1, -1) if is_grid(words[j])), None
    )
    if grid_at is not None:
        tail = words[grid_at + 1 :]
        grid = words[grid_at]
        words = words[:grid_at]
        if tail and _BEARING_AFTER_GRID.fullmatch(tail[0]):
            bearing = tail.pop(0)
        if tail:
            warnings = (f"Extra text: {' '.join(tail)}",)
    elif words and _BEARING.fullmatch(words[-1]):
        bearing = words.pop()
    name = words.pop(0) if words else None
    row = RosterRow(
        line=i + 1,
        text=lines[i],
        callsign=normalize_callsign(match[2]),
        sequence=int(match[1]),
        name=name,
        qth=" ".join(words) or None,
        grid=grid,
        published_bearing=bearing,
        is_controller=tagged,
        warnings=warnings,
    )
    return _Record(i, 1, (row,))


def _multiline(lines: list[str], i: int, end: int) -> _Record | None:
    """CALL [TAG] / NAME / QTH GRID on three lines — W2KV."""
    if i + 2 >= end:
        return None
    call_text, tagged = _split_tag(lines[i])
    name_words = lines[i + 1].split()
    place_words = lines[i + 2].split()
    if not (
        is_callsign(call_text)
        and len(name_words) == 1
        and name_words[0].isalpha()
        and len(place_words) >= 2
        and is_grid(place_words[-1])
    ):
        return None
    row = RosterRow(
        line=i + 1,
        text="\n".join(lines[i : i + 3]),
        callsign=normalize_callsign(call_text),
        name=name_words[0],
        qth=" ".join(place_words[:-1]),
        grid=place_words[-1],
        is_controller=tagged,
    )
    return _Record(i, 3, (row,))


def _name_first_fields(line: str) -> tuple[str, str, bool] | None:
    text, tagged = _split_tag(line)
    words = text.split()
    if len(words) < 2 or not is_callsign(words[-1]):
        return None
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", word) for word in words[:-1]):
        return None
    return " ".join(words[:-1]), words[-1], tagged


def _name_first(lines: list[str], i: int, end: int) -> _Record | None:
    """NAME CALL [TAG] — KA3WXV. Only in a run of two or more, so a lone
    sign-off such as "Phil WA3NUF" is not a check-in."""
    fields = _name_first_fields(lines[i])
    if fields is None:
        return None
    before = i > 0 and _name_first_fields(lines[i - 1]) is not None
    after = i + 1 < end and _name_first_fields(lines[i + 1]) is not None
    if not (before or after):
        return None
    name, call, tagged = fields
    row = RosterRow(
        line=i + 1,
        text=lines[i],
        callsign=normalize_callsign(call),
        name=name,
        is_controller=tagged,
    )
    return _Record(i, 1, (row,))


def _call_grid_list(lines: list[str], i: int, end: int) -> _Record | None:
    """CALL GRID [TAG], one or more per line separated by commas — KC3BVL, WA3NUF.

    A call without its grid is kept (flagged later) as long as the line holds at
    least one complete CALL GRID pair."""
    rows = []
    for item in lines[i].split(","):
        if not item.strip():
            continue
        text, tagged = _split_tag(item.strip())
        words = text.split()
        if not (1 <= len(words) <= 2 and is_callsign(words[0])):
            return None
        if len(words) == 2 and not is_grid(words[1]):
            return None
        rows.append(
            RosterRow(
                line=i + 1,
                text=lines[i],
                callsign=normalize_callsign(words[0]),
                grid=words[1] if len(words) == 2 else None,
                is_controller=tagged,
            )
        )
    if not any(row.grid for row in rows):
        return None
    return _Record(i, 1, tuple(rows))


_FORMATS: list[Callable[[list[str], int, int], _Record | None]] = [
    _numbered,
    _call_grid_list,
    _multiline,
    _name_first,
]


def _match_at(lines: list[str], i: int, end: int) -> _Record | None:
    for format_ in _FORMATS:
        record = format_(lines, i, end)
        if record is not None:
            return record
    return None


def _finish(row: RosterRow) -> RosterRow:
    if row.callsign is None:
        return replace(row, confidence="low", warnings=("Unparsed text",))
    if row.grid is None:
        return replace(row, confidence="medium", warnings=(*row.warnings, "Grid missing"))
    return replace(row, confidence="high")


def _looks_like_broken_entry(chunk: list[str]) -> bool:
    """A short paragraph that starts with a callsign: a roster entry the formats
    did not recognise, not narrative."""
    return (
        bool(chunk)
        and is_callsign(chunk[0].split()[0])
        and all(len(line.split()) <= _EDGE_LINE_MAX_WORDS for line in chunk)
    )


def _edge_chunk(lines: list[str], edge: int, step: int, limit: int) -> tuple[int, int] | None:
    """The paragraph next to a block edge, as (first, last) line indexes, or None.
    step is -1 to look above the block, +1 below; limit is the first index not to cross."""
    i = edge + step
    while i != limit and not lines[i]:
        i += step
    if i == limit:
        return None
    j = i
    while j + step != limit and lines[j + step]:
        j += step
    first, last = min(i, j), max(i, j)
    return (first, last) if _looks_like_broken_entry(lines[first : last + 1]) else None


def _block_rows(lines: list[str], records: list[_Record], low: int, high: int) -> list[RosterRow]:
    """One block of records (between sign-offs, lines low..high-1) in order, plus an
    unparsed row for every other non-blank line between its first and last record
    and for any broken-looking entries just above or below it."""
    by_start = {record.start: record for record in records}
    start = records[0].start
    stop = records[-1].start + records[-1].length
    while (chunk := _edge_chunk(lines, start, -1, low - 1)) is not None:
        start = chunk[0]
    while (chunk := _edge_chunk(lines, stop - 1, 1, high)) is not None:
        stop = chunk[1] + 1
    rows: list[RosterRow] = []
    i = start
    while i < stop:
        record = by_start.get(i)
        if record is not None:
            rows.extend(record.rows)
            i += record.length
            continue
        if lines[i]:
            rows.append(RosterRow(line=i + 1, text=lines[i]))
        i += 1
    return rows


def _flag_duplicates(rows: list[RosterRow]) -> list[RosterRow]:
    first_seen: dict[str, int] = {}
    flagged = []
    for index, row in enumerate(rows):
        if row.callsign is not None:
            key = base_callsign(row.callsign)
            if key in first_seen:
                note = f"Duplicate of row {first_seen[key] + 1}"
                row = replace(row, warnings=(*row.warnings, note))
            else:
                first_seen[key] = index
        flagged.append(row)
    return flagged


def parse_roster(text: str) -> ParseResult:
    lines = _normalize(text)
    end = len(lines)
    # A sign-off ("73 de ...") closes the current block; a second pasted roster
    # after it starts a new one.
    blocks: list[tuple[int, int, list[_Record]]] = []
    low, current = 0, []
    i = 0
    while i < end:
        record = _match_at(lines, i, end) if lines[i] else None
        if record is not None:
            current.append(record)
            i += record.length
            continue
        if _SIGN_OFF.match(lines[i]):
            blocks.append((low, i, current))
            low, current = i + 1, []
        i += 1
    blocks.append((low, end, current))

    block_rows = [row for b_low, b_high, recs in blocks if recs
                  for row in _block_rows(lines, recs, b_low, b_high)]  # fmt: skip
    rows = _flag_duplicates([_finish(row) for row in block_rows])

    warnings: list[str] = []
    controllers = [row.callsign for row in rows if row.is_controller]
    if len(controllers) > 1:
        warnings.append("More than one controller tag.")

    joined = "\n".join(lines)
    checkins_match = _STATED_CHECKINS.search(joined)
    grids_match = _STATED_GRIDS.search(joined)
    stated_checkins = int(checkins_match[1]) if checkins_match else None
    stated_grids = int(grids_match[1]) if grids_match else None
    parsed = sum(row.callsign is not None for row in rows)
    if stated_checkins is not None and stated_checkins != parsed:
        warnings.append(f"Text says {stated_checkins} check-ins; {parsed} parsed.")
    if stated_grids is not None:
        grids = {row.grid[:4].upper() for row in rows if row.grid}
        if stated_grids != len(grids):
            warnings.append(f"Text says {stated_grids} grids; {len(grids)} parsed.")

    return ParseResult(
        rows=tuple(rows),
        controller=controllers[0] if controllers else None,
        stated_checkins=stated_checkins,
        stated_grids=stated_grids,
        warnings=tuple(warnings),
    )
