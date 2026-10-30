"""Build src/beam_navigator/data/regions.csv from Natural Earth admin-1 boundaries.

Dev-time only; the app never downloads anything. Run once with a downloaded copy:

    curl -L -o ne.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_1_states_provinces.geojson
    uv run python tools/build_regions.py ne.geojson src/beam_navigator/data/regions.csv

Natural Earth is public domain. Each centroid is the area centroid computed in
a cylindrical equal-area projection centred on the region, so lobes far from
the equator are not over-weighted. Canadian territories are left out
(requirements 4.2 names provinces only).
"""

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

SOURCE = "Natural Earth 1:50m admin-1 v5.1.2, equal-area centroid"
COUNTRIES = {"US": {"State", "Federal District"}, "CA": {"Province"}}

Ring = list[list[float]]


def _wrap(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def _ring_moments(ring: Ring, ref_lon: float) -> tuple[float, float, float]:
    """Area and first moments of one ring in (radians of longitude, sin latitude)."""
    points = [
        (math.radians(_wrap(lon - ref_lon)), math.sin(math.radians(lat))) for lon, lat in ring
    ]
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    # Orientation varies in the source data: make every ring positive here.
    sign = 1.0 if area >= 0 else -1.0
    return abs(area), sign * cx / 6.0, sign * cy / 6.0


def centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    polygons: list[list[Ring]] = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    # Centre the projection on the largest outer ring's first vertex, so regions
    # that cross 180° (Alaska) stay contiguous.
    largest = max(polygons, key=lambda polygon: len(polygon[0]))
    ref_lon = largest[0][0][0]
    total = mx = my = 0.0
    for polygon in polygons:
        for index, ring in enumerate(polygon):
            area, cx, cy = _ring_moments(ring, ref_lon)
            weight = 1.0 if index == 0 else -1.0  # later rings are holes
            total += weight * area
            mx += weight * cx
            my += weight * cy
    lat = math.degrees(math.asin(my / total))
    lon = _wrap(ref_lon + math.degrees(mx / total))
    return lat, lon


def build(geojson_path: Path, csv_path: Path) -> int:
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        if props.get("type_en") not in COUNTRIES.get(props.get("iso_a2"), set()):
            continue
        lat, lon = centroid(feature["geometry"])
        rows.append([props["postal"], props["name"], f"{lat:.4f}", f"{lon:.4f}", SOURCE])
    rows.sort()
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["code", "name", "lat", "lon", "source"])
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    count = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Wrote {count} regions to {sys.argv[2]}")
