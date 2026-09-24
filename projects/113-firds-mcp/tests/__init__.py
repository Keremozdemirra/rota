"""Makes `import support` work whether discovery runs with `-t .` (package) or without it."""
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
