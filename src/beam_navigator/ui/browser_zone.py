"""The PC's own time zone for a new station profile, asked of the browser on this machine
(owner, 2026-11-21): a profile left on UTC put Friday evening's nets at the end of the
Nets list. Python on Windows only knows names like "Eastern Standard Time"."""

from zoneinfo import available_timezones

from nicegui import ui
from nicegui.elements.mixins.value_element import ValueElement

from beam_navigator.core.schedule import zone_for

ASK = "Intl.DateTimeFormat().resolvedOptions().timeZone"
ZONES = sorted(z for z in available_timezones() if "/" in z or z == "UTC")  # no "Factory"
THIS_COMPUTER = "This computer's time zone"


def zone_options(current: str | None) -> dict[str, str]:
    """Every real zone name, for a list you can type into (owner, 2026-11-24: "no one is
    going to know to type America/New_York"). Blank means this computer's zone."""
    options = {"": THIS_COMPUTER, **{name: name for name in ZONES}}
    if current and current not in options:
        options[current] = current  # an old, unknown name: shown so Save can say why
    return options


def fill_when_blank(box: ValueElement) -> None:
    """Once the page is connected; a box the operator already filled is left alone."""

    async def ask() -> None:
        try:
            name = await ui.run_javascript(ASK, timeout=3)
        except TimeoutError:
            return  # blank still means this computer's zone
        if (
            isinstance(name, str) and name.strip() and zone_for(name) is not None
            and not (box.value or "").strip()
        ):  # fmt: skip
            box.set_value(name.strip())

    ui.timer(0, ask, once=True)
