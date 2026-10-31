"""The keyboard-first entry line (requirements 4.5), shared by the net control screen and
the participant's "I hear" line (owner, 2026-10-30). No rotator commands.

Which key does what is decided in beam_navigator.entry_keys; the browser only sends
the keys that are not ordinary typing (and stops their default action).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import events, run, ui

from beam_navigator.core.keymap import Keymap
from beam_navigator.core.qrz import QrzRecord, page_url
from beam_navigator.entry_keys import ENTRY_ACTIONS, FIELDS, key_action, next_field, previous_field
from beam_navigator.net_control import Entry, NetControl, Suggestion
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
    enabled: bool = True


class EntryLine:
    """Build it, then place fields() and (with QRZ) qrz_button() where the page wants them.

    on_callsign runs whenever the typed call or its details change (the info panel);
    on_logged after each log or update; on_note when the station-note key is pressed.
    heard=True logs through NetControl.log_heard (the participant's line).
    """

    def __init__(
        self,
        control: NetControl,
        session_id: int,
        *,
        fields: tuple[str, ...] = FIELDS,
        qrz: QrzClient | None = None,
        on_logged: Callable[[], object] = lambda: None,
        on_callsign: Callable[[], object] = lambda: None,
        on_note: Callable[[], object] | None = None,
        heard: bool = False,
    ) -> None:
        self.control = control
        self.session_id = session_id
        self.field_names = fields
        self.qrz = qrz
        self.on_logged = on_logged
        self.on_callsign = on_callsign
        self.on_note = on_note
        self.heard = heard
        self.state = _State()
        self.keymap = control.desk.keymap()  # the key filter is built from these
        self.inputs: dict[str, ui.input] = {}
        self._dialogs()

    # What the page reads -----------------------------------------------------------------

    @property
    def callsign(self) -> str:
        box = self.inputs.get("callsign")
        return (box.value or "").strip() if box is not None else ""

    def entry(self) -> Entry:
        return Entry(**{name: (self.inputs[name].value or "") if name in self.inputs else ""
                        for name in FIELDS})  # fmt: skip

    def focus_active(self) -> None:
        self.focus(self.state.active)

    def fill_callsign(self, callsign: str) -> None:
        """Puts a call on the line and fills its details, as picking a suggestion does."""
        self.pick(callsign)

    def set_enabled(self, on: bool) -> None:
        self.state.enabled = on
        for box in self.inputs.values():
            box.set_enabled(on)

    # Entry line --------------------------------------------------------------------------

    def restyle(self) -> None:
        state = self.state
        for name, box in self.inputs.items():
            box.classes(remove=f"{HISTORY} {NEEDED} {ACTIVE} {FROM_QRZ}")
            if name in state.history:
                box.classes(add=HISTORY)
            if name in state.from_qrz:
                box.classes(add=FROM_QRZ)
            if name in state.needed:
                box.classes(add=NEEDED)
            if name == state.active:
                box.classes(add=ACTIVE)

    def focus(self, name: str) -> None:
        self.state.active = name
        self.restyle()
        self.inputs[name].run_method("focus")

    def edited(self, name: str) -> None:
        state = self.state
        if state.filling:
            return
        state.history.discard(name)
        state.from_qrz.discard(name)
        state.needed.discard(name)
        if name == "callsign":
            self.qrz_link()
            # Details filled for the previous call never carry over to a new one.
            state.filling = True
            for filled in state.history:
                self.inputs[filled].set_value("")
            state.filling = False
            state.history.clear()
            state.from_qrz.clear()
            state.needed.clear()
            state.filled_for = ""
            self.message.set_text("")
            self.refresh_suggestions()
            self.on_callsign()
        self.restyle()

    def clear(self) -> None:
        state = self.state
        state.filling = True
        for box in self.inputs.values():
            box.set_value("")
        state.filling = False
        state.history.clear()
        state.from_qrz.clear()
        state.needed.clear()
        state.suggestions, state.highlighted = [], None
        self.message.set_text("")
        self.qrz_link()
        self.suggestions.refresh()
        self.on_callsign()
        self.focus("callsign")

    def qrz_link(self) -> None:
        if self.qrz is not None:
            self.qrz_button.refresh()

    @ui.refreshable_method
    def qrz_button(self) -> None:
        """Look up on QRZ opens the station's QRZ.com page in a new tab (owner, 2026-10-29).
        Redrawn per call: a browser ignores an href added to a button already drawn."""
        link = ui.button("Look up on QRZ").props("flat").mark("qrz-lookup")
        url = page_url(self.callsign) if "callsign" in self.inputs else None
        if url is not None:
            link.props["href"], link.props["target"] = url, "_blank"

    async def qrz_lookup(self, auto: bool = False) -> None:
        """Network in a worker thread; fills only blank fields when it returns."""
        call = self.callsign.upper()
        if self.qrz is None or not call:
            return
        try:
            record, notice = await run.io_bound(self.qrz.lookup, call)
        except QrzError as exc:
            if not (auto and str(exc) in (NO_LOGIN, NO_STORE)):  # QRZ not set up: say nothing
                ui.notify(str(exc), type="warning", multi_line=True)
            return
        self.control.desk.qrz_store(record, notice)
        if self.callsign.upper() != call:
            return  # the operator moved on while QRZ answered
        self.fill_from_qrz(record, notice)
        self.restyle()
        self.on_callsign()

    def fill_from_qrz(self, record: QrzRecord, notice: str | None = None) -> None:
        """Blank fields only, marked as from QRZ (requirements 4.9)."""
        state = self.state
        before = self.entry()
        filled = self.control.qrz_fill(before, record)
        state.filling = True
        for name in ("name", "grid", "qth"):
            value = getattr(filled, name)
            if name in self.inputs and value != getattr(before, name):
                self.inputs[name].set_value(value)
                state.history.add(name)
                state.from_qrz.add(name)
                state.needed.discard(name)
        state.filling = False
        self.message.set_text(" ".join(part for part in ("Filled from QRZ.", notice) if part))

    def autofill(self) -> bool:
        """Fills from the station record; True when QRZ should be asked (owner, 2026-10-29)."""
        state = self.state
        call = self.callsign
        if not call:
            return False
        found = self.control.autofill(call)
        state.filled_for = found.callsign
        state.filling = True
        self.inputs["callsign"].set_value(found.callsign)
        if found.known:
            for name, value in (("name", found.name), ("grid", found.grid), ("qth", found.qth)):
                if name in self.inputs and value and not (self.inputs[name].value or "").strip():
                    self.inputs[name].set_value(value)
                    state.history.add(name)
            self.message.set_text("")
        else:
            state.needed = {"name", "grid"}
            self.message.set_text("New station — name and grid needed")
        state.filling = False
        cached = self.control.desk.qrz.get(found.callsign)
        if cached is not None:
            self.fill_from_qrz(cached[0])  # QRZ answered before: no new lookup (owner, 2026-10-29)
        state.suggestions, state.highlighted = [], None
        self.suggestions.refresh()
        self.on_callsign()
        return self.qrz is not None and self.control.desk.qrz_auto(found.callsign)

    def advance_from_callsign(self) -> None:
        if self.autofill():
            # Runs once, after this key is handled, so typing carries on meanwhile.
            ui.timer(0, lambda: self.qrz_lookup(auto=True), once=True)
        self.focus(next_field("callsign", self.field_names))

    def on_key(self, name: str, e: events.GenericEventArguments) -> None:
        state = self.state
        args = e.args if isinstance(e.args, dict) else {}
        if self.control.desk.keymap() != self.keymap:  # this key filter was built with old keys
            ui.notify("Keys were changed in Settings. Reload this page to use them.",
                      type="warning")  # fmt: skip
            return
        action = key_action(
            name, str(args.get("code", "")), bool(args.get("ctrlKey")), bool(args.get("altKey")),
            bool(args.get("shiftKey")), self.keymap,
        )  # fmt: skip
        if action == "next":
            if name == "callsign":
                self.advance_from_callsign()
            else:
                self.focus(next_field(name, self.field_names))
        elif action == "previous":
            self.focus(previous_field(name, self.field_names))
        elif action == "clear":
            self.clear()
        elif action in ("suggest_down", "suggest_up"):
            self.move_highlight(1 if action == "suggest_down" else -1)
        elif action == "note":
            if self.on_note is not None:
                self.on_note()
        elif action == "log":
            call = self.callsign.upper()
            if name == "callsign" and state.highlighted is not None:
                self.pick(state.suggestions[state.highlighted].callsign)
            elif name == "callsign" and call and state.filled_for != call:
                self.advance_from_callsign()  # first Enter fills; the next logs (decision 31)
            else:
                self.start_log()

    # Partial-call list -------------------------------------------------------------------

    def refresh_suggestions(self) -> None:
        self.state.suggestions = self.control.suggest(self.session_id, self.callsign)
        self.state.highlighted = None
        self.suggestions.refresh()

    def move_highlight(self, step: int) -> None:
        state = self.state
        if not state.suggestions:
            return
        if state.highlighted is None:
            state.highlighted = 0 if step > 0 else len(state.suggestions) - 1
        else:
            state.highlighted = max(0, min(len(state.suggestions) - 1, state.highlighted + step))
        self.suggestions.refresh()

    def pick(self, callsign: str) -> None:
        self.state.filling = True
        self.inputs["callsign"].set_value(callsign)
        self.state.filling = False
        self.autofill()
        self.focus(next_field("callsign", self.field_names))

    # Logging -----------------------------------------------------------------------------

    def start_log(self) -> None:
        state = self.state
        if not state.enabled:
            return
        call = self.callsign
        if not call:
            self.focus("callsign")  # nothing to log; not an error
            return
        if state.filled_for != call.upper():
            self.autofill()  # the callsign is complete when Enter is pressed (spec 4.5)
        typed = self.entry()
        existing = self.control.duplicate(self.session_id, typed.callsign)
        if existing is not None:
            state.pending, state.duplicate_id = typed, existing.id
            self.duplicate_text.set_text(self.control.duplicate_text(self.session_id, existing))
            self.duplicate_dialog.open()
            return
        found = self.control.changes(typed)
        if found:
            state.pending = typed
            self.changes_text.set_text("\n".join(found))
            self.changes_dialog.open()
            return
        self.finish_log(typed, update_record=False)

    def finish_log(self, typed: Entry, update_record: bool) -> None:
        self.changes_dialog.close()
        log = self.control.log_heard if self.heard else self.control.log
        try:
            logged = log(self.session_id, typed, update_record=update_record)
        except DuplicateCheckIn:
            self.start_log()
            return
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Logged {logged.callsign}")
        self.on_logged()
        self.clear()

    def update_existing(self) -> None:
        state = self.state
        self.duplicate_dialog.close()
        if state.pending is None or state.duplicate_id is None:
            return
        try:
            updated = self.control.merge_into_existing(state.duplicate_id, state.pending)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"Updated {updated.callsign}")
        self.on_logged()
        self.clear()

    # Layout ------------------------------------------------------------------------------

    def _dialogs(self) -> None:
        """Built once, reused."""
        state = self.state
        with ui.dialog() as self.changes_dialog, ui.card():
            ui.label("These details differ from the station record").classes("text-lg")
            self.changes_text = ui.label("").classes("whitespace-pre-line")
            with ui.row():
                ui.button(
                    "This session only",
                    on_click=lambda: self.finish_log(state.pending or self.entry(),
                                                     update_record=False),
                ).props("autofocus")  # fmt: skip
                ui.button(
                    "Update station record",
                    on_click=lambda: self.finish_log(state.pending or self.entry(),
                                                     update_record=True),
                ).props("flat")  # fmt: skip

        with ui.dialog() as self.duplicate_dialog, ui.card():
            self.duplicate_text = ui.label("").classes("text-lg")
            with ui.row():
                # Cancel is the default: a stray Enter must never overwrite the earlier entry.
                ui.button("Update existing", on_click=self.update_existing).props("flat").mark(
                    "dup-update"
                )
                ui.button("Cancel", on_click=self.duplicate_dialog.close).props("autofocus").mark(
                    "dup-cancel"
                )

    def fields(self) -> None:
        """The input boxes, the message line and the partial-call list."""
        lines = (
            tuple(f for f in self.field_names if f in LINE_ONE),
            tuple(f for f in self.field_names if f not in LINE_ONE),
        )
        for line in lines:
            if not line:
                continue
            with ui.row().classes("gap-2 no-wrap"):
                for name in line:
                    box = (
                        ui.input(LABELS[name]).props("outlined dense")
                        .classes(WIDTHS[name]).mark(f"entry-{name}")
                    )  # fmt: skip
                    box.on_value_change(lambda _, n=name: self.edited(n))
                    box.on(
                        "keydown",
                        lambda e, n=name: self.on_key(n, e),
                        js_handler=_keys_js(self.keymap, name in ("callsign", "grid")),
                    )
                    self.inputs[name] = box
        self.message = ui.label("").classes("text-warning")
        with ui.column().classes("gap-0").mark("suggestions"):
            self.suggestions()
        self.restyle()

    @ui.refreshable_method
    def suggestions(self) -> None:
        for index, found in enumerate(self.state.suggestions):
            style = "bg-blue-2" if index == self.state.highlighted else ""
            ui.label(
                f"{found.callsign} · {found.last_grid or '—'} · {found.attended} sessions"
            ).classes(f"cursor-pointer {style}").on(
                "click", lambda _, c=found.callsign: self.pick(c)
            )
