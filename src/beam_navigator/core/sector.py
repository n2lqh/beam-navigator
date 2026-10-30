"""The controller's announced sector (requirements 4.4).

A net controller calls one compass sector at a time. The operator's sector is the
direction from the controller to the operator. Nothing here claims the controller can
hear the operator; it only says whether this call is aimed their way.
"""

from dataclasses import dataclass

SECTORS: dict[str, float] = {
    "N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
    "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0,
}  # fmt: skip

# Number-pad layout: the key's position on the pad is its direction.
NUMPAD_SECTORS: dict[str, str] = {
    "Numpad8": "N", "Numpad9": "NE", "Numpad6": "E", "Numpad3": "SE",
    "Numpad2": "S", "Numpad1": "SW", "Numpad4": "W", "Numpad7": "NW",
}  # fmt: skip

DEFAULT_TOLERANCE_DEG = 22.5
SECTOR_UP = "YOUR SECTOR IS UP"
CANT_TELL = "Controller location unknown — can't tell if this call is for you."


@dataclass(frozen=True)
class SectorCheck:
    up: bool | None  # None: the controller's location is unknown
    message: str


def _arc(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def sector_name(bearing_deg: float) -> str:
    """The 8-point sector a bearing falls in."""
    return min(SECTORS, key=lambda name: _arc(bearing_deg, SECTORS[name]))


def check_sector(
    announced: str,
    controller_to_user_deg: float | None,
    tolerance_deg: float = DEFAULT_TOLERANCE_DEG,
) -> SectorCheck:
    centre = SECTORS.get(announced.strip().upper())
    if centre is None:
        raise ValueError(f"Unknown sector {announced!r}.")
    if controller_to_user_deg is None:
        return SectorCheck(None, CANT_TELL)
    if _arc(controller_to_user_deg, centre) <= tolerance_deg:
        return SectorCheck(True, SECTOR_UP)
    where = sector_name(controller_to_user_deg)
    return SectorCheck(False, f"Not your sector — you are {where} of the controller.")
