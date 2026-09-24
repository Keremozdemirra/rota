#!/usr/bin/env python3
"""pkg-vitals hook: the same checks, before Claude Code runs an install command.

PreToolUse on Bash and PowerShell, one handler for both (hooks/hooks.json). The
hook sees every shell command; one that names no installer (npm, pip, uv, ...)
ends here, before pkg_vitals is even imported. For the rest it finds every
package the command would fetch from npm or PyPI, including inside compound
lines such as `cd app && npm i a b; pip install c`, checks each one, and if any
has a serious flag (not on the registry, first published less than 30 days
ago, deprecated, yanked, archived, a security placeholder) it answers with
permissionDecision "ask" and the facts as the reason. The person decides; the
hook never denies. One lock file per tool_use_id makes sure a tool call gets
one working process even when the handler is installed twice.

Healthy packages pass without a word. So does anything the hook cannot parse,
reach or resolve within its time budget (PKG_VITALS_TIMEOUT seconds per
request, default 5; PKG_VITALS_BUDGET seconds in all, default 15).

The logic lives in pkg_vitals.py (hook_main), so the plugin and the
`pkg-vitals-hook` command from PyPI run the same code.
"""
import json
import re
import sys
from pathlib import Path

# The same pattern as pkg_vitals.QUICK (a test keeps them equal); here so that a
# command naming no installer never pays for importing the rest.
QUICK = re.compile(r"(?i)\b(npm|npx|pnpm|pnpx|yarn|bun|bunx|pip[0-9.]*|pipx|python[0-9.]*|pypy[0-9.]*|py|uv|uvx|poetry)\b")


def main() -> int:
    raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        command = payload["tool_input"]["command"]
    except (ValueError, UnicodeDecodeError, KeyError, TypeError):
        return 0
    if not isinstance(command, str) or not QUICK.search(command):
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pkg_vitals
    return pkg_vitals.hook_main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
