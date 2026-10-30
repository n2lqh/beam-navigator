"""Settings (requirements 4.8): station profiles, bands, aliases and rotators.

Saving anything here never moves a rotator (invariant 2). Test connection only connects
and reads; Test move runs on a throwaway simulator.
"""

from collections.abc import Callable
from urllib.parse import quote

from nicegui import events, run, ui

from beam_navigator import about
from beam_navigator.backup import BackupError, checked_backup
from beam_navigator.core.keymap import ACTIONS, Chord, label
from beam_navigator.core.models import LatLon, OperatorProfile, RotatorProfile
from beam_navigator.core.targets import AliasTarget, TargetError
from beam_navigator.desk import QRZ_AUTO, Desk
from beam_navigator.qrz_client import NON_SUBSCRIBER, QrzClient, QrzError
from beam_navigator.qrz_login import clear_login, save_login, saved_username
from beam_navigator.rotators.travel import PRESETS
from beam_navigator.store.repositories import RotatorNotTested

LIVE_LABEL = "Live: Rotate turns the real antenna"
SIMULATION_LABEL = "Simulation"
ADAPTERS = ["simulation", "pstrotator", "hamlib"]
ALIAS_KINDS = ["grid", "coords", "station", "heading"]
LOG_LINES = 10
_TRAVEL_HELP = (
    "The rotor's mechanical range in rotor degrees. Headings outside it are refused, never wrapped."
)
# Owner request 2026-10-28: every rotator field explains itself. Copy states only documented
# behaviour (requirements 4.7, docs/rotator-notes.md).
ROTATOR_HELP = {
    "rotator-name": "Your own label, e.g. VHF or 432 beam.",
    "rotator-adapter": (
        "simulation: no hardware, commands are only recorded. pstrotator: PstRotator or"
        " PstRotatorAz on Windows, over UDP. hamlib: Hamlib's rotctld, over TCP."
    ),
    "rotator-host": (
        "The computer running PstRotator or rotctld. 127.0.0.1 means this computer."
        " Not used in simulation."
    ),
    "rotator-port": (
        "PstRotator: the UDP port set in PstRotator (usually 12000); its replies come back on"
        " the next port up. rotctld: its TCP port (usually 4533)."
    ),
    "rotator-preset": (
        "Fills in travel start and end for common rotators. Check them against your"
        " rotator's manual."
    ),
    "rotator-speed": (
        "Degrees per second, for the time estimate and the simulated rotor's speed."
        " Leave blank if unknown."
    ),
    "rotator-min": _TRAVEL_HELP,
    "rotator-max": _TRAVEL_HELP,
    "rotator-offset": (
        "Rotor heading = true bearing + offset. If the beam points at true north when the"
        " rotor reads 5°, enter 5. Leave 0 if calibrated."
    ),
    "rotator-bands": (
        "Bands this antenna is used on. Each band has one rotator, which becomes the default"
        " on the dashboard and live net screen, unless the net names its own rotator."
    ),
}
ABOUT_TRAVEL = [
    "A north-stop rotor turns 0–360°.",
    "A south-stop rotor turns 180–540°: rotor degrees past 360 are the same compass heading"
    " again.",
    "A Yaesu 450° rotor turns 0–450°, so headings 0–90° can be reached two ways. Beam Navigator"
    " shows which way it plans to go; PstRotatorAz chooses its own path.",
    "Live turns the real antenna. It unlocks only after Test connection passes; new rotators"
    " start in simulation.",
]


def _error(exc: Exception) -> None:
    ui.notify(str(exc), type="negative", multi_line=True)


def _marker(name: str) -> str:
    """Test markers are split on spaces, so "2 m" becomes "2m"."""
    return "".join(name.split())


def _number(text: str | None, what: str) -> float | None:
    """Blank is None; anything else must be a number."""
    clean = (text or "").strip()
    if not clean:
        return None
    try:
        return float(clean)
    except ValueError as exc:
        raise ValueError(f"{what} must be a number, not {clean!r}.") from exc


