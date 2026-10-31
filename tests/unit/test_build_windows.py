"""The Windows build refuses to ship the project's local path (decision 38), and carries
the copyright and third-party notices (decision 41)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "build_windows", ROOT / "packaging" / "build_windows.py"
)
assert spec is not None and spec.loader is not None
build_windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_windows)


def test_notices_cover_every_runtime_package_and_python() -> None:
    names = {dist.metadata["Name"].lower() for dist in build_windows.runtime_distributions()}
    assert {"nicegui", "keyring", "platformdirs", "tzdata", "starlette", "uvicorn"} <= names
    assert names.isdisjoint({"beam-navigator", "pytest", "ruff", "pyinstaller"})
    text = build_windows.notices_text()
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in text
    assert "Permission is hereby granted, free of charge" in text  # an MIT text, in full
    assert "(c) 2018-present Yuxi (Evan) You" in text  # Vue's banner, from NiceGUI's files


def test_version_info_carries_the_copyright(tmp_path: Path) -> None:
    from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file

    path = tmp_path / "version_info.txt"
    path.write_text(build_windows.version_info("0.0.1"), encoding="utf-8")
    info = str(load_version_info_from_text_file(str(path)))
    assert "Copyright © 2026 Terry Rossi, N2LQH" in info
    assert "filevers=(0, 0, 1, 0)" in info
    assert "'ProductVersion', '0.0.1'" in info


def test_finds_the_path_in_either_slash_style_and_case() -> None:
    root = Path("C:/Users/someone/projects/beam_navigator")
    url = b'{"url":"file:///C:/Users/someone/projects/beam_navigator"}'
    assert build_windows.holds_path(url, root)
    assert build_windows.holds_path(rb"c:\users\someone\projects\beam_navigator\app.py", root)
    assert not build_windows.holds_path(rb"beam_navigator\ui\app.py", root)


def test_exe_has_no_console_window() -> None:
    # owner, 2026-10-31: no black window beside the app; Quit stops it (decision 44)
    assert "--noconsole" in build_windows.OPTIONS


def test_installer_command_passes_the_version() -> None:  # decision 45
    iscc = Path("C:/Inno/ISCC.exe")
    command = build_windows.installer_command(iscc, "1.2.0")
    assert command == [str(iscc), "/DAppVersion=1.2.0", "/Q",
                       str(ROOT / "packaging" / "BeamNavigator.iss")]  # fmt: skip


def test_installer_script_installs_per_user_with_a_start_menu_entry() -> None:
    script = (ROOT / "packaging" / "BeamNavigator.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in script  # no administrator prompt
    assert r'Name: "{autoprograms}\Beam Navigator"; Filename: "{app}\BeamNavigator.exe"' in script
    assert "OutputBaseFilename=BeamNavigatorSetup" in script
    assert "AppId={{1215C06F-B505-44B5-9992-1DB60B0C4D65}" in script  # never changes
