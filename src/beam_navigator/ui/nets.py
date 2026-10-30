"""The nets list and each net's history page (requirements 4.6). Nothing here sends a
rotator command (invariant 2): choosing a preferred rotator only records it."""

from collections.abc import Callable
from datetime import UTC, date, datetime

from nicegui import events, run, ui

from beam_navigator.beamnet import (
    BeamnetError,
    ImportReport,
    beamnet_filename,
    import_beamnet,
    write_beamnet,
)
from beam_navigator.core.models import Net, RotatorProfile
from beam_navigator.core.schedule import WEEKDAYS
from beam_navigator.nets import NetBook, NetForm
from beam_navigator.qrz_client import NO_LOGIN, NOT_FOUND, QrzClient, QrzError
from beam_navigator.qrz_login import NO_STORE

WEEKDAY_OPTIONS = {number: name.title() for number, name in enumerate(WEEKDAYS)}
# A clicked button keeps focus; drop it so page hotkeys keep working (as on the live screen).
BLUR = "(e) => e.currentTarget.blur()"
UNVERIFIED = "Example — unverified"
EXAMPLE_OFFER = (
    "Add example nets? Pack Rats and Friday night nets, from a published schedule."
    " Unverified — check before use."
)


def _error(exc: Exception) -> None:
    ui.notify(str(exc), type="negative", multi_line=True)


def _export(nets: list[Net]) -> None:
    ui.download.content(write_beamnet(nets), beamnet_filename(nets, date.today()))


def net_form_dialog(
    book: NetBook,
    band_names: list[str],
    rotators: list[RotatorProfile],
    on_saved: Callable[[Net], object],
) -> Callable[[int | None], None]:
    """Builds the add/edit dialog once; returns open(net_id), None for a new net."""
    editing: dict[str, int | None] = {"net_id": None}
    flagged = {"unverified": False}
    rotator_options = {r.id: r.name for r in rotators if r.id is not None}
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        title = ui.label("New net").classes("text-lg")
        name = ui.input("Net name").mark("form-name")
        with ui.row().classes("w-full no-wrap"):
            weekday = ui.select(WEEKDAY_OPTIONS, label="Weekday", clearable=True).classes(
                "w-36"
            ).mark("form-weekday")
            start = ui.input("Start (HH:MM)").classes("w-28").mark("form-start")
        zone = ui.input("Time zone (e.g. America/New_York)").classes("w-full").mark("form-zone")
        with ui.row().classes("w-full no-wrap"):
            frequency = ui.input("Frequency, MHz").classes("w-36").mark("form-frequency")
            channel = ui.input("Channel or talkgroup").classes("w-44").mark("form-channel")
        with ui.row().classes("w-full no-wrap"):
            mode = ui.input("Mode").classes("w-28").mark("form-mode")
            band = ui.select([*band_names], label="Band", clearable=True).classes("w-36").mark(
                "form-band"
            )
        with ui.row().classes("w-full no-wrap"):
            call = ui.input("Default controller").classes("w-40").mark("form-call")
            grid = ui.input("Controller grid").classes("w-36").mark("form-grid")
        rotator = ui.select(rotator_options, label="Preferred rotator", clearable=True).classes(
            "w-full"
        ).mark("form-rotator")
        checked = ui.checkbox("I've checked these details").mark("form-checked")

        def save() -> None:
            typed = NetForm(
                name=name.value or "", weekday=weekday.value, start_time=start.value or "",
                timezone=zone.value or "", frequency=frequency.value or "",
                channel=channel.value or "", mode=mode.value or "", band=band.value,
                controller_call=call.value or "", controller_grid=grid.value or "",
                rotator_id=rotator.value,
                unverified=flagged["unverified"] and not checked.value,
            )  # fmt: skip
            try:
                net = book.save(typed, editing["net_id"])
            except ValueError as exc:
                _error(exc)
                return
            ui.notify(f"Saved {net.name}")
            dialog.close()
            on_saved(net)

        with ui.row():
            ui.button("Save", on_click=save).mark("form-save")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    def open_form(net_id: int | None) -> None:
        editing["net_id"] = net_id
        title.set_text("Edit net" if net_id is not None else "New net")
        values = book.form_for(net_id) if net_id is not None else None
        name.set_value(values.name if values else "")
        weekday.set_value(values.weekday if values else None)
        start.set_value(values.start_time if values else "")
        zone.set_value(values.timezone if values else "")
        frequency.set_value(values.frequency if values else "")
        channel.set_value(values.channel if values else "")
        mode.set_value(values.mode if values else "")
        band.set_value(values.band if values else None)
        call.set_value(values.controller_call if values else "")
        grid.set_value(values.controller_grid if values else "")
        rotator.set_value(values.rotator_id if values else None)
        flagged["unverified"] = values.unverified if values else False
        checked.set_value(False)
        checked.set_visibility(flagged["unverified"])  # only an example net has it
        dialog.open()

    return open_form