def settings_page(
    desk: Desk, qrz: QrzClient | None = None, restored: str | None = None, tab: str | None = None
) -> None:
    """restored: the safety copy's name, after a restore redrew this page (decision 34).
    tab: the tab to open by its label, e.g. from the Welcome page (decision 35)."""
    if restored is not None:
        _restored_notice(restored)
    with ui.column().classes("w-full max-w-4xl mx-auto p-4"):
        with ui.tabs() as tabs:
            station_tab = ui.tab("Station")
            bands_tab = ui.tab("Bands")
            aliases_tab = ui.tab("Aliases")
            rotators_tab = ui.tab("Rotators")
            qrz_tab = ui.tab("QRZ")
            keys_tab = ui.tab("Keys")
            data_tab = ui.tab("Data")
            about_tab = ui.tab("About")
        by_label = {t.props["label"]: t for t in (station_tab, bands_tab, aliases_tab,
                    rotators_tab, qrz_tab, keys_tab, data_tab, about_tab)}  # fmt: skip
        first = data_tab if restored is not None else by_label.get(tab or "", station_tab)
        with ui.tab_panels(tabs, value=first).classes("w-full"):
            with ui.tab_panel(station_tab):
                _station_panel(desk)
            with ui.tab_panel(bands_tab):
                _bands_panel(desk)
            with ui.tab_panel(aliases_tab):
                _aliases_panel(desk)
            with ui.tab_panel(rotators_tab):
                _rotators_panel(desk)
            with ui.tab_panel(qrz_tab):
                _qrz_panel(desk, qrz or QrzClient())
            with ui.tab_panel(keys_tab):
                _keys_panel(desk)
            with ui.tab_panel(data_tab):
                _data_panel(desk)
            with ui.tab_panel(about_tab):
                _about_panel()


def _about_panel() -> None:
    ui.label(about.TITLE).classes("text-h6")
    ui.label(about.COPYRIGHT)
    with ui.column().mark("about-licence"):
        for paragraph in about.LICENSE_NOTICE:
            ui.label(paragraph)
    ui.label(f"Source code: {about.SOURCE_URL}")
    with ui.row().classes("gap-1"):
        ui.label("Every screen, with pictures:")
        ui.link("screen-by-screen walkthrough", about.WALKTHROUGH_URL, new_tab=True).mark(
            "about-walkthrough"
        )
    with ui.row().classes("gap-1"):
        ui.label("Why I built it:")
        ui.link("the story behind Beam Navigator", about.STORY_URL, new_tab=True).mark(
            "about-story"
        )
    with ui.row().classes("gap-1"):
        ui.label("Feedback and comments:")
        ui.link(about.CONTACT_EMAIL, f"mailto:{about.CONTACT_EMAIL}").mark("about-email")
    ui.label(about.THIRD_PARTY)


MAX_BACKUP_BYTES = 50 * 1024 * 1024


def _restored_notice(kept_name: str) -> None:
    ui.notify(
        f"Restored. Your current data was saved as {kept_name}. Rotators are back in"
        " simulation: run Test connection to go live again. Reload any other open Beam"
        " Navigator pages.",
        type="positive", multi_line=True, timeout=0, close_button=True,
    )  # fmt: skip


