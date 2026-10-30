import time
from pathlib import Path

import pytest

from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.roster_parser import ParseResult, parse_roster
from beam_navigator.core.targets import resolve

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> ParseResult:
    return parse_roster((FIXTURES / name).read_text(encoding="utf-8"))


N3RG_CALLS = [
    "K1DY", "AF3G", "K3WGR", "N3ITT", "N3FTI", "K3JJZ", "N2DEQ", "KC2PHM", "N2QVY", "N1DSB",
    "KE2IVT", "KA3WXV", "N2SCJ", "KA3FQS", "W2KV", "KF2Z", "KC3ZZU", "W1XR", "K4SO", "KD4AA",
    "N2LQH", "N3RG",
]  # fmt: skip


def test_n3rg_fixture() -> None:  # acceptance 11
    result = load("n3rg_50mhz_2026-10-26.txt")
    assert [r.callsign for r in result.checkins] == N3RG_CALLS
    assert [r.sequence for r in result.checkins] == list(range(1, 23))
    assert result.controller == "N3RG"
    row = {r.callsign: r for r in result.checkins}
    assert row["N3RG"].grid == "FM29ki"
    assert row["N3RG"].is_controller
    assert row["N2LQH"].grid == "FM29pt"
    assert row["N2LQH"].published_bearing == "35°"
    assert row["N3ITT"].published_bearing == "0°"
    assert row["N1DSB"].grid == "fm29"
    assert row["N1DSB"].published_bearing is None
    assert row["KF2Z"].published_bearing is None
    assert row["K1DY"].name == "BILL"
    assert row["K1DY"].qth == "TROY, ME"
    assert row["N2SCJ"].qth == "MAPLE SHADE, NJ"
    assert "W3CCX" not in row  # inside the URL
    assert sum(r.is_controller for r in result.checkins) == 1
    assert result.stated_checkins == 22
    assert result.warnings == ()  # 22 matches 22; the sign-off is not a second N3RG


def test_wb2rvx_fixture() -> None:  # acceptance 11
    result = load("wb2rvx_432mhz_2026-10-26.txt")
    assert len(result.checkins) == 10
    assert result.checkins[0].callsign == "K3JJZ"
    assert result.checkins[0].sequence == 1
    assert result.controller == "WB2RVX"
    last = result.checkins[-1]
    assert last.grid == "FM29MT"
    assert last.published_bearing == "0°"
    assert last.is_controller
    assert {r.callsign: r for r in result.checkins}["KO4YC"].qth == "RUTHER GLEN, VA"


def test_state_nc_is_not_a_controller_tag() -> None:  # Review Focus 1
    row = parse_roster("1 W4XX BOB RALEIGH, NC\n2 K1DY BILL TROY, ME FN54jq").checkins[0]
    assert not row.is_controller
    assert row.qth == "RALEIGH, NC"
    assert row.grid is None
    assert row.warnings == ("Grid missing",)
    assert row.confidence == "medium"


def test_mixed_case_call_normalized_grid_kept() -> None:  # Review Focus 2
    row = parse_roster("3 k3wgr AL WERNERSVILLE, PA FN10xh").checkins[0]
    assert row.callsign == "K3WGR"
    assert row.grid == "FN10xh"
    assert row.confidence == "high"


def test_frequencies_and_dates_are_not_rows() -> None:  # spec 4.3
    assert parse_roster("50 mhz Check-ins for 10-26-26\n50.150 net\n144.245").checkins == ()


def test_checkin_count_mismatch_warns() -> None:
    result = parse_roster("We had 3 check-ins\n1 K1DY BILL TROY, ME FN54jq")
    assert result.warnings == ("Text says 3 check-ins; 1 parsed.",)


def test_row_numbered_73_is_not_a_sign_off() -> None:
    result = parse_roster(
        "72 K1DY BILL TROY, ME FN54jq\n73 AF3G GLEN HOLLAND, PA FN20LE\n73 de\nN3RG Ray"
    )
    assert [r.callsign for r in result.checkins] == ["K1DY", "AF3G"]


def test_w2kv_fixture() -> None:  # acceptance 11
    result = load("w2kv_144mhz_2026-10-26.txt")
    calls = [r.callsign for r in result.checkins]
    assert len(calls) == 17
    assert calls[0] == "K4SO"
    assert calls[-1] == "W2KV"
    assert calls.count("K8RYU") == 1  # narrative mention
    assert calls.count("W2KV") == 1  # sign-off "Dave W2KV"
    assert result.controller == "W2KV"
    row = {r.callsign: r for r in result.checkins}
    assert row["W2KV"].grid == "FN20OK"
    assert row["W2KV"].name == "DAVE"
    assert row["W2KV"].qth == "HOPEWELL, NJ"
    assert row["K3WGR"].grid == "FN10xi"
    assert row["AF3G"].name == "GLENN"
    assert row["KA3FQS"].qth == "AMBLER, PA"
    assert row["K4SO"].line == 3
    assert result.stated_checkins == 18
    assert "Text says 18 check-ins; 17 parsed." in result.warnings


