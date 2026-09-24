#!/usr/bin/env python3
"""Runs vsme-kit from a checkout or from the Claude Code plugin directory, without installing it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vsme_kit.cli import main  # noqa: E402

raise SystemExit(main())