def _data_panel(desk: Desk) -> None:
    """Backup and restore of the whole database (decision 34). A restore is checked before
    the dialog opens, keeps a copy of the current data, and sends no rotator command."""
    pending: dict[str, bytes | None] = {"data": None}
    folder = desk.data_dir()
    ui.label(
        "Back up saves everything (stations, nets, history, rotators and settings) in one"
        " file. Your QRZ login is not included: it stays in this computer's credential store."
    ).classes("text-caption")

    def backup() -> None:
        name, data = desk.backup()
        ui.download.content(data, name)

    ui.button("Back up", on_click=backup).mark("backup-download")

    async def chosen(e: events.UploadEventArguments) -> None:
        data = await e.file.read()
        upload.reset()
        try:
            checked_backup(data).close()
        except BackupError as exc:
            _error(exc)
            return
        pending["data"] = data
        dialog.open()

    def confirm() -> None:
        data = pending["data"]
        pending["data"] = None
        dialog.close()
        if data is None:
            return
        try:
            kept = desk.restore_backup(data)
        except BackupError as exc:
            _error(exc)
            return
        # Redraw every panel from the restored data: this page must not keep showing a
        # rotator as live (final review I3).
        ui.navigate.to(f"/settings?restored={quote(kept.name)}")

    def cancel() -> None:
        pending["data"] = None
        dialog.close()

    with ui.dialog().mark("restore-dialog") as dialog, ui.card():
        ui.label(
            "Restore replaces all your stations, nets, history and settings with this backup."
            f" Your current data is saved first in {folder / 'backups' if folder else 'a backup'}."
            " Every rotator will be put in simulation mode."
        )
        with ui.row():
            ui.button("Restore", on_click=confirm).props("color=negative").mark(
                "restore-confirm"
            )
            ui.button("Cancel", on_click=cancel).props("flat").mark("restore-cancel")
    upload = ui.upload(
        label="Restore from a backup (.db)", auto_upload=True, on_upload=chosen,
        max_file_size=MAX_BACKUP_BYTES,
        on_rejected=lambda: ui.notify("That file is too large to be a backup.", type="negative"),
    ).props('accept=".db"').mark("backup-restore")  # fmt: skip


SCOPE_TITLES = {"screen": "Dashboard and live net", "entry": "Net control entry line"}
MODIFIER_CODES = {"ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft",
                  "AltRight", "MetaLeft", "MetaRight"}  # fmt: skip


def _keys_panel(desk: Desk) -> None:
    """Change any shortcut by pressing the new key (decision 33). Space in Callsign and
    Grid is fixed and not listed."""
    recording: dict[str, str | None] = {"id": None}
    ui.label(
        "Press Change, then the new key. Escape cancels. Space always moves on from"
        " Callsign and Grid on the net control screen."
    ).classes("text-caption")
    if desk.keymap_discarded():
        ui.label("Some saved keys were not valid and were reset to their defaults.").classes(
            "text-warning"
        ).mark("keys-discarded")

    def start(action_id: str, action_label: str) -> None:
        recording["id"] = action_id
        prompt.set_text(f"Press the new key for {action_label}…")
        message.set_text("")
        keyboard.active = True
        dialog.open()

    def stop() -> None:
        recording["id"] = None
        keyboard.active = False
        prompt.set_text("")
        message.set_text("")
        dialog.close()

    def on_key(e: events.KeyEventArguments) -> None:
        action_id = recording["id"]
        if action_id is None or not e.action.keydown or e.action.repeat:
            return
        code = e.key.code
        if code in MODIFIER_CODES:
            return  # wait for the key that goes with Ctrl, Alt or Shift
        ctrl = e.modifiers.ctrl or e.modifiers.meta
        if code == "Escape" and not (ctrl or e.modifiers.alt or e.modifiers.shift):
            stop()
            return
        chord = Chord(code, ctrl=ctrl, alt=e.modifiers.alt, shift=e.modifiers.shift)
        try:
            desk.set_key(action_id, chord)
        except ValueError as exc:
            message.set_text(str(exc))  # keep listening for another key
            return
        stop()
        ui.notify(f"{label(chord)} saved")
        rows.refresh()

    def reset(action_id: str | None) -> None:
        try:
            desk.reset_key(action_id)
        except ValueError as exc:
            ui.notify(str(exc), type="warning")
            return
        rows.refresh()

    with ui.dialog() as dialog, ui.card().mark("key-dialog"):
        prompt = ui.label("").classes("text-lg")
        message = ui.label("").classes("text-negative").mark("key-message")
        ui.button("Cancel", on_click=stop).props("flat")
    dialog.on("hide", lambda: setattr(keyboard, "active", False))
    # ignore=[]: a key pressed while the Change button still has focus still counts.
    keyboard = ui.keyboard(on_key=on_key, active=False, ignore=[], repeating=False)

    @ui.refreshable
    def rows() -> None:
        keymap = desk.keymap()
        for scope, title in SCOPE_TITLES.items():
            ui.label(title).classes("text-lg mt-4")
            for action in (a for a in ACTIONS if a.scope == scope):
                with ui.row().classes("items-center gap-4").mark(f"keys-row-{action.id}"):
                    ui.label(action.label).classes("w-56")
                    ui.label(label(keymap[action.id])).classes("w-32 font-mono").mark(
                        f"key-{action.id}"
                    )
                    ui.button(
                        "Change", on_click=lambda a=action: start(a.id, a.label)
                    ).props("flat dense").mark(f"key-change-{action.id}")
                    ui.button(
                        "Reset", on_click=lambda a=action: reset(a.id)
                    ).props("flat dense").mark(f"key-reset-{action.id}")

    rows()
    ui.button("Reset all keys", on_click=lambda: reset(None)).props("outline").mark(
        "keys-reset-all"
    )