def _start_controls(book: NetBook, net_id: int) -> None:
    def start(when: str | None) -> None:
        try:
            session = book.nets.start_session(net_id, (when or "").strip())
        except ValueError as exc:
            _error(exc)
            return
        ui.navigate.to(f"/net/{session.id}")

    with ui.row().classes("items-end gap-2"):
        when = ui.input("Date", value=date.today().isoformat()).mark(f"start-date-{net_id}")
        ui.button("Start session", on_click=lambda: start(when.value)).props("flat").mark(
            f"start-{net_id}"
        )


def nets_page(
    book: NetBook, band_names: list[str], rotators: list[RotatorProfile],
    qrz: QrzClient | None = None,
) -> None:  # fmt: skip
    state: dict[str, bool | str] = {"show_archived": False, "favourites_only": False,
                                     "query": ""}  # fmt: skip

    def changed(_: Net | None = None) -> None:
        net_list.refresh()

    open_form = net_form_dialog(book, band_names, rotators, changed)

    def duplicate(net_id: int) -> None:
        copy = book.duplicate(net_id)
        ui.notify(f"Created {copy.name}")
        changed()

    def set_archived(net_id: int, archived: bool) -> None:
        book.set_archived(net_id, archived)
        changed()

    with ui.dialog() as report_dialog, ui.card():
        ui.label("Imported nets").classes("text-lg")
        report_text = ui.label("").classes("whitespace-pre-line")
        ui.button("Close", on_click=report_dialog.close).props("flat")

    def show_report(report: ImportReport) -> None:
        lines = [f"Added: {', '.join(report.added) or 'none'}"]
        lines += [f"Skipped {line}" for line in report.skipped]
        report_text.set_text("\n".join(lines))
        report_dialog.open()

    async def imported(e: events.UploadEventArguments) -> None:
        data = await e.file.read()
        upload.reset()
        try:
            report = import_beamnet(book, data)
        except BeamnetError as exc:
            _error(exc)
            return
        show_report(report)
        changed()

    async def add_examples() -> None:
        report = book.add_examples()
        offer.refresh()
        show_report(report)
        changed()
        if qrz is not None:
            await complete_from_qrz(qrz, book.desk.qrz_missing(book.example_callsigns()))

    async def complete_from_qrz(client: QrzClient, calls: list[str]) -> None:
        """One lookup per example station missing a name or grid, one at a time, filling
        only the QRZ cache (decision 32). The first failure ends the pass."""
        stored = 0
        for call in calls:
            try:
                record, notice = await run.io_bound(client.lookup, call)
            except QrzError as exc:
                if str(exc).startswith(NOT_FOUND):
                    continue
                if str(exc) not in (NO_LOGIN, NO_STORE):  # QRZ not set up: say nothing
                    ui.notify(str(exc), type="warning", multi_line=True)
                break
            book.desk.qrz_store(record, notice)
            stored += 1
        if stored:
            ui.notify(f"QRZ filled in details for {stored} example stations.")

    def decline_examples() -> None:
        book.decline_examples()
        offer.refresh()

    @ui.refreshable
    def offer() -> None:
        if not book.example_offer():
            return
        with ui.card().classes("w-full bg-blue-1").mark("example-offer"):
            ui.label(EXAMPLE_OFFER)
            with ui.row():
                ui.button("Add examples", on_click=add_examples).mark("add-examples")
                ui.button("No thanks", on_click=decline_examples).props("flat").mark(
                    "decline-examples"
                )

    def set_view(key: str, value: bool | str) -> None:
        state[key] = value
        changed()

    def set_favourite(net_id: int, favourite: bool) -> None:
        book.set_favourite(net_id, favourite)  # only a star; nothing reaches a rotator
        changed()

    @ui.refreshable
    def net_list() -> None:
        query = str(state["query"])
        summaries = book.listing(
            datetime.now(UTC), show_archived=bool(state["show_archived"]), query=query,
            favourites_only=bool(state["favourites_only"]),
        )  # fmt: skip
        if not summaries and query.strip():
            ui.label(f'No nets match "{query.strip()}".')
        elif not summaries:
            ui.label("No nets to show. Create one, import a beamnet file, or import a roster.")
        for summary in summaries:
            net = summary.net
            if net.id is None:
                continue
            net_id = net.id
            channel = f"{net.frequency_mhz:g} MHz" if net.frequency_mhz else (net.channel or "")
            with ui.card().classes("w-full").mark("net-card", f"net-card-{net_id}"):
                with ui.row().classes("items-center gap-3"):
                    ui.button(
                        icon="star" if net.favourite else "star_border",
                        on_click=lambda n=net_id, f=not net.favourite: set_favourite(n, f),
                    ).props("flat round dense color=amber").on("click", js_handler=BLUR).mark(
                        f"favourite-{net_id}"
                    )
                    ui.link(net.name, f"/nets/{net_id}").classes("text-lg font-bold")
                    if net.archived:
                        ui.badge("Archived", color="grey")
                    if net.unverified:
                        ui.badge(UNVERIFIED, color="orange")
                ui.label(
                    " · ".join(part for part in (summary.next_text, channel, net.band) if part)
                ).classes("text-grey-8")
                for session, count in book.nets.sessions(net_id):
                    with ui.row().classes("items-center gap-4"):
                        ui.label(f"{session.date} · {session.status} · {count} check-ins")
                        ui.link("Open", f"/net/{session.id}")
                        ui.link("Net control", f"/control/{session.id}")
                _start_controls(book, net_id)
                with ui.row().classes("gap-1"):
                    ui.button("Edit", on_click=lambda n=net_id: open_form(n)).props("flat").on(
                        "click", js_handler=BLUR
                    ).mark(f"edit-{net_id}")
                    ui.button("Duplicate", on_click=lambda n=net_id: duplicate(n)).props(
                        "flat"
                    ).mark(f"duplicate-{net_id}")
                    ui.button("Export", on_click=lambda n=net: _export([n])).props("flat").mark(
                        f"export-{net_id}"
                    )
                    ui.button(
                        "Unarchive" if net.archived else "Archive",
                        on_click=lambda n=net_id, a=not net.archived: set_archived(n, a),
                    ).props("flat").mark(f"archive-{net_id}")

    with ui.column().classes("w-full max-w-4xl mx-auto gap-4 p-4"):
        with ui.row().classes("items-center gap-4"):
            ui.button("New net", on_click=lambda: open_form(None)).props("flat").mark("new-net")
            ui.button(
                "Export all", on_click=lambda: _export([s.net for s in book.listing(
                    datetime.now(UTC))])
            ).props("flat").mark("export-all")  # fmt: skip
            ui.switch(
                "Favourites only", on_change=lambda e: set_view("favourites_only", bool(e.value))
            ).mark("favourites-only")
            ui.switch(
                "Show archived", on_change=lambda e: set_view("show_archived", bool(e.value))
            ).mark("show-archived")
            ui.link("Import a roster", "/import")
        upload = (
            ui.upload(label="Import nets (*.beamnet.json)", auto_upload=True, on_upload=imported)
            .props("accept=.json flat").classes("w-80").mark("import-nets")
        )  # fmt: skip
        ui.input(
            "Search nets", placeholder="name, frequency, band or controller",
            on_change=lambda e: set_view("query", e.value or ""),
        ).props("clearable dense").classes("w-80").mark("net-search")  # fmt: skip
        offer()
        net_list()


