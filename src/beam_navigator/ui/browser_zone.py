"""The PC's own time zone for a new station profile, asked of the browser on this machine
(owner, 2026-11-21): a profile left on UTC put Friday evening's nets at the end of the
Nets list. Python on Windows only knows names like "Eastern Standard Time"."""

from nicegui import ui

from beam_navigator.core.schedule import zone_for

ASK = "Intl.DateTimeFormat().resolvedOptions().timeZone"


def fill_when_blank(box: ui.input) -> None:
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
