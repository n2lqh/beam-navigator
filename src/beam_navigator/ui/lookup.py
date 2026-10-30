"""The bearing-lookup dashboard (requirements 4.1). Only the Rotate and Stop buttons
reach the rotator with a move (invariant 2)."""

import time
from dataclasses import dataclass

from nicegui import events, run, ui

from beam_navigator.core.callsign import is_callsign, normalize_callsign
from beam_navigator.core.qrz import page_url
from beam_navigator.desk import Desk, LookupView, QrzView
from beam_navigator.hotkeys import action_for
from beam_navigator.qrz_client import NO_LOGIN, QrzClient, QrzError
from beam_navigator.qrz_login import NO_STORE
from beam_navigator.rotators.service import RotateOutcome

STOP_NOTE = "Stop does not replace the controller's physical stop."


@dataclass
class _State:
    view: LookupView | None = None
    label: str = ""
    grid_text: str = ""  # the Grid needed field
    typed_grid: tuple[str, str] | None = None  # (callsign, grid) last used from that field
    rotator_id: int | None = None
    outcome: RotateOutcome | None = None
    watched_id: int | None = None  # the rotator the outcome belongs to
    pressed_at: float = 0.0
    qrz: QrzView | None = None  # the QRZ answer for the callsign on screen (spec 4.9)
    searching: bool = False  # an automatic QRZ lookup is out: no "Grid needed" meanwhile


