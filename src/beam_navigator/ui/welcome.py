"""The Welcome wizard (Milestone 4; decision 35): shown while no station is active.

It saves the operator's station and answers the example-nets offer. It never creates a
rotator profile, sends a rotator command or goes online (invariants 2 and 10)."""

from nicegui import ui

from beam_navigator.desk import Desk, WelcomeDraft
from beam_navigator.nets import NetBook
from beam_navigator.ui.nets import EXAMPLE_OFFER

STATION, EXAMPLES, NEXT = "Your station", "Example nets", "Next steps"


def welcome_page(desk: Desk, book: NetBook) -> None:
    draft = desk.welcome_draft()
    profiles = desk.profiles.list()
    names = {profile.id: profile.name for profile in profiles}
    # The saved station the form edits, if it was filled from one (final review I3).
    editing: dict[str, int | None] = {"id": draft.profile_id if draft.profile_id in names else None}

    def entered() -> WelcomeDraft:
        return WelcomeDraft(
            (callsign.value or "").strip(), (grid.value or "").strip(), units.value,
            (timezone.value or "").strip(), editing["id"],
        )  # fmt: skip

    def save_station() -> None:
        try:
            desk.save_welcome_station(entered())
        except ValueError as exc:
            error.set_text(str(exc))
            return
        error.set_text("")
        stepper.set_value(EXAMPLES)  # set on the server: next() runs only in the browser

    def use(profile_id: int) -> None:
        desk.use_station(profile_id)
        stepper.set_value(EXAMPLES)

    def new_station() -> None:
        editing["id"] = None
        for field in (callsign, grid):
            field.set_value("")
        heading.refresh()

    def skip() -> None:
        desk.keep_welcome_draft(entered())
        ui.navigate.to("/?later=1")  # the dashboard, this visit only

    def add_examples() -> None:
        report = book.add_examples()
        ui.notify(f"Added {len(report.added)} example nets.")
        stepper.set_value(NEXT)

    def no_examples() -> None:
        book.decline_examples()
        stepper.set_value(NEXT)

    with ui.column().classes("w-full max-w-3xl mx-auto p-4"):
        ui.label("Welcome to Beam Navigator").classes("text-2xl")
        ui.label(
            "Beam Navigator works out bearings from your station, so it needs to know where"
            " that is. Everything here can be changed later in Settings."
        ).classes("text-caption")
        with ui.stepper().props("vertical").classes("w-full").mark("welcome-stepper") as stepper:
            with ui.step(STATION):
                if profiles:
                    ui.label("Use a saved station").classes("text-lg")
                    for profile in profiles:
                        with ui.row().classes("items-center gap-4"):
                            ui.label(f"{profile.name} · {profile.home_grid}").classes("w-56")
                            ui.button(
                                "Use", on_click=lambda p=profile.id: use(p)
                            ).props("flat dense").mark(f"welcome-use-{profile.id}")

                @ui.refreshable
                def heading() -> None:
                    profile_id = editing["id"]
                    if profile_id is None:
                        if profiles:
                            ui.label("Or enter a new station").classes("text-lg mt-4")
                        return
                    with ui.row().classes("items-center gap-4 mt-4"):
                        ui.label(f"Editing {names[profile_id]}").classes("text-lg")
                        ui.button("New station instead", on_click=new_station).props(
                            "flat dense"
                        ).mark("welcome-new-station")

                heading()
                with ui.grid(columns=2).classes("w-full gap-2"):
                    callsign = ui.input("Callsign (optional)", value=draft.callsign).mark(
                        "welcome-callsign"
                    )
                    grid = ui.input("Home grid", value=draft.grid).mark("welcome-grid")
                    units = ui.select(["km", "mi"], value=draft.units, label="Units").mark(
                        "welcome-units"
                    )
                    timezone = ui.input(
                        "Time zone", value=draft.timezone,
                    ).props('hint="For net times, e.g. America/New_York"').mark(
                        "welcome-timezone"
                    )  # fmt: skip
                error = ui.label("").classes("text-negative").mark("welcome-error")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=save_station).mark("welcome-next-1")
                    ui.button("Skip for now", on_click=skip).props("flat").mark("welcome-skip")
                ui.link(
                    "Moving to a new computer? Restore a backup instead", "/settings?tab=Data"
                )
            with ui.step(EXAMPLES):
                if book.example_offer():
                    ui.label(EXAMPLE_OFFER)  # it asks "Add example nets?" itself
                    with ui.stepper_navigation():
                        ui.button("Add examples", on_click=add_examples).mark(
                            "welcome-examples-add"
                        )
                        ui.button("No thanks", on_click=no_examples).props("flat").mark(
                            "welcome-examples-no"
                        )
                else:
                    ui.label("Example nets: already set.")
                    with ui.stepper_navigation():
                        ui.button("Next", on_click=lambda: stepper.set_value(NEXT)).mark(
                            "welcome-next-2"
                        )
            with ui.step(NEXT):
                ui.link("Set up a rotator (it starts in simulation)", "/settings?tab=Rotators")
                ui.link("Add your QRZ login for name and grid lookups", "/settings?tab=QRZ")
                ui.link("Change keyboard shortcuts", "/settings?tab=Keys")
                with ui.stepper_navigation():
                    ui.button("Finish", on_click=lambda: ui.navigate.to("/")).mark(
                        "welcome-finish"
                    )
