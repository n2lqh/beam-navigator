"""Small value types shared across the core package and the store."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True)
class OperatorProfile:
    id: int | None
    name: str
    callsign: str | None
    home_grid: str
    latlon: LatLon | None
    units: Literal["km", "mi"]
    timezone: str
    home_region: str | None
    is_active: bool


@dataclass(frozen=True)
class Station:
    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    latlon: LatLon | None
    source: Literal["saved", "roster"]
    notes: str


@dataclass(frozen=True)
class Net:
    id: int | None
    name: str
    weekday: int | None
    start_time: str | None
    timezone: str | None
    frequency_mhz: float | None
    channel: str | None
    mode: str | None
    band: str | None
    default_controller_call: str | None
    default_controller_grid: str | None
    archived: bool
    rotator_id: int | None = None  # the net's preferred rotator (spec 3)
    unverified: bool = False  # an example net the operator has not checked (spec 4.6)
    favourite: bool = False  # the operator's own star; never exported


@dataclass(frozen=True)
class Session:
    id: int
    net_id: int
    date: str
    controller_call: str | None
    controller_grid: str | None
    status: Literal["active", "closed", "imported"]
    raw_text: str | None
    controller_bearing: float | None = None  # tonight's measured bearing, if that is all


@dataclass(frozen=True)
class CheckIn:
    id: int
    session_id: int
    sequence: int | None
    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    published_bearing: str | None
    heard_state: Literal["heard", "weak", "not_heard", "relay"] | None = None
    relay_call: str | None = None
    report: str | None = None
    notes: str | None = None
    logged_at: str | None = None  # UTC ISO time; None for imported rows


@dataclass(frozen=True)
class Participant:
    callsign: str
    last_grid: str | None
    sessions_attended: int
    last_seen: str


@dataclass(frozen=True)
class RotatorProfile:
    id: int | None
    name: str
    adapter: Literal["simulation", "pstrotator", "hamlib"]
    host: str | None
    port: int | None
    az_min: float
    az_max: float
    offset: float
    speed_deg_per_s: float | None
    bands: tuple[str, ...]
    live: bool
    connection_tested: bool


@dataclass(frozen=True)
class Band:
    name: str
    mhz: float
    long_path: bool


@dataclass(frozen=True)
class CommandRecord:
    id: int
    at: str
    rotator_id: int
    target_label: str | None
    requested_true: float | None
    sent: str | None
    ok: bool
    message: str
    measured: float | None
