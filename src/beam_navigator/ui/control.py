"""The net controller screen (requirements 4.5). Keyboard first; no rotator commands.

The entry line itself lives in beam_navigator.ui.entry_line, shared with the
participant's "I hear" line.
"""

from nicegui import ui

from beam_navigator.export import Format, export_filename, export_session
from beam_navigator.net_control import ControlRow, Entry, NetControl
from beam_navigator.qrz_client import QrzClient
from beam_navigator.ui.entry_line import EntryLine


def control_page(control: NetControl, session_id: int, qrz: QrzClient | None = None) -> None:
    line = EntryLine(
        control, session_id, qrz=qrz,
        on_logged=lambda: table.refresh(),
        on_callsign=lambda: info.refresh(),
        on_note=lambda: open_note(),
    )  # fmt: skip

    def open_note() -> None:
        call = line.callsign
        if not call:
            ui.notify("Type a callsign first.", type="warning")
            return
        note_input.set_value("")
        note_dialog.open()

    def save_note() -> None:
        try:
            control.add_station_note(line.callsign, note_input.value or "")
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        note_dialog.close()
        info.refresh()
        line.focus_active()

    def download(fmt: Format) -> None:
        session = control.nets.get_session(session_id)
        net = control.nets.get_net(session.net_id)
        content = export_session(
            control.conn, control.desk, session_id, fmt,
            include_report=bool(include_report.value), include_notes=bool(include_notes.value),
        )  # fmt: skip
        ui.download.content(content.encode("utf-8"), export_filename(session, net, fmt))

    # Dialogs (built once, reused) ----------------------------------------------------------

    with ui.dialog() as note_dialog, ui.card():
        ui.label("Add a station note").classes("text-lg")
        note_input = ui.input("Note").props("autofocus").mark("note-text")
        with ui.row():
            ui.button("Save note", on_click=save_note)
            ui.button("Cancel", on_click=note_dialog.close).props("flat")

    # Layout ------------------------------------------------------------------------------

    session = control.nets.get_session(session_id)
    net = control.nets.get_net(session.net_id)
    with ui.column().classes("w-full max-w-6xl mx-auto gap-3 p-4"):
        ui.label(f"Net control · {net.name} · {session.date}").classes("text-xl font-bold")
        with ui.row().classes("w-full items-start gap-6"):  # narrow window: info drops below
            with ui.column().classes("grow gap-2"):
                line.fields()
                line.inputs["callsign"].props("autofocus")

            @ui.refreshable
            def info() -> None:
                call = line.callsign
                if not call:
                    ui.label("Type a callsign").classes("text-grey")
                    return
                panel = control.info(session_id, call)
                ui.label(panel.callsign).classes("text-lg font-bold")
                ui.label(panel.last)
                if panel.from_net_control:
                    ui.label(panel.from_net_control)
                ui.label(f"Attendance: {panel.attendance}")
                for note in panel.previous_notes:
                    ui.label(note).classes("text-caption")
                if panel.station_notes:
                    ui.label(panel.station_notes).classes("text-caption whitespace-pre-line")

            with ui.column().classes("w-80 shrink-0"):
                with ui.card().classes("w-full").mark("info"):
                    info()
                # Chrome and Edge keep Ctrl+N for a new window, so notes also have a button.
                with ui.row().classes("gap-1"):
                    ui.button("Station note", on_click=open_note).props("flat").mark(
                        "note-button"
                    )
                    if qrz is not None:
                        line.qrz_button()

        @ui.refreshable
        def table() -> None:
            for row in control.rows(session_id):
                _session_row(control, row)

        with ui.column().classes("w-full gap-0 overflow-x-auto"):
            table()
        with ui.row().classes("items-center gap-2"):
            include_report = ui.checkbox("Include report", value=True).mark("export-report")
            include_notes = ui.checkbox("Include notes", value=True).mark("export-notes")
            # No heard-states option: they are private, and the net controller adds the
            # stations to the roster (owner, 2026-10-29; decision 40).
            for label, fmt in (("Text", "text"), ("CSV", "csv"), ("JSON", "json")):
                ui.button(label, on_click=lambda f=fmt: download(f)).props("flat")


CELLS = ("name", "grid", "qth", "report", "notes")
# Wide enough for the names and towns the entry line holds (owner, 2026-10-29).
# shrink-0 keeps them that wide; a narrow window scrolls the table sideways instead.
CELL_WIDTHS = {"name": "w-80 shrink-0", "grid": "w-24 shrink-0", "qth": "w-48 shrink-0",
               "report": "w-16 shrink-0", "notes": "grow min-w-24"}  # fmt: skip


def _session_row(control: NetControl, row: ControlRow) -> None:
    """One editable row. A cell saves on blur only if it changed, and the row is updated
    in place, so focus and typing in the next cell are never lost to a rebuild."""
    stored = {name: getattr(row, name) or "" for name in CELLS}
    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.label(str(row.sequence or "")).classes("w-6 shrink-0")
        ui.label(row.time).classes("w-12 shrink-0 text-grey")
        ui.label(row.callsign).classes("w-24 shrink-0 font-bold")
        cells: dict[str, ui.input] = {}
        for name in CELLS:
            cells[name] = (
                ui.input(value=stored[name]).props("dense borderless").classes(CELL_WIDTHS[name])
                .mark(f"cell-{row.checkin_id}-{name}")
            )  # fmt: skip

        @ui.refreshable
        def flags() -> None:
            for field_name in ("name", "grid"):
                if not stored[field_name]:
                    ui.badge(f"{field_name} missing", color="warning")

        def save(name: str) -> None:
            value = (cells[name].value or "").strip()
            if value == stored[name]:
                return
            typed = Entry(row.callsign, **{**stored, name: value})
            try:
                control.update_existing(row.checkin_id, typed)
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                cells[name].set_value(stored[name])  # the stored value stays the truth
                return
            stored[name] = value
            flags.refresh()
            ui.notify(f"Saved {row.callsign}")

        for name, cell in cells.items():
            cell.on("blur", lambda _, n=name: save(n))
        flags()
