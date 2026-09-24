# Lets `python3 -m unittest discover -s tests -t .` import the test modules' shared helper as `support`.
import sys
from pathlib import Path

for _p in (str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