def test_ka3wxv_fixture() -> None:  # acceptance 11
    result = load("ka3wxv_dmr_2026-10-26.txt")
    assert len(result.checkins) == 11
    assert result.checkins[0].callsign == "K3JJZ"
    assert result.checkins[0].name == "El"
    assert [r.callsign for r in result.checkins].count("KA3WXV") == 1  # sign-off "George / ka3wxv"
    assert result.controller == "KA3WXV"
    assert all(r.grid is None and "Grid missing" in r.warnings for r in result.checkins)
    assert all(r.confidence == "medium" for r in result.checkins)


def test_single_name_call_line_is_not_a_checkin() -> None:
    assert parse_roster("Phil WA3NUF").checkins == ()


def test_wa3nuf_fixture() -> None:  # acceptance 11
    result = load("wa3nuf_222mhz_activity_2026-10-21.txt")
    calls = [r.callsign for r in result.checkins]
    assert len(calls) == 16
    assert calls[0] == "KA3FQS"
    assert "VE2XX" in calls
    assert "WA3NUF" not in calls  # the logger
    grids = [r.grid for r in result.checkins if r.grid]
    assert len(grids) == 16
    assert len({grid[:4].upper() for grid in grids}) == 12
    assert {len(grid) for grid in grids} == {4, 6}
    assert result.controller is None
    assert not any(r.is_controller for r in result.checkins)
    assert (result.stated_checkins, result.stated_grids) == (16, 12)
    assert result.warnings == ()


def test_kc3bvl_fixture() -> None:  # acceptance 11
    result = load("kc3bvl_222mhz_2026-10-19.txt")  # starts with U+FEFF
    assert len(result.checkins) == 8
    assert result.checkins[0].callsign == "W3JG"
    grids = {r.grid[:4].upper() for r in result.checkins if r.grid}
    assert grids == {"FM29", "FN20", "FN31"}
    assert result.controller == "KC3BVL"
    assert result.checkins[-1].grid == "FM29JW"
    assert (result.stated_checkins, result.stated_grids) == (8, 3)
    assert result.warnings == ()


def test_grid_count_mismatch_warns() -> None:
    result = parse_roster("We logged 2 stations and 2 grids\nW1AW FN31, K1ABC FN31")
    assert result.warnings == ("Text says 2 grids; 1 parsed.",)


def test_roster_pasted_twice_flags_duplicates() -> None:  # spec 4.3, Review Focus 4
    text = (FIXTURES / "wb2rvx_432mhz_2026-10-26.txt").read_text(encoding="utf-8")
    result = parse_roster(text + "\n" + text)
    assert len(result.checkins) == 20
    assert result.checkins[10].callsign == "K3JJZ"
    assert result.checkins[10].warnings == ("Duplicate of row 1",)
    assert result.checkins[0].warnings == ()
    assert result.controller == "WB2RVX"
    assert "More than one controller tag." in result.warnings


def test_unparsed_line_inside_block_is_kept() -> None:  # spec 4.3
    result = parse_roster(
        "1 K1DY BILL TROY, ME FN54jq\n?? smudge ??\n2 AF3G GLEN HOLLAND, PA FN20LE"
    )
    assert [r.callsign for r in result.rows] == ["K1DY", None, "AF3G"]
    assert result.rows[1].warnings == ("Unparsed text",)
    assert result.rows[1].confidence == "low"
    assert result.rows[1].text == "?? smudge ??"
    assert result.rows[1].line == 2


