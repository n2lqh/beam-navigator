"""Entry point of the Windows executable (decision 36): the same app as beamnav-ui."""

import multiprocessing

from beam_navigator.ui.app import main

if __name__ in {"__main__", "__mp_main__"}:  # NiceGUI runs the main module twice
    multiprocessing.freeze_support()
    main()
