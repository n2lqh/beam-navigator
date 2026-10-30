"""Roster import review (requirements 4.3): parse, let the operator edit, then save.

Bearings shown here are from the operator's station; a roster's printed bearings stay
in their own field (invariant 3). The raw text is saved unchanged, including rows the
operator left out (invariant 9).
"""

import math
import sqlite3
from dataclasses import dataclass, field, replace

from beam_navigator.core.maidenhead import is_grid
from beam_navigator.core.models import Net, Session
from beam_navigator.core.roster_parser import ParseResult, parse_roster
from beam_navigator.desk import Desk
from beam_navigator.store.repositories import BandRepository, NetRepository


@dataclass
class ReviewRow:
    index: int
    line_text: str
    sequence: int | None
    callsign: str | None
    name: str | None
    qth: str | None
    grid: str | None
    published: str | None
    include: bool
    is_controller: bool
    warnings: list[str] = field(default_factory=list)
    from_you: str | None = None
    distance: str | None = None
    # A different grid learned from an earlier roster: the operator chooses whether this
    # roster's grid replaces it (owner, 2026-10-29; decision 40). Never set for a grid
    # the operator saved, which a roster never changes (decision 13).
    earlier_grid: str | None = None
    replace_grid: bool = False


@dataclass
class Review:
    raw_text: str
    rows: list[ReviewRow]
    warnings: list[str]
    controller_suggested: bool
    parsed: ParseResult = field(repr=False)  # the parser's rows, kept for saving


class RosterReview:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None:
        self._nets = NetRepository(conn)
        self._bands = BandRepository(conn)
        self._desk = desk

    def create_net(
        self, name: str, band: str | None, frequency_text: str, channel: str
    ) -> Net:
        """The import dialog's New net: a name, and a frequency or a channel such as a
        DMR talkgroup (spec 3)."""
        clean = name.strip()
        if not clean:
            raise ValueError("A net needs a name.")
        # Same rule as NetBook.name_taken: names are unique ignoring case and spaces.
        if any(net.name.strip().casefold() == clean.casefold()
               for net in self._nets.list_nets()):  # fmt: skip
            raise ValueError(f"A net called {clean} already exists.")
        if band is not None and self._bands.get(band) is None:
            raise ValueError(f"Unknown band {band!r}.")
        frequency = None
        if frequency_text.strip():
            try:
                frequency = float(frequency_text)
            except ValueError as exc:
                raise ValueError(f"Frequency {frequency_text.strip()!r} is not a number.") from exc
            if not (math.isfinite(frequency) and frequency > 0):
                raise ValueError("Frequency must be a positive number of MHz.")
        return self._nets.save_net(
            Net(None, clean, None, None, None, frequency, channel.strip() or None, None, band,
                None, None, False)  # fmt: skip
        )

    def parse(self, text: str) -> Review:
        parsed = parse_roster(text)
        conflicts = self._nets.saved_grid_conflicts(parsed)
        rows = []
        for index, row in enumerate(parsed.rows):
            review_row = ReviewRow(
                index=index,
                line_text=row.text,
                sequence=row.sequence,
                callsign=row.callsign,
                name=row.name,
                qth=row.qth,
                grid=row.grid,
                published=row.published_bearing,
                include=row.callsign is not None,
                is_controller=row.is_controller,
                warnings=list(row.warnings),
            )
            if index in conflicts:
                review_row.warnings.append(conflicts[index])
                known = self._desk.stations.get(row.callsign or "")
                if known is not None and known.source == "roster":
                    review_row.earlier_grid = known.grid
            self.recompute(review_row)
            rows.append(review_row)
        suggested = any(row.is_controller for row in parsed.rows)
        return Review(text, rows, list(parsed.warnings), suggested, parsed)

    def recompute(self, row: ReviewRow) -> None:
        """Bearing and distance from the operator, after a grid edit."""
        found = self._desk.bearing_to(row.grid)
        row.from_you = None if found is None else found.text
        row.distance = None if found is None else found.distance_text

    @staticmethod
    def set_controller(review: Review, index: int | None) -> None:
        for row in review.rows:
            row.is_controller = row.index == index and row.callsign is not None

    def duplicate_of(self, net_id: int, date: str, review: Review) -> int | None:
        return self._nets.find_identical_import(net_id, date, review.raw_text)

    def save(
        self, net_id: int, date: str, review: Review, replace_session_id: int | None = None
    ) -> Session:
        kept = []
        for row in review.rows:
            if not (row.include and row.callsign is not None):
                continue  # unparsed text and excluded rows stay only in the raw text
            grid = (row.grid or "").strip() or None
            if grid is not None and not is_grid(grid):
                label = row.sequence if row.sequence is not None else row.index + 1
                raise ValueError(f"Row {label}: {grid!r} is not a grid square.")
            original = review.parsed.rows[row.index]
            kept.append(
                replace(
                    original,
                    name=(row.name or "").strip() or None,
                    qth=(row.qth or "").strip() or None,
                    grid=grid,
                    is_controller=row.is_controller,
                )
            )
        result = replace(review.parsed, rows=tuple(kept))
        # The controller is kept even when its row is left out of the check-ins.
        chosen = next((r for r in review.rows if r.is_controller and r.callsign), None)
        controller = None
        if chosen is not None:
            grid = (chosen.grid or "").strip() or None
            if grid is not None and not is_grid(grid):
                raise ValueError(f"Controller {chosen.callsign}: {grid!r} is not a grid square.")
            controller = replace(review.parsed.rows[chosen.index], grid=grid, is_controller=True)
        replace_grids = {
            row.callsign: grid
            for row in review.rows
            if row.include and row.callsign and row.earlier_grid and row.replace_grid
            and (grid := (row.grid or "").strip())
        }  # fmt: skip
        return self._nets.import_roster(
            net_id, date, review.raw_text, result, replace_session_id, controller=controller,
            replace_grids=replace_grids,
        )  # fmt: skip