def _qrz_panel(desk: Desk, qrz: QrzClient) -> None:
    """Optional online lookup (requirements 4.9). The login goes only to the operating
    system's credential store; the password box is emptied after saving."""
    ui.label(
        "Look up names and grids on QRZ.com. Needs your QRZ username and password and a"
        " QRZ XML Data subscription. Your login is kept in this computer's credential store"
        " (Windows Credential Manager, macOS Keychain or the Linux keyring), never in Beam"
        " Navigator's files. Everything else works without it."
    ).classes("text-caption")

    @ui.refreshable
    def saved() -> None:
        username = saved_username()
        ui.label(f"Saved login: {username}" if username else "No QRZ login saved.").mark(
            "qrz-saved"
        )

    saved()
    with ui.row().classes("items-end gap-2"):
        username = ui.input("QRZ username", value=saved_username() or "").mark("qrz-username")
        password = ui.input("QRZ password", password=True, password_toggle_button=True).mark(
            "qrz-password"
        )
    status = ui.label("").mark("qrz-status")

    def save() -> None:
        try:
            save_login(username.value or "", password.value or "")
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        password.set_value("")
        qrz.forget_session()
        status.set_text("")
        ui.notify(f"Saved QRZ login for {(username.value or '').strip()}")
        saved.refresh()

    def clear() -> None:
        clear_login()
        qrz.forget_session()
        username.set_value("")
        password.set_value("")
        status.set_text("")
        saved.refresh()

    async def test_login() -> None:
        status.set_text("Contacting QRZ…")
        try:
            session = await run.io_bound(qrz.login)
        except QrzError as exc:
            status.set_text(str(exc))
            return
        if (session.sub_exp or "").strip().lower() == "non-subscriber":
            status.set_text(f"Logged in. {NON_SUBSCRIBER}")
        else:
            status.set_text(f"Logged in. Subscription until {session.sub_exp or 'unknown'}")

    with ui.row().classes("gap-2"):
        ui.button("Save", on_click=save).mark("qrz-save")
        ui.button("Test login", on_click=test_login).props("flat").mark("qrz-test")
        ui.button("Clear", on_click=clear).props("flat").mark("qrz-clear")
    ui.switch(
        "Look up calls automatically when nothing is saved for them",
        value=desk.settings.get(QRZ_AUTO) != "off",
        on_change=lambda e: desk.settings.set(QRZ_AUTO, "on" if e.value else "off"),
    ).mark("qrz-auto")


