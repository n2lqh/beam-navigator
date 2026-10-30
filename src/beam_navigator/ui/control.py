"""The net controller screen (requirements 4.5). Keyboard first; no rotator commands.

Which key does what is decided in beam_navigator.entry_keys; the browser only sends
the keys that are not ordinary typing (and stops their default action).
"""

from dataclasses import dataclass, field

from nicegui import events, run, ui

from beam_navigator.core.keymap import Keymap
from beam_navigator.core.qrz import QrzRecord, page_url
from beam_navigator.entry_keys import (
    ENTRY_ACTIONS,
    FIELDS,
    key_action,
    next_field,
    previous_field,
)
from beam_navigator.export import Format, export_filename, export_session
from beam_navigator.net_control import ControlRow, Entry, NetControl, Suggestion
from beam_navigator.qrz_client import NO_LOGIN, QrzClient, QrzError
from beam_navigator.qrz_login import NO_STORE
from beam_navigator.store.repositories import DuplicateCheckIn

LABELS = {"callsign": "Callsign", "name": "Name", "grid": "Grid", "qth": "QTH",
          "report": "Report", "notes": "Notes"}  # fmt: skip
# Wide enough for a full name and a town, state (owner, 2026-10-29); the row wraps.
WIDTHS = {"callsign": "w-36", "name": "w-96", "grid": "w-28", "qth": "w-80",
          "report": "w-20", "notes": "w-80"}  # fmt: skip
LINE_ONE = ("callsign", "name", "grid")  # QTH, Report and Notes go on line two
HISTORY = "italic text-grey-7"  # filled from the station record, not yet confirmed
NEEDED = "bg-yellow-2"  # a new station: these are wanted
FROM_QRZ = "from-qrz"  # filled from QRZ (requirements 4.9), shown in the history style too
ACTIVE = "entry-active ring-2 ring-primary"


def _keys_js(keymap: Keymap, space_advances: bool) -> str:
    """Send only the entry line's bound keys to the server, and stop their browser
    default; every other key types as usual (decision 33)."""

    def js(on: bool) -> str:
        return "true" if on else "false"

    chords = ", ".join(
        f"['{c.code}', {js(c.ctrl)}, {js(c.alt)}, {js(c.shift)}]"
        for c in (keymap[action] for action in ENTRY_ACTIONS)
    )  # codes are plain letters and digits (core.keymap), so they are safe to inline
    space = "false"
    if space_advances:
        space = "(e.code === 'Space' && !ctrl && !e.altKey && !e.shiftKey)"
    return (
        "(e) => { const ctrl = e.ctrlKey || e.metaKey;"
        f" const bound = [{chords}].some(([code, c, a, s]) =>"
        " (e.code === code || (code === 'Enter' && e.code === 'NumpadEnter'))"
        " && ctrl === c && e.altKey === a && e.shiftKey === s);"
        f" if (bound || {space}) {{ e.preventDefault();"
        " emit({code: e.code, ctrlKey: ctrl, altKey: e.altKey, shiftKey: e.shiftKey}); } }"
    )


@dataclass
class _State:
    active: str = "callsign"
    history: set[str] = field(default_factory=set)
    needed: set[str] = field(default_factory=set)
    filling: bool = False
    suggestions: list[Suggestion] = field(default_factory=list)
    highlighted: int | None = None
    pending: Entry | None = None
    duplicate_id: int | None = None
    filled_for: str = ""  # the callsign auto-fill last ran for
    from_qrz: set[str] = field(default_factory=set)


