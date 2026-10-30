"""Export one session as text, CSV or JSON (requirements 4.5).

Bearings are from net control and labelled so. The operator's heard states are
private (spec 4.4) and are left out unless asked for. Missing grids stay blank.
Names and QTHs are put in proper case, and the report and notes can be left out (owner,
2026-10-29).
"""

import csv
import io
import json
import re
import sqlite3
from typing import Literal

from beam_navigator.core.geometry import short_path
from beam_navigator.core.maidenhead import grid_center, is_grid
from beam_navigator.core.models import Net, Session
from beam_navigator.core.text_case import proper_name, proper_qth
from beam_navigator.desk import KM_PER_MILE, Desk
from beam_navigator.net_control import NetControl

Format = Literal["text", "csv", "json"]
EXTENSIONS = {"text": "txt", "csv": "csv", "json": "json"}
COLUMNS = ["net", "date", "frequency", "controller", "controller_grid", "sequence", "time",
           "callsign", "name", "grid", "qth", "report", "notes", "bearing", "bearing_from",
           "distance"]  # fmt: skip  # "distance" is renamed distance_km or distance_mi
NET_CONTROL = "net control"


def export_filename(session: Session, net: Net, fmt: Format) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", net.name.lower()).strip("-") or "net"
    return f"{slug}_{session.date}.{EXTENSIONS[fmt]}"


def export_session(
    conn: sqlite3.Connection,
    desk: Desk,
    session_id: int,
    fmt: Format,
    include_heard: bool = False,
    include_report: bool = True,
    include_notes: bool = True,
) -> str:
    control = NetControl(conn, desk)
    session = control.nets.get_session(session_id)
    net = control.nets.get_net(session.net_id)
    frequency = f"{net.frequency_mhz:g} MHz" if net.frequency_mhz else (net.channel or "")
    # Bearings from net control; without one, the person logging is running the net, so
    # from their own station, labelled as such (owner, 2026-10-29). Never unlabelled.
    origin, origin_label = control.live.controller_location(session_id), NET_CONTROL
    if origin is None and (own := desk.own_station()) is not None:
        origin, origin_label = own
    units = desk.distance_units()
    distance_key = f"distance_{units}"
    heard = {c.id: c.heard_state for c in control.nets.checkins(session_id)}
    header = {
        "net": net.name,
        "date": session.date,
        "frequency": frequency,
        "controller": session.controller_call or "",
        "controller_grid": session.controller_grid or "",
        "bearings_from": origin_label if origin is not None else "",
        "units": units,
    }
    records = []
    for row in control.rows(session_id):
        bearing = distance = None
        if origin is not None and row.grid and is_grid(row.grid):
            path = short_path(origin, grid_center(row.grid))
            km = path.distance_km / KM_PER_MILE if units == "mi" else path.distance_km
            bearing, distance = round(path.bearing_deg, 1), round(km, 1)
        record: dict[str, object] = {
            "sequence": row.sequence, "time": row.time, "callsign": row.callsign,
            "name": proper_name(row.name), "grid": row.grid, "qth": proper_qth(row.qth),
            "report": row.report, "notes": row.notes, "bearing": bearing,
            "bearing_from": origin_label if bearing is not None else None,
            distance_key: distance,
        }  # fmt: skip
        for key, wanted in (("report", include_report), ("notes", include_notes)):
            if not wanted:
                del record[key]
        if include_heard:
            record["heard"] = heard.get(row.checkin_id)
        records.append(record)

    shared = {k: header[k] for k in ("net", "date", "frequency", "controller", "controller_grid")}
    if fmt == "json":
        bearings = f"from {header['bearings_from']}" if header["bearings_from"] else None
        return json.dumps(
            {"schema": 1, **shared, "bearings": bearings, "checkins": records},
            ensure_ascii=False, indent=2,
        )  # fmt: skip
    if fmt == "csv":
        out = io.StringIO()
        left_out = {key for key, wanted in (("report", include_report),
                                            ("notes", include_notes)) if not wanted}  # fmt: skip
        columns = [distance_key if c == "distance" else c for c in COLUMNS if c not in left_out]
        columns += ["heard"] if include_heard else []
        writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow({**shared, **{k: "" if v is None else v for k, v in record.items()}})
        return out.getvalue()
    return _text(header, records, include_heard, distance_key)


def _text(
    header: dict[str, str], records: list[dict[str, object]], include_heard: bool,
    distance_key: str,
) -> str:  # fmt: skip
    """One block per station, as W2KV's roster lays them out, plus the bearing and the
    distance in the operator's units (owner, 2026-10-29). Empty lines are left out."""
    controller = header["controller"] or "unknown"
    if header["controller_grid"]:
        controller += f" ({header['controller_grid']})"
    origin = header["bearings_from"]
    if origin == NET_CONTROL:
        note = "Bearings are from net control."
    elif origin:
        note = f"Bearings are from {origin}: net control's location is unknown."
    else:
        note = "No bearings: net control's location is unknown."
    who = origin.split(" (")[0]  # "N2LQH (FM29pt)" → "N2LQH"
    blocks = [
        "\n".join([
            f"{header['net']} — {header['date']}",
            f"Frequency: {header['frequency'] or '—'}",
            f"Net control: {controller}",
            note,
        ])
    ]  # fmt: skip
    for record in records:
        place = " ".join(str(record[k]) for k in ("qth", "grid") if record.get(k))
        lines = [str(record["callsign"]), str(record.get("name") or ""), place]
        distance = record.get(distance_key)
        if record["bearing"] is not None and isinstance(distance, float):
            shown = f"{distance:,.0f}" if distance >= 10 else f"{distance:.1f}"
            lines.append(f"{record['bearing']}° from {who}, {shown} {header['units']}")
        if record.get("report"):
            lines.append(f"Report: {record['report']}")
        if record.get("notes"):
            lines.append(f"Notes: {' / '.join(str(record['notes']).splitlines())}")
        if include_heard and record.get("heard"):
            lines.append(f"Heard: {record['heard']}")
        blocks.append("\n".join(line for line in lines if line))
    return "\n\n".join(blocks) + "\n"
