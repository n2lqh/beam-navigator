"""The user guide stays true to the app (plan 4c; decision 37): keys, tabs, commands and
labels it names must exist."""

import re
import sys
import tomllib
from pathlib import Path

import pytest

from beam_navigator.core.keymap import ACTIONS, label

ROOT = Path(__file__).resolve().parents[2]
GUIDE = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
SOURCE = "\n".join(
    path.read_text(encoding="utf-8") for path in (ROOT / "src" / "beam_navigator").rglob("*.py")
)


def headings() -> list[str]:
    return re.findall(r"^## (.+)$", GUIDE, flags=re.MULTILINE)


def section(n: int) -> str:
    """The text of the n-th "## " section (0-based), sub-headings included."""
    return re.split(r"^## ", GUIDE, flags=re.MULTILINE)[n + 1]


def test_why_section_first() -> None:
    assert headings()[0] == "Why I wrote Beam Navigator"
    assert "Terry" in section(0) and "N2LQH" in section(0)


def test_features_and_benefits_second() -> None:
    assert headings()[1] == "Features and benefits"
    assert "For attendees" in section(1) and "For net controllers" in section(1)


def test_shortcut_table_matches_the_keymap() -> None:
    rows = [line for line in GUIDE.splitlines() if line.startswith("|")]
    for action in ACTIONS:
        assert any(action.label in row and label(action.default) in row for row in rows), (
            action.label
        )


@pytest.mark.parametrize("tab", ["Station", "Bands", "Aliases", "Rotators", "QRZ", "Keys", "Data"])
def test_settings_tabs_named(tab: str) -> None:
    assert f"Settings → {tab}" in GUIDE


def test_commands_exist() -> None:
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"
    ]
    named = set(re.findall(r"`(beamnav(?:-[a-z]+)?)`", GUIDE))  # commands are in backticks
    assert named and named <= set(scripts)
    assert "packaging/build_windows.py" in GUIDE
    assert (ROOT / "packaging" / "build_windows.py").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows data folder")
def test_windows_data_folder() -> None:
    from platformdirs import user_data_dir

    folder = Path(user_data_dir("beam-navigator", False))
    assert folder.name == "beam-navigator" and folder.parent.name == "Local"
    assert r"%LOCALAPPDATA%\beam-navigator" in GUIDE


@pytest.mark.parametrize(
    "text",
    ["YOUR SECTOR IS UP", "Rotate to net control", "Find or point at", "Use for tonight",
     "Save for this net", "Set net control…", "Add grid…"],
)  # fmt: skip
def test_live_net_labels(text: str) -> None:
    assert text in GUIDE and text in SOURCE


def test_live_switch_named_as_shown() -> None:
    # Final review I1: off, the switch reads SIMULATION_LABEL, not LIVE_LABEL.
    from beam_navigator.ui.settings import LIVE_LABEL, SIMULATION_LABEL

    assert f"**{SIMULATION_LABEL}** switch" in GUIDE and f"**{LIVE_LABEL}**" in GUIDE


def test_safety_promise_names_every_move() -> None:
    # Final review I2: Rotate to net control (once Snap back) moves the rotator too.
    promise = next(line for line in GUIDE.splitlines() if "No surprises at the tower" in line)
    assert "Rotate," in promise and "Rotate to net control" in promise
