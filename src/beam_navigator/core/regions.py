"""US state, DC and Canadian province centroids from the bundled data/regions.csv.

The table is built once by tools/build_regions.py; see the source column.
"""

import csv
from dataclasses import dataclass
from functools import cache
from importlib.resources import as_file, files
from pathlib import Path

HEADER = ["code", "name", "lat", "lon", "source"]


class RegionDataError(ValueError):
    """The region table is malformed."""


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    lat: float
    lon: float
    source: str


def load_regions_from(path: Path) -> dict[str, Region]:
    regions: dict[str, Region] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != HEADER:
            raise RegionDataError(f"{path.name}: header must be {','.join(HEADER)}.")
        for row in reader:
            line = reader.line_num
            try:
                code, name, lat, lon, source = row
                region = Region(code.strip().upper(), name.strip(), float(lat), float(lon), source)
            except ValueError as exc:
                raise RegionDataError(f"{path.name} line {line}: {exc}") from exc
            if not (-90 <= region.lat <= 90 and -180 <= region.lon <= 180):
                raise RegionDataError(f"{path.name} line {line}: coordinates out of range.")
            if not (region.code and region.name and region.source):
                raise RegionDataError(f"{path.name} line {line}: empty field.")
            if region.code in regions:
                raise RegionDataError(f"{path.name} line {line}: duplicate code {region.code}.")
            regions[region.code] = region
    return regions


@cache
def load_regions() -> dict[str, Region]:
    with as_file(files("beam_navigator") / "data" / "regions.csv") as path:
        return load_regions_from(path)
