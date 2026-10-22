"""Entry point used by PyInstaller (a frozen app can't use ``python -m``)."""

import multiprocessing
import sys

from stripsafe.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # lets the worker processes start inside the frozen app
    sys.exit(main())
