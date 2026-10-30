"""The Windows build refuses to ship the project's local path (decision 38)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "build_windows", ROOT / "packaging" / "build_windows.py"
)
assert spec is not None and spec.loader is not None
build_windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_windows)


def test_finds_the_path_in_either_slash_style_and_case() -> None:
    root = Path("C:/Users/someone/projects/beam_navigator")
    url = b'{"url":"file:///C:/Users/someone/projects/beam_navigator"}'
    assert build_windows.holds_path(url, root)
    assert build_windows.holds_path(rb"c:\users\someone\projects\beam_navigator\app.py", root)
    assert not build_windows.holds_path(rb"beam_navigator\ui\app.py", root)
