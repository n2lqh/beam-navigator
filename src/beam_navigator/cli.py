"""Command-line entry points.

beamnav bearing: true bearing and distance from a given grid to any target.
beamnav parse: check-ins from a pasted roster, with bearings from the user.
Neither talks to a rotator.

beamnav-rotor is the milestone 0 spike: send one heading, query position once,
print exactly what was sent and received. One run sends one move command.
"""

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import GridError, grid_center
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.core.targets import TargetError, resolve
from beam_navigator.rotators.base import RotatorAdapter, RotatorError, azimuth_error
from beam_navigator.rotators.hamlib import HamlibAdapter
from beam_navigator.rotators.pstrotator import PstRotatorAdapter
from beam_navigator.rotators.simulation import SimulationAdapter

DEFAULT_PORTS = {"pstrotator": 12000, "hamlib": 4533}
KM_PER_MILE = 1.609344


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="beamnav", description="Beam Navigator tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    bearing = commands.add_parser("bearing", help="bearing and distance to a target")
    bearing.add_argument("target", help="heading, compass point, grid, state, or callsign")
    bearing.add_argument("--from", dest="home", required=True, help="your grid, e.g. FM29pt")
    bearing.add_argument("--units", choices=["km", "mi"], default="km")
    bearing.add_argument("--long-path", action="store_true", help="also show the long path")
    bearing.add_argument("--mhz", type=float, help="band, for the coarse-location note")
    bearing.add_argument("--home-region", help="state or province you are in, e.g. NJ")
    roster = commands.add_parser("parse", help="parse a pasted net roster")
    roster.add_argument("file", help="text file holding the roster as pasted")
    roster.add_argument("--from", dest="home", help="your grid, to show bearings from you")
    roster.add_argument("--units", choices=["km", "mi"], default="km")
    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args)
    return _bearing(args)


_COLUMNS = [("#", 3, ">"), ("CALL", 8, "<"), ("NAME", 10, "<"), ("QTH", 24, "<"),
            ("GRID", 10, "<"), ("FROM YOU", 8, ">"), ("DIST", 9, ">"),
            ("PUBLISHED (theirs)", 18, "<")]  # fmt: skip


def _table_line(cells: Sequence[str], notes: str) -> str:
    # Two spaces between columns, so a column never runs into the next one.
    parts = [
        f"{cell[:width]:{align}{width}}"
        for cell, (_, width, align) in zip(cells, _COLUMNS, strict=True)
    ]
    return "  ".join([*parts, notes]).rstrip()


def _parse(args: argparse.Namespace) -> int:
    try:
        home = grid_center(args.home) if args.home else None
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    except GridError as exc:
        print(f"Rejected:  {exc}")
        return 2
    except OSError as exc:
        print(f"Rejected:  cannot read {args.file}: {exc.strerror}")
        return 2
    result = parse_roster(text)
    print(_table_line([name for name, _, _ in _COLUMNS], "NOTES"))
    for row in result.rows:
        from_you = distance = ""
        if home is not None and row.grid:
            found = lookup(home, resolve(f"grid:{row.grid}"))
            if found.bearing_deg is not None and found.distance_km is not None:
                from_you = f"{found.bearing_deg:.1f}°"
                distance = _distance(found.distance_km, args.units)
            elif found.message:
                from_you = found.message
        notes = (["NC"] if row.is_controller else []) + list(row.warnings)
        if row.callsign is None:
            notes.append(repr(row.text))
        cells = [
            "" if row.sequence is None else str(row.sequence),
            row.callsign or "?",
            row.name or "",
            row.qth or "",
            row.grid or "",
            from_you,
            distance,
            row.published_bearing or "",
        ]
        print(_table_line(cells, ", ".join(notes)))
    print(f"Check-ins: {len(result.checkins)}")
    print(f"Controller: {result.controller or 'none'}")
    for warning in result.warnings:
        print(f"Warning:   {warning}")
    return 0


