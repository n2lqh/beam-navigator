"""The operator's nets (requirements 4.6): the edit form, duplicate, archive, the nets list
and each net's history view. Nothing here sends a rotator command (invariant 2)."""

import json
import math
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from importlib.resources import files
from typing import TYPE_CHECKING

from beam_navigator.core.callsign import is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import is_grid
from beam_navigator.core.models import Net, Participant, Session
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.core.schedule import (
    check_zone,
    next_occurrence,
    occurrence_text,
    parse_start_time,
    zone_for,
)
from beam_navigator.desk import Desk
from beam_navigator.store.repositories import NetRepository

if TYPE_CHECKING:
    from beam_navigator.beamnet import ImportReport

# The owner's published schedule (docs/example-nets-source.txt; decision 27).
EXAMPLE_NETS = files("beam_navigator") / "data" / "example_nets.beamnet.json"
EXAMPLE_SETTING = "example_nets"  # "added" or "declined": the offer is made once
# The owner's own rosters, copied byte for byte from tests/fixtures (decision 32).
EXAMPLE_ROSTERS = files("beam_navigator") / "data" / "example_rosters.json"


@dataclass(frozen=True)
class ExampleRoster:
    net: str  # the example net it belongs to
    date: str
    text: str  # raw roster text, as pasted


def example_rosters() -> list[ExampleRoster]:
    manifest = json.loads(EXAMPLE_ROSTERS.read_text(encoding="utf-8"))
    folder = files("beam_navigator") / "data" / "example_rosters"
    return [
        ExampleRoster(entry["net"], entry["date"],
                      (folder / entry["file"]).read_text(encoding="utf-8"))  # fmt: skip
        for entry in manifest["rosters"]
    ]


@dataclass(frozen=True)
class NetForm:
    """What the net form holds, as typed."""

    name: str
    weekday: int | None
    start_time: str
    timezone: str
    frequency: str
    channel: str
    mode: str
    band: str | None
    controller_call: str
    controller_grid: str
    rotator_id: int | None
    unverified: bool = False  # cleared when the operator ticks "I've checked these details"


@dataclass(frozen=True)
class NetSummary:
    net: Net
    next_text: str
    session_count: int


@dataclass(frozen=True)
class NetView:
    net: Net
    next_text: str
    controller_text: str
    sessions: list[tuple[Session, int]]
    participants: list[Participant]


def _key(name: str) -> str:
    return name.strip().casefold()


def _search_text(net: Net) -> str:
    # Full precision: ":g" would turn 1296.125 into 1296.12 and miss the search.
    frequency = repr(net.frequency_mhz) if net.frequency_mhz is not None else ""
    fields = (net.name, net.channel, frequency, net.band, net.default_controller_call)
    return "\n".join(field for field in fields if field).casefold()


def _blank(text: str) -> str | None:
    return text.strip() or None