def _station_panel(desk: Desk) -> None:
    editing: dict[str, int | None] = {"id": None}

    @ui.refreshable
    def profile_list() -> None:
        for profile in desk.profiles.list():
            with ui.row().classes("items-center gap-4"):
                ui.label(f"{profile.name} · {profile.home_grid} · {profile.units}")
                if profile.is_active:
                    ui.badge("Active")
                elif profile.id is not None:
                    profile_id = profile.id
                    ui.button("Activate", on_click=lambda p=profile_id: activate(p)).props("flat")
                ui.button("Edit", on_click=lambda p=profile: load(p)).props("flat")

    def activate(profile_id: int) -> None:
        desk.profiles.activate(profile_id)
        profile_list.refresh()

    def load(profile: OperatorProfile) -> None:
        editing["id"] = profile.id
        name.set_value(profile.name)
        callsign.set_value(profile.callsign or "")
        grid.set_value(profile.home_grid)
        lat.set_value("" if profile.latlon is None else f"{profile.latlon.lat:g}")
        lon.set_value("" if profile.latlon is None else f"{profile.latlon.lon:g}")
        units.set_value(profile.units)
        timezone.set_value(profile.timezone)
        region.set_value(profile.home_region or "")

    def save() -> None:
        try:
            lat_value = _number(lat.value, "Latitude")
            lon_value = _number(lon.value, "Longitude")
            if (lat_value is None) != (lon_value is None):
                raise ValueError("Give both latitude and longitude, or neither.")
            latlon = None
            if lat_value is not None and lon_value is not None:
                latlon = LatLon(lat_value, lon_value)
            saved = desk.profiles.save(
                OperatorProfile(
                    id=editing["id"],
                    name=(name.value or "").strip(),
                    callsign=(callsign.value or "").strip() or None,
                    home_grid=(grid.value or "").strip(),
                    latlon=latlon,
                    units=units.value,
                    timezone=(timezone.value or "").strip() or "UTC",
                    home_region=(region.value or "").strip() or None,
                    is_active=False,
                )
            )
        except ValueError as exc:
            _error(exc)
            return
        editing["id"] = saved.id
        ui.notify(f"Saved {saved.name}")
        profile_list.refresh()

    profile_list()
    ui.separator()
    with ui.grid(columns=2).classes("w-full gap-2"):
        name = ui.input("Profile name").mark("profile-name")
        callsign = ui.input("Callsign (optional)").mark("profile-callsign")
        grid = ui.input("Home grid").mark("profile-grid")
        region = ui.input("Home state or province (optional)").mark("profile-region")
        lat = ui.input("Exact latitude (optional)").mark("profile-lat")
        lon = ui.input("Exact longitude (optional)").mark("profile-lon")
        units = ui.select(["km", "mi"], value="km", label="Units").mark("profile-units")
        timezone = ui.input("Time zone", placeholder="UTC").mark("profile-timezone")
    ui.button("Save station", on_click=save)


def _bands_panel(desk: Desk) -> None:
    @ui.refreshable
    def band_list() -> None:
        for band in desk.bands.list():
            with ui.row().classes("items-center gap-4"):
                ui.label(f"{band.name} · {band.mhz:g} MHz").classes("w-40")
                ui.switch(
                    "Long path", value=band.long_path,
                    on_change=lambda e, b=band.name: set_long_path(b, bool(e.value)),
                ).mark(f"long-path-{_marker(band.name)}")  # fmt: skip
                ui.button(
                    "Delete", on_click=lambda b=band.name: delete(b)
                ).props("flat").mark(f"delete-band-{_marker(band.name)}")

    def set_long_path(band: str, on: bool) -> None:
        desk.bands.set_long_path(band, on)

    def delete(band: str) -> None:
        try:
            desk.bands.delete(band)
        except ValueError as exc:
            _error(exc)
            return
        band_list.refresh()

    def add() -> None:
        try:
            mhz = _number(new_mhz.value, "MHz")
            if mhz is None:
                raise ValueError("Give the band's frequency in MHz.")
            desk.bands.add(new_name.value or "", mhz)
        except ValueError as exc:
            _error(exc)
            return
        new_name.set_value("")
        new_mhz.set_value("")
        band_list.refresh()

    band_list()
    ui.separator()
    with ui.row().classes("items-end gap-2"):
        new_name = ui.input("New band name", placeholder="13 cm").mark("band-name")
        new_mhz = ui.input("MHz", placeholder="2304").mark("band-mhz")
        ui.button("Add band", on_click=add)


