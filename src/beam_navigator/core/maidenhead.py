"""Maidenhead grid locators: validation and cell centres (requirements 5)."""

from beam_navigator.core.models import LatLon


class GridError(ValueError):
    """Text is not a valid 4, 6, 8 or 10 character Maidenhead locator."""


# Each pair narrows the cell: (allowed characters, divisions of the previous cell).
_PAIRS = [
    ("ABCDEFGHIJKLMNOPQR", 18),
    ("0123456789", 10),
    ("ABCDEFGHIJKLMNOPQRSTUVWX", 24),
    ("0123456789", 10),
    ("ABCDEFGHIJKLMNOPQRSTUVWX", 24),
]


def grid_center(grid: str) -> LatLon:
    text = grid.strip().upper()
    if len(text) not in (4, 6, 8, 10):
        raise GridError(f"Grid {grid.strip()!r} must have 4, 6, 8 or 10 characters.")
    lon, lat = -180.0, -90.0
    width, height = 360.0, 180.0
    for index in range(0, len(text), 2):
        allowed, divisions = _PAIRS[index // 2]
        width /= divisions
        height /= divisions
        for offset, char in enumerate(text[index : index + 2]):
            position = allowed.find(char)
            if position < 0:
                place = index + offset + 1
                raise GridError(f"Grid {text!r}: {char!r} is not allowed at position {place}.")
            if offset == 0:
                lon += position * width
            else:
                lat += position * height
    return LatLon(lat + height / 2, lon + width / 2)


def is_grid(text: str) -> bool:
    try:
        grid_center(text)
    except GridError:
        return False
    return True
