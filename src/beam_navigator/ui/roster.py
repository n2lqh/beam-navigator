"""Roster import and review (requirements 4.3). Saving sends no rotator command."""

from collections.abc import Callable
from datetime import date

from nicegui import ui

from beam_navigator.core.models import Net
from beam_navigator.roster_review import Review, ReviewRow, RosterReview
from beam_navigator.store.repositories import NetRepository


def _error(exc: Exception) -> None:
    ui.notify(str(exc), type="negative", multi_line=True)


def new_net_dialog(
    review: RosterReview, band_names: list[str], on_created: Callable[[Net], object]
) -> ui.dialog:
    with ui.dialog() as dialog, ui.card():
        ui.label("New net").classes("text-lg")
        name = ui.input("Net name").mark("net-name")
        band = ui.select([*band_names], label="Band (optional)", clearable=True).mark("net-band")
        frequency = ui.input("Frequency, MHz (optional)").mark("net-frequency")
        channel = ui.input("Channel or talkgroup (optional)").mark("net-channel")

        def create() -> None:
            try:
                net = review.create_net(
                    name.value or "", band.value, frequency.value or "", channel.value or ""
                )
            except ValueError as exc:
                _error(exc)
                return
            ui.notify(f"Created {net.name}")
            dialog.close()
            on_created(net)

        with ui.row():
            ui.button("Create net", on_click=create)
            ui.button("Cancel", on_click=dialog.close).props("flat")
    return dialog


def import_page(review: RosterReview, nets: NetRepository, band_names: list[str]) -> None:
    state: dict[str, Review | None] = {"review": None}

    def net_options() -> dict[int, str]:
        # Archived nets are left out of the picker (spec 4.6); their history stays.
        return {
            net.id: net.name
            for net in nets.list_nets()
            if net.id is not None and not net.archived
        }

    def net_created(net: Net) -> None:
        net_select.set_options(net_options(), value=net.id)

    async def paste_clipboard() -> None:
        text = await ui.clipboard.read()
        if text:
            roster_text.set_value(text)

    def parse() -> None:
        state["review"] = review.parse(roster_text.value or "")
        saved_link.clear()
        table.refresh()

    def save(replace_session_id: int | None = None, keep_both: bool = False) -> None:
        current = state["review"]
        if current is None:
            ui.notify("Parse the roster first.", type="warning")
            return
        if net_select.value is None:
            ui.notify("Pick the net this roster belongs to.", type="warning")
            return
        when = (date_input.value or "").strip()
        try:
            if replace_session_id is None and not keep_both:
                existing = review.duplicate_of(net_select.value, when, current)
                if existing is not None:
                    ask_replace(existing)
                    return
            session = review.save(net_select.value, when, current, replace_session_id)
        except ValueError as exc:
            _error(exc)
            return
        count = len(nets.checkins(session.id))
        ui.notify(f"Saved {count} check-ins")
        saved_link.clear()
        with saved_link:
            ui.label(f"Saved {count} check-ins")
            ui.link("Open live net", f"/net/{session.id}")

    def ask_replace(existing: int) -> None:
        def replace() -> None:
            dialog.close()
            save(replace_session_id=existing)

        def keep_both() -> None:
            dialog.close()
            save(keep_both=True)

        with ui.dialog() as dialog, ui.card():
            ui.label("This exact roster was already imported for this net and date.")
            with ui.row():
                ui.button("Replace", on_click=replace)
                ui.button("Keep both", on_click=keep_both)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    dialog = new_net_dialog(review, band_names, net_created)
    with ui.column().classes("w-full max-w-5xl mx-auto gap-4 p-4"):
        roster_text = (
            ui.textarea("Roster text", placeholder="Paste the net's check-in list here")
            .props("outlined autogrow")
            .classes("w-full")
            .mark("roster-text")
        )
        with ui.row().classes("items-end gap-4"):
            ui.button("Paste from clipboard", on_click=paste_clipboard).props("flat")
            net_select = ui.select(net_options(), label="Net").classes("w-56").mark("net")
            ui.button("New net", on_click=dialog.open).props("flat")
            date_input = ui.input("Date (YYYY-MM-DD)", value=date.today().isoformat()).mark(
                "date"
            )
            ui.button("Parse", on_click=parse).mark("parse")

        @ui.refreshable
        def table() -> None:
            current = state["review"]
            if current is None:
                return
            for warning in current.warnings:
                ui.label(warning).classes("text-warning")
            callers = {row.index: row.callsign for row in current.rows if row.callsign}
            chosen = next((row.index for row in current.rows if row.is_controller), None)
            suggestion = " (suggested by the roster)" if current.controller_suggested else ""
            ui.select(
                callers, value=chosen, label=f"Net controller{suggestion}", clearable=True,
                on_change=lambda e: review.set_controller(current, e.value),
            ).classes("w-64").mark("controller")  # fmt: skip
            for row in current.rows:
                _review_row(review, row)

        table()
        ui.button("Save", on_click=lambda: save()).props("size=lg").mark("save")
        saved_link = ui.column()


def _review_row(review: RosterReview, row: ReviewRow) -> None:
    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        if row.callsign is None:
            ui.label(f"Unparsed text: {row.line_text}").classes("text-grey italic")
            return
        ui.checkbox(value=row.include, on_change=lambda e: setattr(row, "include", e.value)).mark(
            f"row-include-{row.index}"
        )
        ui.label(str(row.sequence or "")).classes("w-6")
        ui.label(row.callsign).classes("w-24 font-bold")
        ui.input("Name", value=row.name or "",
                 on_change=lambda e: setattr(row, "name", e.value)).classes("w-28")  # fmt: skip
        ui.input("QTH", value=row.qth or "",
                 on_change=lambda e: setattr(row, "qth", e.value)).classes("w-40")  # fmt: skip
        from_you = ui.label("")
        distance = ui.label("")

        def show() -> None:
            from_you.set_text(f"From you: {row.from_you or '—'}")
            distance.set_text(row.distance or "")

        def grid_changed(value: str) -> None:
            row.grid = value
            review.recompute(row)
            show()

        ui.input("Grid", value=row.grid or "",
                 on_change=lambda e: grid_changed(e.value)).classes("w-24").mark(
            f"row-grid-{row.index}"
        )  # fmt: skip
        ui.label(f"Published: {row.published}" if row.published else "").classes("text-grey")
        show()
        for warning in row.warnings:
            ui.badge(warning, color="warning")
        if row.earlier_grid:  # asked, never assumed (decision 40)
            ui.checkbox(
                f"Replace earlier roster grid {row.earlier_grid}", value=row.replace_grid,
                on_change=lambda e: setattr(row, "replace_grid", bool(e.value)),
            ).mark(f"row-replace-grid-{row.index}")  # fmt: skip