def dashboard(desk: Desk, qrz: QrzClient | None = None) -> None:
    state = _State()
    band_names = [band.name for band in desk.bands.list()]

    def default_rotator_id() -> int | None:
        rotator = desk.default_rotator(band.value)
        return rotator.id if rotator else None

    def run_lookup() -> None:
        text = target.value or ""
        state.view = desk.look_up_or_qrz(text, band.value)
        state.label = text.strip()
        state.typed_grid = None
        state.qrz = desk.qrz_view(state.label) if callsign_on_screen() else None
        result.refresh()
        controls.refresh()

    async def enter() -> None:
        run_lookup()
        if qrz is not None and callsign_on_screen() and desk.qrz_auto(state.label):
            state.searching = True
            result.refresh()
            try:
                await qrz_lookup(auto=True)  # nothing stored for this call (owner, 2026-10-29)
            finally:
                state.searching = False
                result.refresh()

    def callsign_on_screen() -> bool:
        return bool(state.label) and is_callsign(normalize_callsign(state.label))

    async def qrz_lookup(auto: bool = False) -> None:
        """Network in a worker thread; the database only back on the event loop."""
        if qrz is None or not callsign_on_screen():
            return
        call = normalize_callsign(state.label)
        try:
            record, notice = await run.io_bound(qrz.lookup, call)
        except QrzError as exc:
            if not (auto and str(exc) in (NO_LOGIN, NO_STORE)):  # QRZ not set up: say nothing
                ui.notify(str(exc), type="warning", multi_line=True)
            return
        if not callsign_on_screen() or normalize_callsign(state.label) != call:
            return  # the operator moved on while QRZ answered
        desk.qrz_store(record, notice)
        run_lookup()  # an exact QRZ position now gives the bearing
        state.qrz = desk.qrz_view(call, notice)
        result.refresh()

    def save_station() -> None:
        if state.qrz is None:
            return
        try:
            saved = desk.save_qrz_station(state.qrz.callsign)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Saved {saved.callsign}")
        run_lookup()

    def use_qrz() -> None:
        if state.qrz is None:
            return
        state.view = desk.look_up_with_qrz(state.qrz.callsign, band.value)
        state.typed_grid = None
        result.refresh()
        controls.refresh()

    def look_up_text(text: str) -> None:
        target.set_value(text)
        run_lookup()

    def use_grid() -> None:
        view = state.view
        if view is None or view.needs_grid_for is None:
            return
        call, grid = view.needs_grid_for, state.grid_text
        state.view = desk.look_up_with_grid(call, grid, band.value)
        state.typed_grid = (call, grid.strip()) if state.view.error is None else None
        result.refresh()
        controls.refresh()

    def save_grid() -> None:
        if state.typed_grid is None:
            return
        call, grid = state.typed_grid
        try:
            desk.save_station_grid(call, grid)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Saved {grid} for {call}")
        state.typed_grid = None
        result.refresh()

    def forget_move() -> None:
        """A different rotator is selected: the last move's status no longer applies."""
        stop_watching()
        state.outcome = state.watched_id = None
        status.set_text("")

    def change_band() -> None:
        forget_move()
        if band.value:
            desk.select_band(band.value)
        state.rotator_id = default_rotator_id()
        if state.view is not None and state.label:
            run_lookup()
        else:
            controls.refresh()

    def change_rotator(value: int | None) -> None:
        if value != state.rotator_id:
            forget_move()
        state.rotator_id = value
        controls.refresh()

    def stop_watching() -> None:
        watcher.deactivate()

    def rotate() -> None:
        view = state.view
        # Re-checked here: the Ctrl+Enter hotkey does not go through the disabled button.
        if view is None or not view.can_rotate or view.bearing_deg is None:
            return
        if state.rotator_id is None:
            return
        stop_watching()
        outcome = desk.rotate(state.rotator_id, state.label, view.bearing_deg)
        state.outcome = outcome
        state.watched_id = state.rotator_id
        state.pressed_at = time.monotonic()
        status.set_text(outcome.status)
        if outcome.sent and outcome.ok and outcome.measured is None:
            watcher.activate()
        controls.refresh()

    def on_key(e: events.KeyEventArguments) -> None:
        action = action_for(
            e.key.code, e.modifiers.ctrl or e.modifiers.meta, e.modifiers.alt, e.modifiers.shift,
            e.action.keydown, e.action.repeat, "dashboard", desk.keymap(),
        )  # fmt: skip
        if action == "rotate":
            rotate()

    def tick() -> None:
        if state.outcome is None or state.watched_id is None:
            stop_watching()
            return
        elapsed = time.monotonic() - state.pressed_at
        text, done = desk.watch(state.watched_id, state.outcome, elapsed)
        status.set_text(text)
        if done:
            stop_watching()
            controls.refresh()

    def read_position() -> None:
        if state.rotator_id is not None:
            status.set_text(desk.read_position(state.rotator_id))
            controls.refresh()

    def stop() -> None:
        if state.rotator_id is not None:
            stop_watching()
            status.set_text(desk.stop(state.rotator_id))

    with ui.column().classes("w-full max-w-3xl mx-auto gap-4 p-4"):
        with ui.row().classes("w-full items-end gap-4 no-wrap"):
            target = (
                ui.input("Target", placeholder="Callsign, grid, state, heading or alias")
                .props("outlined autofocus")
                .classes("grow text-xl")
                .mark("target")
                .on("keydown.enter", enter)
            )
            band = ui.select(
                band_names, value=desk.selected_band(), label="Band",
                on_change=lambda _: change_band(),
            ).classes("w-32").mark("band")  # fmt: skip
        state.rotator_id = default_rotator_id()

        @ui.refreshable
        def result() -> None:
            view = state.view
            if view is None:
                return
            if state.searching:
                ui.label(f"Looking up {state.label} on QRZ…").classes("text-lg text-grey")
                return
            if view.error:
                ui.label(view.error).classes("text-negative text-lg")
                qrz_card()
                return
            with ui.card().classes("w-full"):
                ui.label(view.title or "").classes("text-lg")
                if view.bearing_text:
                    ui.label(view.bearing_text).classes("text-5xl font-bold")
                for line in (view.distance_text, view.reverse_text, view.long_path_text,
                             view.coarse_note):  # fmt: skip
                    if line:
                        ui.label(line)
                if view.message:
                    ui.label(view.message).classes("text-2xl")
                if view.alternative and view.alternative_label:
                    alternative = view.alternative
                    ui.button(
                        view.alternative_label, on_click=lambda: look_up_text(alternative)
                    ).props("flat")
                if view.needs_grid_for:
                    with ui.row().classes("items-end"):
                        ui.input("Grid").props("outlined").mark("grid").bind_value_to(
                            state, "grid_text"
                        )
                        ui.button("Use grid", on_click=use_grid)
                if state.typed_grid is not None:
                    call, grid = state.typed_grid
                    ui.button(f"Save grid to {call}", on_click=save_grid).props("outline")
            qrz_card()

        def qrz_card() -> None:
            if qrz is None or not callsign_on_screen():
                return
            found = state.qrz
            with ui.card().classes("w-full").mark("qrz-card"):
                if found is not None:
                    ui.label(f"{found.callsign} · {found.source_text}").classes("text-lg")
                    for label, value in (("Name", found.name), ("Grid", found.grid),
                                         ("QTH", found.qth)):  # fmt: skip
                        ui.label(f"{label}: {value or '—'}")
                    ui.label(found.precision_text).classes("text-caption")
                    if found.notice:
                        ui.label(found.notice).classes("text-caption text-warning")
                with ui.row():
                    url = page_url(found.callsign if found else state.label)
                    if url is not None:  # opens QRZ.com in a new tab (owner, 2026-10-29)
                        link = ui.button("Look up on QRZ").props("flat").mark("qrz-lookup")
                        link.props["href"], link.props["target"] = url, "_blank"
                    if found is not None and desk.can_save_qrz(found.callsign):
                        ui.button("Save this station", on_click=save_station).props(
                            "outline"
                        ).mark("qrz-save")
                    elif found is not None and found.precision == "approximate":
                        ui.button("Show approximate bearing", on_click=use_qrz).props(
                            "outline"
                        ).mark("qrz-use")

        result()

        @ui.refreshable
        def controls() -> None:
            rotators = desk.rotators()
            if not rotators:
                ui.label("No rotator configured: Settings → Rotators.").classes("text-grey")
                return
            options = {r.id: r.name for r in rotators if r.id is not None}
            ui.select(
                options, value=state.rotator_id, label="Rotator",
                on_change=lambda e: change_rotator(e.value),
            ).classes("w-48").mark("rotator")  # fmt: skip
            chosen = next((r for r in rotators if r.id == state.rotator_id), None)
            view = state.view
            bearing = view.bearing_deg if view and view.can_rotate else None
            if chosen is not None and chosen.id is not None and bearing is not None:
                ui.label(desk.plan_text(chosen.id, bearing)).mark("plan")
                label = desk.rotate_label(chosen, bearing)
            else:
                label = "Rotate"
            button = ui.button(label, on_click=rotate).props("size=lg").mark("rotate")
            button.on("click", js_handler="(e) => e.currentTarget.blur()")  # keys work after
            button.set_enabled(chosen is not None and bearing is not None)
            if chosen is not None and chosen.id is not None:
                with ui.row().classes("gap-2"):
                    ui.button("Read position", on_click=read_position).props("flat")
                    if desk.service.capabilities(chosen.id).has_stop:
                        ui.button("Stop", on_click=stop, color="negative").mark("stop")
                if desk.service.capabilities(chosen.id).has_stop:
                    ui.label(STOP_NOTE).classes("text-caption text-grey")

        controls()
        status = ui.label("").classes("text-lg").mark("status")
        # One timer for the page, outside every refreshable: a timer created in a click
        # handler would live in the refreshed controls and be deleted with them.
        watcher = ui.timer(1.0, tick, active=False)
        ui.keyboard(on_key=on_key, repeating=False)  # decision 22
