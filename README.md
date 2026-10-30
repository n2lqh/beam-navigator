# Beam Navigator

Beam Navigator tells an amateur radio operator **which way to point** a directional antenna, and turns the rotator when asked. Type a callsign, grid square or shortcode, or paste a net roster, and get true bearings and distances **from your own station**. Pressing Rotate turns the antenna. Net controllers use the same app to log check-ins quickly. It works offline, on Windows, macOS, Linux and Raspberry Pi.

**Using it:** see the [user guide](docs/user-guide.md).

## Development

```
uv sync                         # install
uv run pytest                   # tests
uv run ruff check . && uv run mypy src/beam_navigator/core
uv run beamnav bearing FN20ok   # CLI bearing
uv run beamnav-rotor --adapter simulation --az 90
uv run beamnav-ui               # start the web UI
uv run python packaging/build_windows.py   # Windows .exe in dist/ (stop the app first)
```

The specification is [docs/requirements.md](docs/requirements.md); design decisions are in [docs/decisions.md](docs/decisions.md).

## License

Copyright © 2026 Terry Rossi, N2LQH.

Beam Navigator is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See [LICENSE](LICENSE) for details.

The Windows program bundles Python and open-source libraries under their own licences; their notices are in `THIRD_PARTY_NOTICES.txt`, published with each release.
