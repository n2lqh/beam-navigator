from pathlib import Path

import pytest

from beam_navigator.core.regions import RegionDataError, load_regions, load_regions_from

US_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}  # fmt: skip
CANADA_PROVINCE_CODES = {"AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK"}


def test_bundled_table_has_states_dc_and_provinces() -> None:
    regions = load_regions()
    assert len(US_CODES) == 51
    assert set(regions) == US_CODES | CANADA_PROVINCE_CODES


def test_bundled_values_are_sane() -> None:
    for code, region in load_regions().items():
        assert region.code == code
        assert region.name
        assert region.source
        assert -90 <= region.lat <= 90
        assert -180 <= region.lon <= 180


def test_names() -> None:
    regions = load_regions()
    assert regions["NJ"].name == "New Jersey"
    assert regions["ON"].name == "Ontario"


def test_malformed_row_names_the_line(tmp_path: Path) -> None:
    bad = tmp_path / "regions.csv"
    bad.write_text("code,name,lat,lon,source\nXX,Nowhere,not-a-number,0,test\n", encoding="utf-8")
    with pytest.raises(RegionDataError, match="line 2"):
        load_regions_from(bad)


def test_wrong_header_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "regions.csv"
    bad.write_text("code,lat,lon\n", encoding="utf-8")
    with pytest.raises(RegionDataError, match="header"):
        load_regions_from(bad)


def test_duplicate_code_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "regions.csv"
    bad.write_text(
        "code,name,lat,lon,source\nXX,A,1,1,test\nxx,B,2,2,test\n", encoding="utf-8"
    )
    with pytest.raises(RegionDataError, match="line 3"):
        load_regions_from(bad)
