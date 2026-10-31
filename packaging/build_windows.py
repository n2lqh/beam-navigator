"""Build dist/BeamNavigator.exe, a single-file Windows program (decision 36).

Run with the app stopped (Windows locks a running program's files):
    uv run python packaging/build_windows.py

The options are the ones the 2026-10-29 trial build proved: NiceGUI's own files, the
package data (migrations, regions, example nets and rosters), tzdata for net time zones,
and the Windows Credential Manager backend for the QRZ login.

The build also writes THIRD_PARTY_NOTICES.txt, bundles it, and copies it beside the .exe
for the release; Windows file properties carry the version and copyright (decision 41).

Then Inno Setup 6 wraps both in dist/BeamNavigatorSetup.exe, which adds the Start menu entry
and an uninstaller (decision 45). Install it once with:
    winget install --id JRSoftware.InnoSetup --exact --scope user
"""

import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from beam_navigator import __version__, about

ROOT = Path(__file__).resolve().parent.parent
NAME = "BeamNavigator"
NOTICES = "THIRD_PARTY_NOTICES.txt"
LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.I)
BANNER = re.compile(r"\A\s*/\*[!*]?(.*?)\*/", re.S)
RULE = "=" * 78
INSTALLER = "BeamNavigatorSetup.exe"
INSTALLER_SCRIPT = ROOT / "packaging" / "BeamNavigator.iss"
OPTIONS = [
    "--noconfirm", "--clean", "--onefile", "--noconsole", "--name", NAME,
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


def runtime_distributions() -> list[metadata.Distribution]:
    """Installed packages beam-navigator needs on this platform, dependencies included."""
    from packaging.requirements import Requirement

    found: dict[str, metadata.Distribution] = {}
    todo = list(metadata.requires("beam-navigator") or [])
    while todo:
        requirement = Requirement(todo.pop())
        key = re.sub(r"[-_.]+", "-", requirement.name).lower()
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        if key not in found:
            found[key] = metadata.distribution(requirement.name)
            todo.extend(found[key].requires or [])
    return sorted(found.values(), key=lambda dist: dist.metadata["Name"].lower())


def _licence_texts(dist: metadata.Distribution) -> list[str]:
    files = [f for f in dist.files or [] if f.parts[0].endswith(".dist-info")
             and LICENSE_FILE.match(f.name)]  # fmt: skip
    if not files:
        raise SystemExit(f"{dist.metadata['Name']} ships no licence file; its notice is unknown.")
    return [dist.locate_file(f).read_text(encoding="utf-8", errors="replace") for f in files]


def _python_licence() -> str:
    base = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for path in (base / "LICENSE.txt", base / "lib" / version / "LICENSE.txt"):
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise SystemExit(f"Python's LICENSE.txt was not found under {base}.")


def _nicegui_web_files() -> tuple[list[str], list[str]]:
    """NiceGUI's bundled web files: the licence banners they carry, and those without one."""
    import nicegui

    static = Path(nicegui.__file__).parent / "static"
    banners, bare = [], []
    for path in sorted(p for p in static.rglob("*") if p.is_file()):
        name = path.relative_to(static).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
        match = BANNER.match(text) if path.suffix in {".js", ".mjs", ".css"} else None
        banner = match.group(1) if match else ""
        if re.search(r"licen[cs]e|\(c\)|copyright", banner, re.I):
            lines = (line.strip().lstrip("*").strip() for line in banner.splitlines())
            banners.append(f"{name}:\n" + "\n".join(line for line in lines if line))
        else:
            bare.append(name)
    return banners, bare


def notices_text() -> str:
    """THIRD_PARTY_NOTICES.txt: every bundled package's own licence text, in full."""
    parts = [
        f"Third-party notices for {about.TITLE}",
        f"{about.COPYRIGHT}, licensed {about.LICENSE_ID}; see LICENSE.\n"
        "The Windows program also contains the software below, each under its own licence.",
        f"{RULE}\nPython {sys.version.split()[0]}\n{RULE}\n{_python_licence()}",
    ]
    for dist in runtime_distributions():
        licence = dist.metadata.get("License-Expression") or ""
        title = f"{dist.metadata['Name']} {dist.version}" + (f" ({licence})" if licence else "")
        parts.append(f"{RULE}\n{title}\n{RULE}\n" + "\n\n".join(_licence_texts(dist)))
    banners, bare = _nicegui_web_files()
    parts.append(
        f"{RULE}\nWeb files bundled inside NiceGUI, with the notices they carry\n{RULE}\n"
        + "\n\n".join(banners)
        + "\n\nFiles without a notice of their own, distributed as part of NiceGUI:\n"
        + "\n".join(bare)
    )
    return "\n\n".join(parts) + "\n"


def version_info(version: str) -> str:
    """PyInstaller's version file: the Details tab of the .exe's Windows properties."""
    numbers = tuple(([int(part) for part in version.split(".")] + [0, 0, 0])[:4])
    strings = {
        "CompanyName": about.HOLDER,
        "FileDescription": about.PRODUCT,
        "FileVersion": version,
        "InternalName": NAME,
        "LegalCopyright": f"{about.COPYRIGHT}. Licence: {about.LICENSE_ID}.",
        "OriginalFilename": f"{NAME}.exe",
        "ProductName": about.PRODUCT,
        "ProductVersion": version,
    }
    entries = ",\n".join(
        f"      StringStruct({key!r}, {value!r})" for key, value in strings.items()
    )
    return f"""# -*- coding: utf-8 -*-
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
{entries}
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def find_iscc() -> Path | None:
    """Inno Setup's compiler: on PATH, or where a per-user or all-users install puts it."""
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    homes = [os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
             os.environ.get("ProgramFiles", "")]  # fmt: skip
    for home in homes:
        if home and (Path(home) / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(home) / "Inno Setup 6" / "ISCC.exe"
        if home and (Path(home) / "Programs" / "Inno Setup 6" / "ISCC.exe").exists():
            return Path(home) / "Programs" / "Inno Setup 6" / "ISCC.exe"
    return None


def installer_command(iscc: Path, version: str) -> list[str]:
    return [str(iscc), f"/DAppVersion={version}", "/Q", str(INSTALLER_SCRIPT)]


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    import PyInstaller.__main__

    exe = ROOT / "dist" / f"{NAME}.exe"
    iscc = find_iscc()
    if iscc is None:  # before the long build, not after it
        raise SystemExit(
            "Inno Setup 6 was not found. Install it once with:\n"
            "    winget install --id JRSoftware.InnoSetup --exact --scope user"
        )
    exe.unlink(missing_ok=True)  # never report an old build as new
    setup = ROOT / "dist" / INSTALLER
    setup.unlink(missing_ok=True)
    (ROOT / "dist" / NOTICES).unlink(missing_ok=True)
    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    notices = work / NOTICES
    notices.write_text(notices_text(), encoding="utf-8")
    version_file = work / "version_info.txt"
    version_file.write_text(version_info(__version__), encoding="utf-8")
    PyInstaller.__main__.run(
        [*OPTIONS, "--version-file", str(version_file), "--add-data", f"{notices}{os.pathsep}."]
    )
    if not exe.exists():
        raise SystemExit("The build did not produce an executable; see the messages above.")
    leaks = files_holding_path(exe, ROOT)
    if leaks:
        exe.unlink()
        raise SystemExit(f"Removed the build: these files hold {ROOT}: {', '.join(leaks)}")
    shutil.copyfile(notices, ROOT / "dist" / NOTICES)
    subprocess.run(installer_command(iscc, __version__), check=True)
    if not setup.exists():
        raise SystemExit("Inno Setup did not produce the installer; see the messages above.")
    print(f"Built {exe} ({exe.stat().st_size / 1_000_000:.0f} MB), dist/{NOTICES} and {setup}")


if __name__ == "__main__":
    main()