def net_page(
    book: NetBook, net_id: int, band_names: list[str], rotators: list[RotatorProfile]
) -> None:
    """One net: next occurrence, default controller, past sessions and known participants.
    Participants are history only; they are never shown as checked in (spec 4.6)."""
    rotator_names = {r.id: r.name for r in rotators}

    def changed(_: Net | None = None) -> None:
        body.refresh()

    open_form = net_form_dialog(book, band_names, rotators, changed)

    @ui.refreshable
    def body() -> None:
        view = book.view(net_id, datetime.now(UTC))
        net = view.net
        with ui.row().classes("items-center gap-3"):
            ui.label(net.name).classes("text-2xl font-bold")
            if net.archived:
                ui.badge("Archived", color="grey")
            if net.unverified:
                ui.badge(UNVERIFIED, color="orange")
            ui.button("Edit", on_click=lambda: open_form(net_id)).props("flat").on(
                "click", js_handler=BLUR
            ).mark("edit-net")
        channel = f"{net.frequency_mhz:g} MHz" if net.frequency_mhz else (net.channel or "")
        details = [
            ("Next", view.next_text),
            ("Controller", view.controller_text),
            ("Frequency", channel or "—"),
            ("Rotator", rotator_names.get(net.rotator_id, "Band default")),
        ]
        with ui.grid(columns=2).classes("gap-x-6 gap-y-1"):
            for label, value in details:
                ui.label(label).classes("text-grey-7")
                ui.label(value)
        _start_controls(book, net_id)

        ui.label(f"Sessions ({len(view.sessions)})").classes("text-lg mt-4")
        if not view.sessions:
            ui.label("No sessions yet.").classes("text-grey-7")
        for session, count in view.sessions:
            with ui.row().classes("items-center gap-4"):
                ui.label(f"{session.date} · {session.status} · {count} check-ins")
                ui.link("Open", f"/net/{session.id}").mark(f"open-{session.id}")
                ui.link("Net control", f"/control/{session.id}").mark(f"control-{session.id}")

        ui.label(f"Participants ({len(view.participants)})").classes("text-lg mt-4")
        with ui.grid(columns=4).classes("gap-x-6 gap-y-1"):
            for heading in ("Callsign", "Last grid", "Sessions", "Last seen"):
                ui.label(heading).classes("text-grey-7")
            for person in view.participants:
                ui.label(person.callsign).classes("font-bold")
                ui.label(person.last_grid or "—").mark(f"grid-{person.callsign}")
                ui.label(str(person.sessions_attended))
                ui.label(person.last_seen)

    with ui.column().classes("w-full max-w-4xl mx-auto gap-2 p-4"):
        ui.link("← All nets", "/nets")
        body()
