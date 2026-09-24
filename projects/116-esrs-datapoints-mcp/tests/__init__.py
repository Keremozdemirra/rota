"""Lets the test modules import their helpers (support, xlsxmake) both when discovered with
`-s tests -t .` (as the package `tests`) and with `-s tests` alone."""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
