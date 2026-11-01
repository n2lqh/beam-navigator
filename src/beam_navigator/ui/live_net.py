"""The live net screen (requirements 4.4). One Target: whatever was picked last. Only
Rotate and Rotate to net control reach the rotator (invariant 2); everything else here
only reads or records."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from nicegui import events, run, ui

from beam_navigator.core.callsign import is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import is_grid
from beam_navigator.core.sector import sector_name
from beam_navigator.desk import Bearing
from beam_navigator.hotkeys import action_for
from beam_navigator.live_net import (
    LiveNet,
    LiveNetView,
    Mode,
    RegularSort,
    SortKey,
    controller_line,
    filter_rows,
    sort_regulars,
    sort_rows,
)
from beam_navigator.net_control import Entry, NetControl
from beam_navigator.qrz_client import QrzClient, QrzError
from beam_navigator.rotators.service import RotateOutcome
from beam_navigator.store.repositories import DuplicateCheckIn
from beam_navigator.ui.entry_line import EntryLine

COMPASS_LAYOUT = [["NW", "N", "NE"], ["W", "", "E"], ["SW", "S", "SE"]]
HEARD_OPTIONS = {"": "—", "heard": "Heard", "weak": "Weak", "not_heard": "Not heard",
                 "relay": "Via relay"}  # fmt: skip
# Each list sorts on its own (owner, 2026-10-30); "Roster order" read as jargon.
TONIGHT_SORTS = {"roster": "Check-in order", "callsign": "Callsign", "bearing": "Direction",
                 "distance": "Distance"}  # fmt: skip
REGULAR_SORTS = {"last": "Last check-in", "callsign": "Callsign", "grid": "Grid",
                 "direction": "Direction"}  # fmt: skip
# Where the Target came from, in words (redesign, owner 2026-11-01).
NET_CONTROL, TONIGHT, REGULARS, TYPED, I_HEAR = (
    "Net control", "Tonight list", "Regulars", "Typed", "I hear"
)
NO_TARGET = "No target yet — pick a station"
NO_LOCATION = "The target has no location: pick another station or type a grid."
NO_ROTATOR_SET_UP = "No rotator set up: Settings → Rotators."


# A clicked button keeps focus, and ui.keyboard ignores keys while a button has focus
# (so Ctrl+Enter cannot also "click" it): drop focus after each click.
BLUR = "(e) => e.currentTarget.blur()"
BLUR_ACTIVE = "() => document.activeElement && document.activeElement.blur()"
# A row selects on click, except clicks that start in a form field (the heard select):
# selecting rebuilds the table, which would close the select's menu as it opens.
# Clicks on a row's own button (Heard) are that button's, not the row's.
ROW_CLICK = "(e) => { if (!(e.target.closest('.q-field') || e.target.closest('.q-btn'))) emit(e) }"
# Enter in Find or point at looks the text up, then leaves the box so Ctrl+Enter rotates next.
AIM_ENTER = "(e) => { emit(); e.target.blur() }"


def _error(exc: Exception) -> None:
    ui.notify(str(exc), type="negative", multi_line=True)


@dataclass
class _State:
    mode: Mode = "controller"
    selected: int | None = None  # a check-in tonight
    callsign: str | None = None  # a regular not heard yet
    source: str = NET_CONTROL  # where the Target came from, shown on the Target card
    typed: tuple[str, float] | None = None
    rotator_id: int | None = None
    outcome: RotateOutcome | None = None
    watched_id: int | None = None
    pressed_at: float = 0.0
    sort: SortKey = "roster"
    regular_sort: RegularSort = "last"
    filter_text: str = ""
    aim_call: str | None = None  # a typed callsign not in tonight's list yet


def live_net_page(control: NetControl, session_id: int, qrz: QrzClient | None = None) -> None:
    live = control.live
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
            pressed(live.rotate(session_id, state.rotator_id, state.mode, state.selected,
                                callsign=state.callsign, typed=state.typed))  # fmt: skip

    def snap_back() -> None:
        """Rotate to net control: make net control the Target and rotate, one press."""
        pick("controller", NET_CONTROL)
        if state.rotator_id is not None:
            stop_watching()
            pressed(live.snap_back(session_id, state.rotator_id))

    def announce(sector: str) -> None:
        result = live.announce(session_id, sector)
        banner.set_text(f"{sector}: {result.message}")
        banner.classes(
            replace="text-4xl font-bold p-4 " + ("text-positive" if result.up else "text-grey")
        )

    def pick(mode: Mode, source: str) -> None:
        """Makes something the Target. Never rotates (invariant 2)."""
        state.mode, state.source = mode, source
        lists.refresh()
        controls.refresh()

    def select_row(checkin_id: int) -> None:
        state.selected = checkin_id
        pick("station", TONIGHT)

    def select_regular(callsign: str) -> None:
        state.callsign = callsign
        pick("regular", REGULARS)

    def aim_enter() -> None:
        """Looks the typed text up and makes it the target. Never rotates (invariant 2)."""
        text = (aim.value or "").strip()
        view, target = live.aim(session_id, text)
        parts = [view.title, view.bearing_text, view.distance_text, view.message]
        aim_result.set_text(view.error or " · ".join(p for p in parts if p))
        tonight = {row.callsign for row in live.view(session_id).rows}
        call = normalize_callsign(text) if is_callsign(text) else None
        state.aim_call = call if call and call not in tonight else None
        add_tonight.set_visibility(state.aim_call is not None)
        if target is not None:
            state.typed = target
            pick("typed", TYPED)
        elif state.typed is not None:
            # Never leave Rotate on an earlier typed target while showing this one.
            state.typed = None
            controls.refresh()

    def aim_heard(found: tuple[str, Bearing] | None) -> None:
        """Aim on the I-hear line: that station becomes the typed target. Never rotates."""
        if found is not None:
            state.typed = (found[0], found[1].deg)
            pick("typed", I_HEAR)

    def add_aimed_tonight() -> None:
        """Puts the typed call on the I-hear line; logging it is still the operator's Enter."""
        if state.aim_call is not None:
            i_hear.fill_callsign(state.aim_call)

    def heard_regular(callsign: str) -> None:
        """Heard: adds the regular to tonight as on the I-hear line, from their record."""
        found = control.autofill(callsign)
        regular = next((r for r in live.view(session_id).regulars if r.callsign == callsign),
                       None)  # fmt: skip
        grid = found.grid or (regular.grid_text if regular and is_grid(regular.grid_text) else "")
        try:
            logged = control.log_heard(
                session_id, Entry(callsign, name=found.name or "", grid=grid or "")
            )
        except DuplicateCheckIn as exc:
            ui.notify(control.duplicate_text(session_id, exc.existing), type="warning")
            lists.refresh()
            return
        except ValueError as exc:
            _error(exc)
            return
        ui.notify(f"Logged {callsign}")
        if state.mode == "regular" and state.callsign == callsign:
            state.selected = logged.id  # keep Rotate on them, now in tonight's list
            pick("station", TONIGHT)
        else:
            lists.refresh()

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
        lists.refresh()

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
        lists.refresh()

    def set_sort(key: SortKey) -> None:
        state.sort = key
        lists.refresh()

    def set_regular_sort(key: RegularSort) -> None:
        state.regular_sort = key
        lists.refresh()

    def everything() -> None:
        header.refresh()
        lists.refresh()
        controls.refresh()

    def close_session() -> None:
        """Close my session: notes for next time; the session turns read-only."""
        try:
            session = live.nets.close_session(session_id, close_notes.value or "")
        except ValueError as exc:
            _error(exc)
            return
        close_dialog.close()
        ui.navigate.to(f"/nets/{session.net_id}")

    def reopen() -> None:
        live.nets.reopen_session(session_id)
        i_hear.set_enabled(True)
        header.refresh()
        lists.refresh()

    controller_dialog = _ControllerDialog(live, session_id, qrz, everything)
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
        lists.refresh()

    def cancel_relay() -> None:
        relay_dialog.close()
        lists.refresh()  # puts the row's select back to its saved state

    with ui.dialog() as close_dialog, ui.card():
        ui.label("Close my session").classes("text-lg")
        close_notes = ui.textarea("Notes for next time").classes("w-96").mark("close-notes")
        ui.label("Shown at the next session of this net. Never exported.").classes(
            "text-caption"
        )
        with ui.row():
            ui.button("Close", on_click=close_session).mark("close-confirm")
            ui.button("Cancel", on_click=close_dialog.close).props("flat")

    with ui.dialog() as relay_dialog, ui.card():
        ui.label("Relayed by").classes("text-lg")
        relay_call = ui.input("Relaying station's callsign").mark("relay-call")
        with ui.row():
            ui.button("Save relay", on_click=save_relay)
            ui.button("Cancel", on_click=cancel_relay).props("flat")

    with ui.column().classes("w-full max-w-7xl mx-auto gap-3 p-4"):

        @ui.refreshable
        def header() -> None:
            view = live.view(session_id)
            with ui.row().classes("items-center gap-4 w-full"):
                ui.label(view.title).classes("text-xl font-bold")
                ui.label(view.frequency)
                ui.link("Net control screen", f"/control/{session_id}")
                ui.space()
                if view.closed:
                    # Read-only, but pointing still works: it records nothing.
                    ui.badge("Closed", color="grey").mark("closed-badge")
                    ui.button("Reopen", on_click=reopen).props("flat").mark("reopen").on(
                        "click", js_handler=BLUR
                    )
                else:
                    ui.button("Close my session…", on_click=close_dialog.open).props(
                        "flat"
                    ).mark("close-session").on("click", js_handler=BLUR)
            text, button_label = controller_line(view.controller)
            with ui.row().classes("items-center gap-2"):
                ui.label(text).classes("text-lg").mark("net-control")
                ui.button(button_label, on_click=controller_dialog.open).props(
                    "flat dense no-refocus"
                ).mark("net-control-change").on("click", js_handler=BLUR)
            if view.last_time is not None:
                when, notes = view.last_time
                with ui.card().classes("w-full bg-amber-1").mark("last-time"):
                    ui.label(f"Last time ({when})").classes("font-bold")
                    ui.label(notes).classes("whitespace-pre-line")

        header()

        with ui.element("div").classes("flex flex-col md:flex-row gap-6 w-full items-start"):
            # Beam panel: the Target, Rotate and the rotator; stays in view on a wide window.
            with ui.column().classes(
                "gap-2 w-full md:w-96 shrink-0 md:sticky md:top-4"
            ).mark("beam"):
                ui.label("Beam").classes("text-overline")

                @ui.refreshable
                def controls() -> None:
                    view = live.view(session_id)
                    rotators = desk.rotators()
                    chosen = next((r for r in rotators if r.id == state.rotator_id), None)
                    aim_at = live.target(session_id, state.mode, state.selected,
                                         callsign=state.callsign, typed=state.typed)  # fmt: skip
                    with ui.card().classes("w-full").mark("target"):
                        ui.label("Target").classes("text-caption")
                        if aim_at is not None:
                            deg = aim_at[1]
                            ui.label(aim_at[0]).classes("text-3xl font-bold")
                            ui.label(f"{deg:.1f}° {sector_name(deg)}").classes("text-lg")
                            ui.label(f"from: {state.source}").classes("text-caption")
                        else:
                            ui.label(_unlocated(view, state)).classes("text-lg")
                    label = "Rotate"
                    if chosen is not None and aim_at is not None:
                        label = f"{desk.rotate_label(chosen, aim_at[1])} ({aim_at[0]})"
                    rotate_button = ui.button(label, on_click=rotate).props("size=lg").classes(
                        "w-full"
                    ).mark("rotate")
                    rotate_button.set_enabled(chosen is not None and aim_at is not None)
                    reason = None
                    if chosen is None:
                        reason = (view.rotate_reason if rotators else None) or NO_ROTATOR_SET_UP
                    elif aim_at is None:
                        reason = NO_TARGET if state.mode == "controller" else NO_LOCATION
                    if reason is not None:
                        ui.label(reason).classes("text-grey").mark("rotate-reason")
                    ui.label("Ctrl+Enter").classes("text-caption")
                    snap = ui.button("Rotate to net control", on_click=snap_back).props(
                        "outline"
                    ).classes("w-full").mark("snap-back")
                    snap.set_enabled(chosen is not None)
                    ui.label("Home").classes("text-caption")
                    for button in (rotate_button, snap):
                        button.on("click", js_handler=BLUR)
                    if rotators:
                        options = {r.id: r.name for r in rotators if r.id is not None}
                        with ui.row().classes("items-center gap-2"):
                            ui.select(
                                options, value=state.rotator_id, label="Rotator",
                                on_change=lambda e: change_rotator(e.value),
                            ).classes("w-48").mark("rotator").on(
                                "update:model-value", js_handler=BLUR_ACTIVE
                            )  # fmt: skip
                            if chosen is not None:
                                ui.label("Live" if chosen.live else "Simulation").classes(
                                    "text-caption"
                                )

                controls()
                status = ui.label("").classes("text-lg").mark("status")
                watcher = ui.timer(1.0, tick, active=False)
                # Fixed keys (decision 22); ignored while a field or button has focus.
                ui.keyboard(on_key=on_key, repeating=False)

                ui.label("Net control is calling").classes("text-overline mt-2")
                with ui.grid(columns=3).classes("gap-1"):
                    for line in COMPASS_LAYOUT:
                        for sector in line:
                            if sector:
                                ui.button(sector, on_click=lambda s=sector: announce(s)).mark(
                                    f"sector-{sector}"
                                ).on("click", js_handler=BLUR)
                            else:
                                ui.label("")
                banner = ui.label("Press the direction net control is calling").mark("banner")

            # Everything you pick from.
            with ui.column().classes("gap-2 grow min-w-0"):
                ui.label("Find or point at").classes("text-overline")
                # Also the filter for both lists (owner, 2026-10-30).
                with ui.row().classes("items-center gap-4 w-full"):
                    aim = (
                        ui.input("Call, grid, alias or direction",
                                 on_change=lambda e: set_filter(e.value))
                        .props("clearable outlined dense").classes("w-80").mark("aim")
                    )  # fmt: skip
                    aim.on("keydown.enter", aim_enter, js_handler=AIM_ENTER)
                    aim_result = ui.label("").mark("aim-result")
                    add_tonight = ui.button("Add to tonight", on_click=add_aimed_tonight).props(
                        "flat dense"
                    ).mark("add-tonight")  # fmt: skip
                    add_tonight.on("click", js_handler=BLUR)
                    add_tonight.set_visibility(False)

                @ui.refreshable
                def lists() -> None:
                    view = live.view(session_id)
                    rows = filter_rows(sort_rows(view.rows, state.sort), state.filter_text)
                    with ui.row().classes("items-end gap-4 mt-2"):
                        ui.label(f"Tonight ({len(view.rows)})").classes("text-lg")
                        ui.select(
                            TONIGHT_SORTS, value=state.sort, label="Sort by",
                            on_change=lambda e: set_sort(e.value),
                        ).classes("w-40").mark("tonight-sort").on(
                            "update:model-value", js_handler=BLUR_ACTIVE
                        )  # fmt: skip
                    for row in rows:
                        selected = state.mode == "station" and row.checkin_id == state.selected
                        with (
                            ui.row()
                            .classes("items-center gap-3 w-full cursor-pointer no-wrap"
                                     + (" bg-blue-1" if selected else ""))
                            .mark(f"row-{row.checkin_id}")
                            .on("click", lambda r=row.checkin_id: select_row(r),
                                js_handler=ROW_CLICK)
                        ):  # fmt: skip
                            ui.label(str(row.sequence or "")).classes("w-6")
                            ui.label(row.callsign).classes("w-24 font-bold")
                            ui.label(row.name or "").classes("w-24")
                            ui.label(row.grid_text).classes("w-32")
                            ui.label(f"From you: {row.bearing_text or '—'}").classes("w-36")
                            ui.label(row.distance_text or "").classes("w-20")
                            ui.label(
                                f"Published: {row.published}" if row.published else ""
                            ).classes("w-28 text-grey")
                            ui.select(
                                HEARD_OPTIONS, value=row.heard or "",
                                on_change=lambda e, c=row.checkin_id: set_heard(c, e.value),
                            ).classes("w-28").mark(f"heard-{row.checkin_id}").set_enabled(
                                not view.closed
                            )  # fmt: skip
                            if row.heard == "relay":
                                ui.label(f"via {row.relay_call}")

                    regulars = filter_rows(
                        sort_regulars(view.regulars, state.regular_sort), state.filter_text
                    )
                    with ui.row().classes("items-end gap-4 mt-4"):
                        ui.label(f"Regulars not heard yet ({len(view.regulars)})").classes(
                            "text-lg"
                        )
                        ui.select(
                            REGULAR_SORTS, value=state.regular_sort, label="Sort by",
                            on_change=lambda e: set_regular_sort(e.value),
                        ).classes("w-40").mark("regular-sort").on(
                            "update:model-value", js_handler=BLUR_ACTIVE
                        )  # fmt: skip
                    for regular in regulars:
                        selected = state.mode == "regular" and regular.callsign == state.callsign
                        with (
                            ui.row()
                            .classes("items-center gap-3 w-full cursor-pointer no-wrap"
                                     + (" bg-blue-1" if selected else ""))
                            .mark(f"regular-{regular.callsign}")
                            .on("click", lambda c=regular.callsign: select_regular(c),
                                js_handler=ROW_CLICK)
                        ):  # fmt: skip
                            ui.label(regular.callsign).classes("w-24 font-bold")
                            ui.label(regular.name or "").classes("w-24")
                            ui.label(regular.grid_text).classes("w-32")
                            ui.label(f"From you: {regular.bearing_text or '—'}").classes("w-36")
                            ui.label(regular.distance_text or "").classes("w-20")
                            ui.label(regular.attendance_text).classes("w-24 text-grey")
                            ui.label(f"Last: {regular.last_seen}").classes("w-32 text-grey")
                            heard = ui.button(
                                "Heard", on_click=lambda c=regular.callsign: heard_regular(c)
                            ).props("flat dense").mark(f"heard-regular-{regular.callsign}")
                            heard.on("click", js_handler=BLUR)
                            heard.set_enabled(not view.closed)

                lists()

                # Stations the operator hears, logged as on net control's screen.
                i_hear = EntryLine(
                    control, session_id, qrz=qrz, on_logged=lambda: lists.refresh(),
                    heard=True, on_callsign=lambda: heard_aim.refresh(),
                )  # fmt: skip
                ui.label("I hear").classes("text-overline mt-2")
                with ui.column().classes("gap-1"):
                    i_hear.fields()

                @ui.refreshable
                def heard_aim() -> None:
                    """Direction to the station on the line, Aim to <call> (sets the Target,
                    never rotates), then Look up on QRZ, in one row (owner, 2026-10-31)."""
                    found = live.heard_aim(i_hear.callsign, i_hear.entry().grid)
                    call = normalize_callsign(i_hear.callsign) if i_hear.callsign else ""
                    with ui.row().classes("items-center gap-2"):
                        ui.label(
                            "Direction: —" if found is None
                            else f"Direction: {found[1].text} · {found[1].distance_text}"
                        ).mark("i-hear-direction")  # fmt: skip
                        button = ui.button(
                            f"Aim to {call}" if call else "Aim",
                            on_click=lambda: aim_heard(found),
                        ).props("flat").mark("i-hear-aim")  # same props as Look up on QRZ
                        button.on("click", js_handler=BLUR)
                        button.set_enabled(found is not None)
                        if qrz is not None:
                            i_hear.qrz_button()

                heard_aim()
                i_hear.set_enabled(not first.closed)


