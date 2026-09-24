#!/usr/bin/env python3
"""pkg-vitals hook: the same checks, before Claude Code runs an install command.

PreToolUse on Bash and PowerShell. Claude Code runs this for the install
commands listed in hooks/hooks.json (npm install, pip install, uv add, npx, uvx
and the rest). It finds every package the command would fetch from npm or
PyPI, including inside compound lines such as `cd app && npm i a b; pip
install c`, checks each one, and if any has a serious flag (not on the
registry, first published less than 30 days ago, deprecated, yanked, archived,
a security placeholder) it answers with permissionDecision "ask" and the facts
as the reason. The person decides; the hook never denies.

Healthy packages pass without a word. So does anything the hook cannot parse,
reach or resolve within its time budget (PKG_VITALS_TIMEOUT seconds per
request, default 5; PKG_VITALS_BUDGET seconds in all, default 15): a hook that
blocks work because the network is slow is a hook people uninstall.

The logic lives in pkg_vitals.py (hook_main), so the plugin and the
`pkg-vitals-hook` command from PyPI run the same code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pkg_vitals  # noqa: E402


def main() -> int:
    return pkg_vitals.hook_main()


if __name__ == "__main__":
    raise SystemExit(main())
