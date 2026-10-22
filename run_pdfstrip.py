"""Entry point used by PyInstaller (a frozen app can't use ``python -m``)."""

import sys

from pdfstrip.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