def _aliases_panel(desk: Desk) -> None:
    @ui.refreshable
    def alias_list() -> None:
        for alias_name, target in desk.aliases.list():
            with ui.row().classes("items-center gap-4"):
                ui.label(f"{alias_name} → {target.kind} {target.value}")
                ui.button(
                    "Delete", on_click=lambda n=alias_name: delete(n)
                ).props("flat").mark(f"delete-alias-{alias_name}")

    def delete(alias_name: str) -> None:
        desk.aliases.delete(alias_name)
        alias_list.refresh()

    def add() -> None:
        try:
            desk.aliases.save(name.value or "", AliasTarget(kind.value, value.value or ""))
        except (TargetError, ValueError) as exc:
            _error(exc)
            return
        name.set_value("")
        value.set_value("")
        alias_list.refresh()

    alias_list()
    ui.separator()
    with ui.row().classes("items-end gap-2"):
        name = ui.input("Shortcode", placeholder="CLUB").mark("alias-name")
        kind = ui.select(ALIAS_KINDS, value="grid", label="Points to").mark("alias-kind")
        value = ui.input("Value", placeholder="FM29jw").mark("alias-value")
        ui.button("Add alias", on_click=add)


def _rotators_panel(desk: Desk) -> None:
    editing: dict[str, RotatorProfile | None] = {"profile": None}

    @ui.refreshable
    def rotator_list() -> None:
        rotators = desk.rotators()
        if not rotators:
            ui.label("No rotators yet. A new rotator always starts in simulation.")
        for profile in rotators:
            if profile.id is not None:
                _rotator_card(desk, profile, profile.id, load, rotator_list.refresh)

    def load(profile: RotatorProfile) -> None:
        editing["profile"] = profile
        name.set_value(profile.name)
        adapter.set_value(profile.adapter)
        host.set_value(profile.host or "")
        port.set_value("" if profile.port is None else str(profile.port))
        az_min.set_value(f"{profile.az_min:g}")
        az_max.set_value(f"{profile.az_max:g}")
        offset.set_value(f"{profile.offset:g}")
        speed.set_value("" if profile.speed_deg_per_s is None else f"{profile.speed_deg_per_s:g}")
        bands.set_value(list(profile.bands))

    def apply_preset(preset_name: str | None) -> None:
        travel = PRESETS.get(preset_name or "")
        if travel is not None:
            az_min.set_value(f"{travel.az_min:g}")
            az_max.set_value(f"{travel.az_max:g}")

    def save() -> None:
        before = editing["profile"]
        try:
            port_text = (port.value or "").strip()
            if port_text and not port_text.isdigit():
                raise ValueError(f"Port must be a whole number, not {port_text!r}.")
            az_min_value = _number(az_min.value, "Travel start")
            az_max_value = _number(az_max.value, "Travel end")
            if az_min_value is None or az_max_value is None:
                raise ValueError("Give the rotor's travel start and end, or pick a preset.")
            saved = desk.rotator_profiles.save(
                RotatorProfile(
                    id=None if before is None else before.id,
                    name=(name.value or "").strip(),
                    adapter=adapter.value,
                    host=(host.value or "").strip() or None,
                    port=int(port_text) if port_text else None,
                    az_min=az_min_value,
                    az_max=az_max_value,
                    offset=_number(offset.value, "Offset") or 0.0,
                    speed_deg_per_s=_number(speed.value, "Speed"),
                    bands=tuple(bands.value or ()),
                    live=False,
                    connection_tested=False,
                )
            )
        except ValueError as exc:
            _error(exc)
            return
        editing["profile"] = saved
        ui.notify(f"Saved {saved.name}")
        rotator_list.refresh()

    def new() -> None:
        editing["profile"] = None
        for field in (name, host, port, offset, speed):
            field.set_value("")
        adapter.set_value("simulation")
        apply_preset(next(iter(PRESETS)))
        bands.set_value([])

    rotator_list()
    ui.separator()
    ui.label("Add or edit a rotator").classes("text-lg")
    with ui.grid(columns=2).classes("w-full gap-2"):
        name = ui.input("Rotator name", placeholder="VHF").mark("rotator-name")
        adapter = ui.select(ADAPTERS, value="simulation", label="Adapter").mark("rotator-adapter")
        host = ui.input("Host", placeholder="127.0.0.1").mark("rotator-host")
        port = ui.input("Port", placeholder="12000 (PstRotator) or 4533 (rotctld)").mark(
            "rotator-port"
        )
        preset = ui.select(
            list(PRESETS), label="Travel preset", on_change=lambda e: apply_preset(e.value)
        ).mark("rotator-preset")
        speed = ui.input("Speed, °/s (optional)").mark("rotator-speed")
        az_min = ui.input("Travel start, rotor °", value="0").mark("rotator-min")
        az_max = ui.input("Travel end, rotor °", value="360").mark("rotator-max")
        offset = ui.input("Offset, ° (rotor = true + offset)", value="0").mark("rotator-offset")
        bands = ui.select(
            [band.name for band in desk.bands.list()], multiple=True, value=[],
            label="Bands it serves",
        ).mark("rotator-bands")  # fmt: skip
    fields = {"rotator-name": name, "rotator-adapter": adapter, "rotator-host": host,
              "rotator-port": port, "rotator-preset": preset, "rotator-speed": speed,
              "rotator-min": az_min, "rotator-max": az_max, "rotator-offset": offset,
              "rotator-bands": bands}  # fmt: skip
    for marker, field in fields.items():
        field.props["hint"] = ROTATOR_HELP[marker]  # set directly: the copy has apostrophes
    with ui.row():
        ui.button("Save rotator", on_click=save)
        ui.button("New rotator", on_click=new).props("flat")
    with ui.expansion("About travel and stops", icon="help_outline").classes("w-full").mark(
        "rotator-about"
    ):
        for line in ABOUT_TRAVEL:
            ui.label(line)