def control_page(control: NetControl, session_id: int, qrz: QrzClient | None = None) -> None:
    state = _State()
    keymap = control.desk.keymap()  # the key filter below is built from these
    inputs: dict[str, ui.input] = {}

    # Entry line --------------------------------------------------------------------------

    def entry() -> Entry:
        return Entry(**{name: (inputs[name].value or "") for name in FIELDS})

    def restyle() -> None:
        for name, box in inputs.items():
            box.classes(remove=f"{HISTORY} {NEEDED} {ACTIVE} {FROM_QRZ}")
            if name in state.history:
                box.classes(add=HISTORY)
            if name in state.from_qrz:
                box.classes(add=FROM_QRZ)
            if name in state.needed:
                box.classes(add=NEEDED)
            if name == state.active:
                box.classes(add=ACTIVE)

    def focus(name: str) -> None:
        state.active = name
        restyle()
        inputs[name].run_method("focus")

    def edited(name: str) -> None:
        if state.filling:
            return
        state.history.discard(name)
        state.from_qrz.discard(name)
        state.needed.discard(name)
        if name == "callsign":
            qrz_link()
            # Details filled for the previous call never carry over to a new one.
            state.filling = True
            for filled in state.history:
                inputs[filled].set_value("")
            state.filling = False
            state.history.clear()
            state.from_qrz.clear()
            state.needed.clear()
            state.filled_for = ""
            message.set_text("")
            refresh_suggestions()
            info.refresh()
        restyle()

    def clear() -> None:
        state.filling = True
        for box in inputs.values():
            box.set_value("")
        state.filling = False
        state.history.clear()
        state.from_qrz.clear()
        state.needed.clear()
        state.suggestions, state.highlighted = [], None
        message.set_text("")
        qrz_link()
        suggestions.refresh()
        info.refresh()
        focus("callsign")

    def qrz_link() -> None:
        if qrz is not None:
            qrz_button.refresh()

    @ui.refreshable
    def qrz_button() -> None:
        """Look up on QRZ opens the station's QRZ.com page in a new tab (owner, 2026-10-29).
        Redrawn per call: a browser ignores an href added to a button already drawn."""
        link = ui.button("Look up on QRZ").props("flat").mark("qrz-lookup")
        url = page_url(inputs["callsign"].value or "") if "callsign" in inputs else None
        if url is not None:
            link.props["href"], link.props["target"] = url, "_blank"

    async def qrz_lookup(auto: bool = False) -> None:
        """Network in a worker thread; fills only blank fields when it returns."""
        call = (inputs["callsign"].value or "").strip().upper()
        if qrz is None or not call:
            return
        try:
            record, notice = await run.io_bound(qrz.lookup, call)
        except QrzError as exc:
            if not (auto and str(exc) in (NO_LOGIN, NO_STORE)):  # QRZ not set up: say nothing
                ui.notify(str(exc), type="warning", multi_line=True)
            return
        control.desk.qrz_store(record, notice)
        if (inputs["callsign"].value or "").strip().upper() != call:
            return  # the controller moved on while QRZ answered
        fill_from_qrz(record, notice)
        restyle()
        info.refresh()

    def fill_from_qrz(record: QrzRecord, notice: str | None = None) -> None:
        """Blank fields only, marked as from QRZ (requirements 4.9)."""
        before = entry()
        filled = control.qrz_fill(before, record)
        state.filling = True
        for name in ("name", "grid", "qth"):
            value = getattr(filled, name)
            if value != getattr(before, name):
                inputs[name].set_value(value)
                state.history.add(name)
                state.from_qrz.add(name)
                state.needed.discard(name)
        state.filling = False
        message.set_text(" ".join(part for part in ("Filled from QRZ.", notice) if part))

    def autofill() -> bool:
        """Fills from the station record; True when QRZ should be asked (owner, 2026-10-29)."""
        call = (inputs["callsign"].value or "").strip()
        if not call:
            return False
        found = control.autofill(call)
        state.filled_for = found.callsign
        state.filling = True
        inputs["callsign"].set_value(found.callsign)
        if found.known:
            for name, value in (("name", found.name), ("grid", found.grid), ("qth", found.qth)):
                if value and not (inputs[name].value or "").strip():
                    inputs[name].set_value(value)
                    state.history.add(name)
            message.set_text("")
        else:
            state.needed = {"name", "grid"}
            message.set_text("New station — name and grid needed")
        state.filling = False
        cached = control.desk.qrz.get(found.callsign)
        if cached is not None:
            fill_from_qrz(cached[0])  # QRZ answered before: no new lookup (owner, 2026-10-29)
        state.suggestions, state.highlighted = [], None
        suggestions.refresh()
        info.refresh()
        return qrz is not None and control.desk.qrz_auto(found.callsign)

    def advance_from_callsign() -> None:
        if autofill():
            # Runs once, after this key is handled, so typing carries on meanwhile.
            ui.timer(0, lambda: qrz_lookup(auto=True), once=True)
        focus(next_field("callsign"))

    def on_key(name: str, e: events.GenericEventArguments) -> None:
        args = e.args if isinstance(e.args, dict) else {}
        if control.desk.keymap() != keymap:  # this page's key filter was built with old keys
            ui.notify("Keys were changed in Settings. Reload this page to use them.",
                      type="warning")  # fmt: skip
            return
        action = key_action(
            name, str(args.get("code", "")), bool(args.get("ctrlKey")), bool(args.get("altKey")),
            bool(args.get("shiftKey")), keymap,
        )  # fmt: skip
        if action == "next":
            if name == "callsign":
                advance_from_callsign()
            else:
                focus(next_field(name))
        elif action == "previous":
            focus(previous_field(name))
        elif action == "clear":
            clear()
        elif action in ("suggest_down", "suggest_up"):
            move_highlight(1 if action == "suggest_down" else -1)
        elif action == "note":
            open_note()
        elif action == "log":
            call = (inputs["callsign"].value or "").strip().upper()
            if name == "callsign" and state.highlighted is not None:
                pick(state.suggestions[state.highlighted].callsign)
            elif name == "callsign" and call and state.filled_for != call:
                advance_from_callsign()  # first Enter fills; the next one logs (decision 31)
            else:
                start_log()

    # Partial-call list -------------------------------------------------------------------

    def refresh_suggestions() -> None:
        state.suggestions = control.suggest(session_id, inputs["callsign"].value or "")
        state.highlighted = None
        suggestions.refresh()

    def move_highlight(step: int) -> None:
        if not state.suggestions:
            return
        if state.highlighted is None:
            state.highlighted = 0 if step > 0 else len(state.suggestions) - 1
        else:
            state.highlighted = max(0, min(len(state.suggestions) - 1, state.highlighted + step))
        suggestions.refresh()

    def pick(callsign: str) -> None:
        state.filling = True
        inputs["callsign"].set_value(callsign)
        state.filling = False
        autofill()
        focus("name")

    # Logging -----------------------------------------------------------------------------

    def start_log() -> None:
        call = (inputs["callsign"].value or "").strip()
        if not call:
            focus("callsign")  # nothing to log; not an error
            return
        if state.filled_for != call.upper():
            autofill()  # the callsign is complete when Enter is pressed (spec 4.5)
        typed = entry()
        existing = control.duplicate(session_id, typed.callsign)
        if existing is not None:
            state.pending, state.duplicate_id = typed, existing.id
            duplicate_text.set_text(control.duplicate_text(session_id, existing))
            duplicate_dialog.open()
            return
        found = control.changes(typed)
        if found:
            state.pending = typed
            changes_text.set_text("\n".join(found))
            changes_dialog.open()
            return
        finish_log(typed, update_record=False)

    def finish_log(typed: Entry, update_record: bool) -> None:
        changes_dialog.close()
        try:
            logged = control.log(session_id, typed, update_record=update_record)
        except DuplicateCheckIn:
            start_log()
            return
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Logged {logged.callsign}")
        table.refresh()
        clear()

    def update_existing() -> None:
        duplicate_dialog.close()
        if state.pending is None or state.duplicate_id is None:
            return
        try:
            updated = control.merge_into_existing(state.duplicate_id, state.pending)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Updated {updated.callsign}")
        table.refresh()
        clear()

    def open_note() -> None:
        call = (inputs["callsign"].value or "").strip()
        if not call:
            ui.notify("Type a callsign first.", type="warning")
            return
        note_input.set_value("")
        note_dialog.open()

    def save_note() -> None:
        try:
            control.add_station_note(inputs["callsign"].value or "", note_input.value or "")
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        note_dialog.close()
        info.refresh()
        focus(state.active)

    def download(fmt: Format) -> None:
        session = control.nets.get_session(session_id)
        net = control.nets.get_net(session.net_id)
        content = export_session(
            control.conn, control.desk, session_id, fmt,
            include_report=bool(include_report.value), include_notes=bool(include_notes.value),
        )  # fmt: skip
        ui.download.content(content.encode("utf-8"), export_filename(session, net, fmt))

    # Dialogs (built once, reused) ----------------------------------------------------------

    with ui.dialog() as changes_dialog, ui.card():
        ui.label("These details differ from the station record").classes("text-lg")
        changes_text = ui.label("").classes("whitespace-pre-line")
        with ui.row():
            ui.button(
                "This session only",
                on_click=lambda: finish_log(state.pending or entry(), update_record=False),
            ).props("autofocus")
            ui.button(
                "Update station record",
                on_click=lambda: finish_log(state.pending or entry(), update_record=True),
            ).props("flat")

    with ui.dialog() as duplicate_dialog, ui.card():
        duplicate_text = ui.label("").classes("text-lg")
        with ui.row():
            # Cancel is the default: a stray Enter must never overwrite the earlier entry.
            ui.button("Update existing", on_click=update_existing).props("flat").mark(
                "dup-update"
            )
            ui.button("Cancel", on_click=duplicate_dialog.close).props("autofocus").mark(
                "dup-cancel"
            )

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
                for line in (LINE_ONE, tuple(f for f in FIELDS if f not in LINE_ONE)):
                    with ui.row().classes("gap-2 no-wrap"):
                        for name in line:
                            box = (
                                ui.input(LABELS[name]).props("outlined dense")
                                .classes(WIDTHS[name]).mark(f"entry-{name}")
                            )  # fmt: skip
                            box.on_value_change(lambda _, n=name: edited(n))
                            box.on(
                                "keydown",
                                lambda e, n=name: on_key(n, e),
                                js_handler=_keys_js(keymap, name in ("callsign", "grid")),
                            )
                            inputs[name] = box
                inputs["callsign"].props("autofocus")
                message = ui.label("").classes("text-warning")

                @ui.refreshable
                def suggestions() -> None:
                    for index, found in enumerate(state.suggestions):
                        style = "bg-blue-2" if index == state.highlighted else ""
                        ui.label(
                            f"{found.callsign} · {found.last_grid or '—'} · "
                            f"{found.attended} sessions"
                        ).classes(f"cursor-pointer {style}").on(
                            "click", lambda _, c=found.callsign: pick(c)
                        )

                with ui.column().classes("gap-0").mark("suggestions"):
                    suggestions()

            @ui.refreshable
            def info() -> None:
                call = (inputs["callsign"].value or "").strip() if inputs else ""
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
                        qrz_button()

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
    restyle()


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