class NetBook:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None:
        self.conn = conn
        self.desk = desk
        self.nets = NetRepository(conn)

    def form_for(self, net_id: int) -> NetForm:
        net = self.nets.get_net(net_id)
        return NetForm(
            name=net.name,
            weekday=net.weekday,
            start_time=net.start_time or "",
            timezone=net.timezone or "",
            frequency=f"{net.frequency_mhz:g}" if net.frequency_mhz is not None else "",
            channel=net.channel or "",
            mode=net.mode or "",
            band=net.band,
            controller_call=net.default_controller_call or "",
            controller_grid=net.default_controller_grid or "",
            rotator_id=net.rotator_id,
            unverified=net.unverified,
        )

    def name_taken(self, name: str, net_id: int | None = None) -> bool:
        return any(
            _key(net.name) == _key(name) and net.id != net_id for net in self.nets.list_nets()
        )

    def save(self, form: NetForm, net_id: int | None = None) -> Net:
        """Validates in a fixed order; the first problem raises ValueError with its reason."""
        name = form.name.strip()
        if not name:
            raise ValueError("A net needs a name.")
        if self.name_taken(name, net_id):
            raise ValueError(f"A net called {name} already exists.")
        if form.weekday is not None and not 0 <= form.weekday <= 6:
            raise ValueError("Weekday must be Monday to Sunday.")
        start_time = parse_start_time(form.start_time)
        timezone = check_zone(form.timezone)
        if (form.weekday is None) != (start_time is None):
            raise ValueError("Give both a weekday and a start time, or neither.")
        frequency = None
        if form.frequency.strip():
            try:
                frequency = float(form.frequency)
            except ValueError:
                frequency = math.nan
            if not (math.isfinite(frequency) and frequency > 0):
                raise ValueError("Frequency must be a positive number of MHz.")
        if form.band is not None and self.desk.bands.get(form.band) is None:
            raise ValueError(f"Unknown band {form.band!r}. Add it in Settings → Bands first.")
        call = normalize_callsign(form.controller_call) if form.controller_call.strip() else None
        if call is not None and not is_callsign(call):
            raise ValueError(f"{call!r} is not a callsign.")
        grid = _blank(form.controller_grid)
        if grid is not None and not is_grid(grid):
            raise ValueError(f"{grid!r} is not a grid square.")
        if form.rotator_id is not None:
            self.desk.rotator_profiles.get(form.rotator_id)  # raises "No rotator with id N."
        stored = self.nets.get_net(net_id) if net_id is not None else None
        archived = stored.archived if stored else False
        favourite = stored.favourite if stored else False  # a new net or a copy: unstarred
        return self.nets.save_net(
            Net(net_id, name, form.weekday, start_time, timezone, frequency,
                _blank(form.channel), _blank(form.mode), form.band, call, grid, archived,
                form.rotator_id, form.unverified, favourite)  # fmt: skip
        )

    def duplicate(self, net_id: int) -> Net:
        form = self.form_for(net_id)
        name, number = f"{form.name} (copy)", 2
        while self.name_taken(name):
            name, number = f"{form.name} (copy {number})", number + 1
        return self.save(replace(form, name=name))

    def set_favourite(self, net_id: int, favourite: bool) -> None:
        net = self.nets.get_net(net_id)
        self.nets.save_net(replace(net, favourite=favourite))

    def set_archived(self, net_id: int, archived: bool) -> None:
        net = self.nets.get_net(net_id)
        self.nets.save_net(replace(net, archived=archived))

    def pickable(self) -> list[Net]:
        """Nets a roster can be imported into: archived ones are left out."""
        return [net for net in self.nets.list_nets() if not net.archived]

    def next_text(self, net: Net, now: datetime) -> str:
        if net.weekday is None or net.start_time is None:
            return occurrence_text(None)
        profile = self.desk.profiles.get_active()
        zone = zone_for(net.timezone, profile.timezone if profile else None)
        return occurrence_text(next_occurrence(net.weekday, net.start_time, zone, now))

    def listing(
        self,
        now: datetime,
        show_archived: bool = False,
        query: str = "",
        favourites_only: bool = False,
    ) -> list[NetSummary]:
        """Favourites first, then by name; search matches name, channel, frequency (MHz as
        text), band and default controller, ignoring case and surrounding spaces."""
        wanted = query.strip().casefold()
        nets = [
            net for net in self.nets.list_nets()
            if net.id is not None
            and (show_archived or not net.archived)
            and (net.favourite or not favourites_only)
            and (not wanted or wanted in _search_text(net))
        ]  # fmt: skip
        nets.sort(key=lambda net: not net.favourite)  # stable: name order kept within each
        return [
            NetSummary(net, self.next_text(net, now), len(self.nets.sessions(net.id or 0)))
            for net in nets
        ]

    def view(self, net_id: int, now: datetime) -> NetView:
        net = self.nets.get_net(net_id)
        if net.default_controller_call is None:
            controller = "No default controller"
        else:
            grid = net.default_controller_grid or "grid unknown"
            controller = f"{net.default_controller_call} · {grid}"
        participants = sorted(
            self.nets.participants(net_id), key=lambda p: (-p.sessions_attended, p.callsign)
        )
        return NetView(net, self.next_text(net, now), controller, self.nets.sessions(net_id),
                       participants)  # fmt: skip

    # Example nets (spec 4.6: offered at first run, opt-in, labelled unverified) ---------

    def example_offer(self) -> bool:
        """True until the operator adds or declines the example nets."""
        return self.desk.settings.get(EXAMPLE_SETTING) is None

    def add_examples(self) -> "ImportReport":
        from beam_navigator.beamnet import import_beamnet  # beamnet imports this module

        report = import_beamnet(self, EXAMPLE_NETS.read_bytes())
        self._import_example_rosters(set(report.added))
        self.desk.settings.set(EXAMPLE_SETTING, "added")
        return report

    def _import_example_rosters(self, added: set[str]) -> None:
        """Each example roster becomes a past session of its example net, which also stores
        its stations as roster records (decision 32). Only nets this call added get one: a
        net the operator already had under that name is theirs, and is left alone."""
        from beam_navigator.roster_review import RosterReview

        ids = {net.name: net.id for net in self.nets.list_nets() if net.name in added}
        review = RosterReview(self.desk.conn, self.desk)
        for roster in example_rosters():
            net_id = ids.get(roster.net)
            if net_id is not None:
                review.save(net_id, roster.date, review.parse(roster.text))

    def example_callsigns(self) -> list[str]:
        """Every callsign in the example rosters, once each, in roster order."""
        calls: dict[str, None] = {}
        for roster in example_rosters():
            for row in parse_roster(roster.text).rows:
                if row.callsign:
                    calls.setdefault(normalize_callsign(row.callsign))
        return list(calls)

    def decline_examples(self) -> None:
        self.desk.settings.set(EXAMPLE_SETTING, "declined")