def test_paste_damage_gives_same_rows() -> None:  # Review Focus 3
    clean = (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8")
    damaged = "﻿" + clean.replace("\n", "\r\n").replace("  ", "\t").replace(" ", " ")
    assert [(r.callsign, r.grid, r.qth) for r in parse_roster(damaged).checkins] == [
        (r.callsign, r.grid, r.qth) for r in parse_roster(clean).checkins
    ]


def test_garbage_and_huge_paste() -> None:  # acceptance 32, Review Focus 5
    garbage = "".join(chr(c) for c in range(0, 0x3000, 7)) * 20
    huge = ("Conditions were average and the band was quiet tonight. " * 20 + "\n") * 900
    assert len(huge) > 1_000_000
    for text in (garbage, huge):
        start = time.perf_counter()
        result = parse_roster(text)
        assert time.perf_counter() - start < 2.0
        assert result.checkins == ()


def test_hundred_station_roster_parses_and_calculates_fast() -> None:  # acceptance 33
    source = (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8")
    rows = [line for line in source.splitlines() if parse_roster(line).checkins]
    text = "\n".join(rows * 5)  # 110 rows of real data
    home = grid_center("FM29pt")
    start = time.perf_counter()
    result = parse_roster(text)
    for row in result.checkins:
        if row.grid:
            lookup(home, resolve(f"grid:{row.grid}"))
    assert time.perf_counter() - start < 2.0
    assert len(result.checkins) == 110


# Final review findings ----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.glob("*.txt")))
def test_every_fixture_pasted_twice_keeps_both_copies(name: str) -> None:  # finding 1
    text = (FIXTURES / name).read_text(encoding="utf-8")
    once = parse_roster(text).checkins
    twice = parse_roster(text + "\n" + text).checkins
    assert [r.callsign for r in twice] == [r.callsign for r in once] * 2
    assert all(any(w.startswith("Duplicate of row") for w in r.warnings) for r in twice[len(once):])


def test_n3rg_twice_adds_no_rows_from_narrative() -> None:  # finding 1
    text = (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8")
    result = parse_roster(text + "\n" + text)
    assert len(result.rows) == 44
    assert result.rows == result.checkins


def test_sign_off_above_the_list() -> None:  # finding 1
    assert [r.callsign for r in parse_roster("73 de N3RG\n1 K1DY BILL TROY FN54").checkins] == [
        "K1DY"
    ]


def test_broken_entry_at_block_edge_is_kept_as_unparsed() -> None:  # finding 2
    result = parse_roster("K4SO\nAMISSVILLE, VA FM18AP\n\nKD4AA\nTOM\nKILMARNOCK, VA FM17UR")
    assert [r.callsign for r in result.rows] == [None, None, "KD4AA"]
    assert result.rows[0].text == "K4SO"
    assert result.rows[0].warnings == ("Unparsed text",)


def test_call_grid_list_keeps_good_pairs() -> None:  # finding 2
    result = parse_roster("KA3FQS FN20jf, WZ1V FN31rh, K3SK\nW1AUV FN32ii")
    assert [r.callsign for r in result.checkins] == ["KA3FQS", "WZ1V", "K3SK", "W1AUV"]
    k3sk = result.checkins[2]
    assert k3sk.grid is None
    assert k3sk.warnings == ("Grid missing",)


def test_bracketed_nc_tag_in_call_grid_list() -> None:  # finding 2
    result = parse_roster("W1AW FN31 (NC), K1DY FN20")
    assert [r.callsign for r in result.checkins] == ["W1AW", "K1DY"]
    assert result.controller == "W1AW"


@pytest.mark.parametrize(
    ("text", "bearing", "controller"),
    [
        ("1 K1DY BILL TROY, ME FN54jq 38", "38", None),
        ("1 K1DY BILL TROY, ME FN54jq NCS", None, "K1DY"),
        ("1 K1DY BILL TROY, ME FN54jq (NCS)", None, "K1DY"),
        ("1 K1DY BILL TROY, ME FN54jq [NC]", None, "K1DY"),
        ("1 K1DY BILL TROY, ME FN54jq Net Control Station", None, "K1DY"),
        ("1 K1DY BILL TROY, ME FN54jq - Net Control", None, "K1DY"),
        ("1 K1DY BILL TROY, ME FN54jq 38° net control", "38°", "K1DY"),
    ],
)
def test_text_after_grid_does_not_hide_it(
    text: str, bearing: str | None, controller: str | None
) -> None:  # finding 3
    result = parse_roster(text)
    row = result.checkins[0]
    assert row.grid == "FN54jq"
    assert row.qth == "TROY, ME"
    assert row.published_bearing == bearing
    assert result.controller == controller


def test_unknown_words_after_grid_are_flagged() -> None:  # finding 3
    row = parse_roster("1 K1DY BILL TROY, ME FN54jq loud").checkins[0]
    assert row.grid == "FN54jq"
    assert row.warnings == ("Extra text: loud",)


@pytest.mark.parametrize("text", ["x" * 100_000, "a@" * 50_000, "http://" + "y" * 100_000])
def test_long_unbroken_text_is_fast(text: str) -> None:  # finding 4
    start = time.perf_counter()
    assert parse_roster(text).checkins == ()
    assert time.perf_counter() - start < 2.0