def _unlocated(view: LiveNetView, state: _State) -> str:
    """The Target card when the pick has no location (invariant 4: nothing is guessed)."""
    name = ""
    if state.mode == "station":
        name = next((r.callsign for r in view.rows if r.checkin_id == state.selected), "")
    elif state.mode == "regular":
        name = state.callsign or ""
    if state.mode == "controller" or not name:
        return NO_TARGET
    return f"{name} — grid needed: type a grid, or pick another station."


class _ControllerDialog:
    """Change… / Add grid… / Set net control…: one dialog, two ways to keep it
    (redesign, owner 2026-11-01)."""

    def __init__(
        self, live: LiveNet, session_id: int, qrz: QrzClient | None, refresh: Callable[[], None]
    ) -> None:
        self.live, self.session_id, self.qrz, self.refresh = live, session_id, qrz, refresh
        with ui.dialog() as self.dialog, ui.card().mark("controller-dialog"):
            ui.label("Net control").classes("text-lg")
            self.call = ui.input("Callsign").mark("nc-call")
            with ui.row().classes("items-center gap-2"):
                self.grid = ui.input("Grid").mark("nc-grid")
                if qrz is not None:
                    ui.button("Get grid from QRZ", on_click=self.from_qrz).props(
                        "flat dense"
                    ).mark("nc-qrz")
            self.bearing = ui.input("Measured bearing, ° (optional)").mark("nc-bearing")
            ui.label(
                "Use for tonight changes this session only. Save for this net also makes "
                "it the net's net control for future sessions."
            ).classes("text-caption w-80")
            with ui.row():
                ui.button("Use for tonight", on_click=lambda: self.apply(False)).mark(
                    "nc-tonight"
                )
                ui.button("Save for this net", on_click=lambda: self.apply(True)).mark("nc-save")
                ui.button("Cancel", on_click=self.dialog.close).props("flat")

    def open(self) -> None:
        """Starts from tonight's values each time."""
        session = self.live.nets.get_session(self.session_id)
        self.call.set_value(session.controller_call or "")
        self.grid.set_value(session.controller_grid or "")
        bearing = session.controller_bearing
        self.bearing.set_value("" if bearing is None else f"{bearing:g}")
        self.dialog.open()

    async def from_qrz(self) -> None:
        """Only on this press (offline-first); fills the grid, saves nothing."""
        call = (self.call.value or "").strip().upper()
        if self.qrz is None or not call:
            return
        try:
            record, notice = await run.io_bound(self.qrz.lookup, call)
        except QrzError as exc:
            _error(exc)
            return
        self.live.desk.qrz_store(record, notice)
        if record.grid and is_grid(record.grid):
            self.grid.set_value(record.grid)
        else:
            ui.notify(f"QRZ has no grid for {call}.", type="warning")

    def apply(self, save_for_net: bool) -> None:
        try:
            text = (self.bearing.value or "").strip()
            value = float(text) if text else None
            self.live.set_controller(
                self.session_id, self.call.value, self.grid.value, value,
                save_for_net=save_for_net,
            )  # fmt: skip
        except ValueError as exc:
            _error(exc)
            return
        self.dialog.close()
        self.refresh()
