"""Build dist/BeamNavigator.exe, a single-file Windows program (decision 36).

Run with the app stopped (Windows locks a running program's files):
    uv run python packaging/build_windows.py

The options are the ones the 2026-10-29 trial build proved: NiceGUI's own files, the
package data (migrations, regions, example nets and rosters), tzdata for net time zones,
and the Windows Credential Manager backend for the QRZ login.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "BeamNavigator"
OPTIONS = [
    "--noconfirm", "--clean", "--onefile", "--name", NAME,
    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    "--collect-all", "nicegui",
    "--collect-data", "beam_navigator",
    "--collect-data", "tzdata",
    "--hidden-import", "keyring.backends.Windows",
    str(ROOT / "packaging" / "beamnav_entry.py"),
]  # fmt: skip


def holds_path(data: bytes, root: Path) -> bool:
    """True when data names the project folder, with either slash style, in any case."""
    text = data.decode("utf-8", "replace").lower().replace("\\", "/")
    return root.as_posix().lower() in text


def files_holding_path(exe: Path, root: Path) -> list[str]:
    """Bundled files that name this computer's project folder (decision 38): the .exe is
    meant to be shared, and the folder holds the builder's user name."""
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    return [name for name in archive.toc if holds_path(archive.extract(name) or b"", root)]


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    import PyInstaller.__main__

    exe = ROOT / "dist" / f"{NAME}.exe"
    exe.unlink(missing_ok=True)  # never report an old build as new
    PyInstaller.__main__.run(OPTIONS)
    if not exe.exists():
        raise SystemExit("The build did not produce an executable; see the messages above.")
    leaks = files_holding_path(exe, ROOT)
    if leaks:
        exe.unlink()
        raise SystemExit(f"Removed the build: these files hold {ROOT}: {', '.join(leaks)}")
    print(f"Built {exe} ({exe.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