def _distance(km: float, units: str) -> str:
    return f"{km / KM_PER_MILE:.1f} mi" if units == "mi" else f"{km:.1f} km"


def _bearing(args: argparse.Namespace) -> int:
    try:
        home = grid_center(args.home)
        target = resolve(args.target)
    except (GridError, TargetError) as exc:
        print(f"Rejected:  {exc}")
        return 2
    result = lookup(
        home,
        target,
        home_region=args.home_region,
        include_long_path=args.long_path,
        freq_mhz=args.mhz,
    )
    print(f"Target:    {target.label} ({target.kind}, {target.source})")
    if target.alternative:
        print(f"Also:      {target.alternative} for the other meaning")
    if result.message:
        print(f"Result:    {result.message}")
        return 0
    print(f"Bearing:   {result.bearing_deg:.1f}° {result.compass}")
    if result.distance_km is not None:
        print(f"Distance:  {_distance(result.distance_km, args.units)}")
    if result.reverse_deg is not None:
        print(f"Reverse:   {result.reverse_deg:.1f}° (from the target to you)")
    if result.long_path is not None:
        long_km = _distance(result.long_path.distance_km, args.units)
        print(f"Long path: {result.long_path.bearing_deg:.1f}°, {long_km}")
    if result.coarse_note:
        print(f"Note:      {result.coarse_note}")
    return 0


def _build_adapter(args: argparse.Namespace) -> RotatorAdapter:
    if args.adapter == "simulation":
        return SimulationAdapter()
    port = args.port if args.port is not None else DEFAULT_PORTS[args.adapter]
    if args.adapter == "pstrotator":
        return PstRotatorAdapter(host=args.host, port=port, timeout_s=args.timeout)
    return HamlibAdapter(host=args.host, port=port, timeout_s=args.timeout)


def _elapsed_ms(start: float) -> str:
    return f"({(time.perf_counter() - start) * 1000:.0f} ms)"


def rotor_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="beamnav-rotor",
        description="Send one heading to a rotator and print exactly what happens.",
    )
    parser.add_argument("--adapter", required=True, choices=["simulation", "pstrotator", "hamlib"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="default: pstrotator 12000, hamlib 4533")
    parser.add_argument("--az", type=float, required=True, help="true heading, 0-359.9 degrees")
    parser.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for a reply")
    args = parser.parse_args(argv)

    error = azimuth_error(args.az)
    if error:
        print(f"Rejected:  {error}")
        return 2

    rotor = _build_adapter(args)
    target = "" if args.adapter == "simulation" else f" → {args.host}"
    print(f"Adapter:   {args.adapter}{target}")

    start = time.perf_counter()
    connection = rotor.connect()
    print(f"Connect:   {connection.message} {_elapsed_ms(start)}")
    if not connection.ok:
        return 1

    try:
        start = time.perf_counter()
        result = rotor.set_azimuth(args.az)
        print(f"Sent:      {rotor.last_sent}")
        if rotor.last_reply is not None:
            print(f"Reply:     {rotor.last_reply}")
        print(f"Result:    {result.message} {_elapsed_ms(start)}")
        if not result.ok:
            return 1

        if not rotor.capabilities().has_feedback:
            print("Position:  unverified (this rotator reports no position).")
            return 0

        start = time.perf_counter()
        try:
            position = rotor.get_position()
        except RotatorError as exc:
            print(f"Query:     {rotor.last_sent}")
            print(f"Position:  unverified — {exc} {_elapsed_ms(start)}")
            return 1
        print(f"Query:     {rotor.last_sent}")
        if rotor.last_reply is not None:
            print(f"Reply:     {rotor.last_reply}")
        if position is None:
            print("Position:  unverified.")
        else:
            print(
                f"Position:  {position:.1f}° at the time of the query; "
                f"the rotor may still be moving. {_elapsed_ms(start)}"
            )
        return 0
    finally:
        rotor.disconnect()
