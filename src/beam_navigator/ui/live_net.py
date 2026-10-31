"""The live net screen (requirements 4.4). Only Rotate, Snap back
and Stop reach the rotator (invariant 2); everything else here only reads or records."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from nicegui import events, ui

from beam_navigator.hotkeys import action_for
from beam_navigator.live_net import LiveNet, Mode, SortKey, filter_rows, sort_rows
from beam_navigator.rotators.service import RotateOutcome

COMPASS_LAYOUT = [["NW", "N", "NE"], ["W", "", "E"], ["SW", "S", "SE"]]
HEARD_OPTIONS = {"": "—", "heard": "Heard", "weak": "Weak", "not_heard": "Not heard",
                 "relay": "Via relay"}  # fmt: skip
SORT_OPTIONS = {"roster": "Roster order", "bearing": "Bearing", "distance": "Distance",
                "callsign": "Callsign"}  # fmt: skip


# A clicked button keeps focus, and ui.keyboard ignores keys while a button has focus
# (so Ctrl+Enter cannot also "click" it): drop focus after each click.
BLUR = "(e) => e.currentTarget.blur()"
BLUR_ACTIVE = "() => document.activeElement && document.activeElement.blur()"
# A row selects on click, except clicks that start in a form field (the heard select):
# selecting rebuilds the table, which would close the select's menu as it opens.
ROW_CLICK = "(e) => { if (!e.target.closest('.q-field')) emit(e) }"


def _error(exc: Exception) -> None:
    ui.notify(str(exc), type="negative", multi_line=True)


@dataclass
class _State:
    mode: Mode = "controller"
    selected: int | None = None
    rotator_id: int | None = None
    outcome: RotateOutcome | None = None
    watched_id: int | None = None
    pressed_at: float = 0.0
    sort: SortKey = "roster"
    filter_text: str = ""


def live_net_page(live: LiveNet, session_id: int) -> None:
    desk = live.desk
    state = _State()
    first = live.view(session_id)
    state.rotator_id = first.rotator.id if first.rotator else None

    def stop_watching() -> None:
        watcher.deactivate()

    def tick() -> None:
        if state.outcome is None or state.watched_id is None:
            stop_watching()
            return
        elapsed = time.monotonic() - state.pressed_at
        text, done = desk.watch(state.watched_id, state.outcome, elapsed)
        status.set_text(text)
        if done:
            stop_watching()

    def pressed(outcome: RotateOutcome | None) -> None:
        if outcome is None:
            status.set_text("Nothing to aim at: the target has no location. Nothing was sent.")
            return
        state.outcome, state.watched_id = outcome, state.rotator_id
        state.pressed_at = time.monotonic()
        status.set_text(outcome.status)
        if outcome.sent and outcome.ok and outcome.measured is None:
            watcher.activate()
        else:
            stop_watching()
        controls.refresh()

    def rotate() -> None:
        """The explicit Rotate press."""
        if state.rotator_id is not None:
            stop_watching()
            pressed(live.rotate(session_id, state.rotator_id, state.mode, state.selected))

    def snap_back() -> None:
        """Snap back to controller: target the controller and rotate, one press."""
        state.mode = "controller"
        if state.rotator_id is not None:
            stop_watching()
            pressed(live.snap_back(session_id, state.rotator_id))
        mode_toggle.set_value("controller")

    def announce(sector: str) -> None:
        result = live.announce(session_id, sector)
        banner.set_text(f"{sector}: {result.message}")
        banner.classes(
            replace="text-4xl font-bold p-4 " + ("text-positive" if result.up else "text-grey")
        )

    def select_row(checkin_id: int) -> None:
        state.selected = checkin_id
        table.refresh()
        controls.refresh()

    def set_mode(value: Mode) -> None:
        state.mode = value
        controls.refresh()

    def change_rotator(value: int | None) -> None:
        if value != state.rotator_id:
            stop_watching()
            state.outcome = state.watched_id = None
            status.set_text("")
        state.rotator_id = value
        controls.refresh()

    def set_heard(checkin_id: int, value: str, relay: str | None = None) -> None:
        if value == "relay" and relay is None:
            relay_target["id"] = checkin_id
            relay_call.set_value("")
            relay_dialog.open()  # ask who relayed; the row keeps its old state until saved
            return
        try:
            live.nets.set_heard(checkin_id, value or None, relay)  # type: ignore[arg-type]
        except ValueError as exc:
            _error(exc)
        table.refresh()

    def on_key(e: events.KeyEventArguments) -> None:
        action = action_for(
            e.key.code, e.modifiers.ctrl or e.modifiers.meta, e.modifiers.alt, e.modifiers.shift,
            e.action.keydown, e.action.repeat, "live_net", desk.keymap(),
        )  # fmt: skip
        if action == "rotate":
            rotate()
        elif action == "snap_back":
            snap_back()
        elif isinstance(action, tuple):
            announce(action[1])

    def set_filter(text: str | None) -> None:
        state.filter_text = text or ""
        table.refresh()

    def set_sort(key: SortKey) -> None:
        state.sort = key
        table.refresh()

    def everything() -> None:
        header.refresh()
        table.refresh()
        controls.refresh()

    sub_dialog = _substitute_dialog(live, session_id, everything)
    relay_target: dict[str, int | None] = {"id": None}

    def save_relay() -> None:
        checkin_id = relay_target["id"]
        if checkin_id is None:
            return
        try:
            live.nets.set_heard(checkin_id, "relay", relay_call.value or "")
        except ValueError as exc:
            _error(exc)
            return
        relay_dialog.close()
        table.refresh()

    def cancel_relay() -> None:
        relay_dialog.close()
        table.refresh()  # puts the row's select back to its saved state

    with ui.dialog() as relay_dialog, ui.card():
        ui.label("Relayed by").classes("text-lg")
        relay_call = ui.input("Relaying station's callsign").mark("relay-call")
        with ui.row():
            ui.button("Save relay", on_click=save_relay)
            ui.button("Cancel", on_click=cancel_relay).props("flat")

    with ui.column().classes("w-full max-w-5xl mx-auto gap-3 p-4"):

        @ui.refreshable
        def header() -> None:
            view = live.view(session_id)
            ui.label(view.title).classes("text-xl font-bold")
            with ui.row().classes("gap-6"):
                ui.link("Net control screen", f"/control/{session_id}")
                ui.label(view.frequency)
                ui.label(f"Controller: {view.controller.callsign or 'unknown'}")
            with ui.card().classes("w-full"):
                ui.label(view.controller.you_to_controller or "You → controller: unknown")
                ui.label(view.controller.controller_to_you or "Controller → you: unknown")
                ui.label(f"Location: {view.controller.source}").classes("text-caption")
            ui.button("Substitute controller tonight", on_click=sub_dialog.open).props(
                "flat no-refocus"
            ).mark("substitute").on("click", js_handler=BLUR)

        header()
        with ui.row().classes("items-start gap-8"):
            with ui.grid(columns=3).classes("gap-1"):
                for line in COMPASS_LAYOUT:
                    for sector in line:
                        if sector:
                            ui.button(sector, on_click=lambda s=sector: announce(s)).mark(
                                f"sector-{sector}"
                            ).on("click", js_handler=BLUR)
                        else:
                            ui.label("")
            banner = ui.label("Announced sector: press a direction").mark("banner")

        mode_toggle = ui.toggle(
            {"controller": "Follow Controller", "station": "Follow Station"},
            value="controller", on_change=lambda e: set_mode(e.value),
        ).mark("mode").on("click", js_handler=BLUR_ACTIVE)  # fmt: skip

        @ui.refreshable
        def controls() -> None:
            view = live.view(session_id)
            rotators = desk.rotators()
            if not rotators or view.rotate_reason and state.rotator_id is None:
                ui.label(view.rotate_reason or "No rotator configured.").classes("text-grey")
            if rotators:
                options = {r.id: r.name for r in rotators if r.id is not None}
                ui.select(
                    options, value=state.rotator_id, label="Rotator",
                    on_change=lambda e: change_rotator(e.value),
                ).classes("w-48").mark("rotator").on(
                    "update:model-value", js_handler=BLUR_ACTIVE
                )  # fmt: skip
            chosen = next((r for r in rotators if r.id == state.rotator_id), None)
            aim = live.target(session_id, state.mode, state.selected)
            label = "Rotate"
            if chosen is not None and aim is not None:
                label = f"{desk.rotate_label(chosen, aim[1])} ({aim[0]})"
                ui.label("Live" if chosen.live else "Simulation").classes("text-caption")
            with ui.row().classes("gap-2"):
                rotate_button = ui.button(label, on_click=rotate).props("size=lg").mark("rotate")
                rotate_button.set_enabled(chosen is not None and aim is not None)
                snap = ui.button("Snap back to controller", on_click=snap_back).mark("snap-back")
                snap.set_enabled(chosen is not None)
                for button in (rotate_button, snap):
                    button.on("click", js_handler=BLUR)

        controls()
        status = ui.label("").classes("text-lg").mark("status")
        watcher = ui.timer(1.0, tick, active=False)
        # Fixed keys (decision 22); ignored while a field or button has focus, no repeats.
        ui.keyboard(on_key=on_key, repeating=False)

        with ui.row().classes("items-end gap-4"):
            ui.input("Filter", on_change=lambda e: set_filter(e.value)).mark("filter")
            ui.select(
                SORT_OPTIONS, value="roster", label="Sort", on_change=lambda e: set_sort(e.value)
            ).mark("sort").on("update:model-value", js_handler=BLUR_ACTIVE)

        @ui.refreshable
        def table() -> None:
            view = live.view(session_id)
            rows = filter_rows(sort_rows(view.rows, state.sort), state.filter_text)
            for row in rows:
                selected = row.checkin_id == state.selected
                with (
                    ui.row()
                    .classes("items-center gap-3 w-full cursor-pointer no-wrap"
                             + (" bg-blue-1" if selected else ""))
                    .mark(f"row-{row.checkin_id}")
                    .on("click", lambda r=row.checkin_id: select_row(r), js_handler=ROW_CLICK)
                ):  # fmt: skip
                    ui.label(str(row.sequence or "")).classes("w-6")
                    ui.label(row.callsign).classes("w-24 font-bold")
                    ui.label(row.name or "").classes("w-24")
                    ui.label(row.grid_text).classes("w-32")
                    ui.label(f"From you: {row.bearing_text or '—'}").classes("w-36")
                    ui.label(row.distance_text or "").classes("w-20")
                    ui.label(f"Published: {row.published}" if row.published else "").classes(
                        "w-28 text-grey"
                    )
                    ui.select(
                        HEARD_OPTIONS, value=row.heard or "",
                        on_change=lambda e, c=row.checkin_id: set_heard(c, e.value),
                    ).classes("w-28").mark(f"heard-{row.checkin_id}")  # fmt: skip
                    if row.heard == "relay":
                        ui.label(f"via {row.relay_call}")
            if view.regulars:
                ui.label(f"Expected ({len(view.regulars)})").classes("text-lg mt-4")
                for regular in view.regulars:
                    ui.label(
                        f"{regular.callsign} · {regular.grid_text} · {regular.attendance_text}"
                    ).classes("text-grey")

        table()


def _substitute_dialog(
    live: LiveNet, session_id: int, refresh: Callable[[], None]
) -> ui.dialog:
    with ui.dialog() as dialog, ui.card():
        ui.label("Substitute controller tonight").classes("text-lg")
        ui.label("Applies to this session only; the net's default is not changed.").classes(
            "text-caption"
        )
        call = ui.input("Callsign").mark("sub-call")
        grid = ui.input("Grid (optional)").mark("sub-grid")
        bearing = ui.input("Measured bearing, ° (optional)").mark("sub-bearing")

        def apply() -> None:
            try:
                text = (bearing.value or "").strip()
                value = float(text) if text else None
                live.set_substitute(session_id, call.value, grid.value, value)
            except ValueError as exc:
                _error(exc)
                return
            dialog.close()
            refresh()

        with ui.row():
            ui.button("Apply for tonight", on_click=apply)
            ui.button("Cancel", on_click=dialog.close).props("flat")
    return dialog