def _rotator_card(
    desk: Desk,
    profile: RotatorProfile,
    rotator_id: int,
    load: Callable[[RotatorProfile], None],
    refresh: Callable[[], object],
) -> None:
    with ui.card().classes("w-full"):
        where = "" if profile.host is None else f" · {profile.host}:{profile.port}"
        ui.label(
            f"{profile.name} · {profile.adapter}{where} · travel "
            f"{profile.az_min:g}–{profile.az_max:g}° · bands {', '.join(profile.bands) or '—'}"
        ).classes("font-bold")
        result = ui.label("").mark(f"rotator-result-{rotator_id}")

        def test_connection() -> None:
            outcome = desk.service.test_connection(rotator_id)
            result.set_text(outcome.message)
            refresh()
            ui.notify(outcome.message, type="positive" if outcome.ok else "negative")

        def set_live(on: bool) -> None:
            try:
                desk.rotator_profiles.set_live(rotator_id, on)
            except (RotatorNotTested, ValueError) as exc:
                _error(exc)
            refresh()

        def test_move() -> None:
            try:
                heading = _number(heading_input.value, "Heading")
                if heading is None:
                    raise ValueError("Give a heading for the test move.")
            except ValueError as exc:
                _error(exc)
                return
            outcome = desk.service.test_move(rotator_id, heading)
            result.set_text(f"Simulated: {outcome.status}")

        with ui.row().classes("items-center gap-4"):
            ui.button("Edit", on_click=lambda: load(profile)).props("flat").mark(
                f"edit-{rotator_id}"
            )
            ui.button("Test connection", on_click=test_connection).props("flat").mark(
                f"test-connection-{rotator_id}"
            )
            can_go_live = profile.adapter != "simulation" and profile.connection_tested
            ui.switch(
                LIVE_LABEL if profile.live else SIMULATION_LABEL, value=profile.live,
                on_change=lambda e: set_live(bool(e.value)),
            ).mark(f"live-{rotator_id}").set_enabled(can_go_live)  # fmt: skip
        with ui.row().classes("items-end gap-2"):
            heading_input = ui.input("Test heading, °").mark(f"test-heading-{rotator_id}")
            ui.button("Test move in simulation", on_click=test_move).props("flat").mark(
                f"test-move-{rotator_id}"
            )
        records = desk.recent_commands(rotator_id, LOG_LINES)
        if records:
            with ui.expansion("Recent commands"):
                for record in records:
                    ui.label(
                        f"{record.at} · {record.target_label or ''} · "
                        f"{'ok' if record.ok else 'failed'} · {record.message}"
                    ).classes("text-caption")
