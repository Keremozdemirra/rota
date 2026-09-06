#!/usr/bin/env python3
"""mcp_health — do the configured MCP endpoints still answer?

`drift` compares the install against the record. It cannot see that a server
in the record stopped existing: wolfram sat in the config returning 503 and
then 404 for a whole day, appearing in every session's startup banner, and
nothing here noticed — the inventory still counted it as a capability.

Weekly, not daily. An endpoint that is down for an hour is not an endpoint
that is gone, and a check that cannot tell those apart teaches its reader to
skip it. Weekly cadence lets a transient outage pass and still catches a dead
address within days.

Status is reported, never interpreted as death:
  200 with serverInfo  the server is there and open
  200 without it       something answered; not this protocol
  401                  the server is there and gated — positive evidence
  404 / DNS failure     the recorded address is wrong
  5xx                  the server is having a bad day; say so, decide later

    python3 tools/mcp_health.py [--json]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CONFIG = Path.home() / ".claude.json"
HANDSHAKE = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "rota-health", "version": "1"}},
}).encode()


def probe(url: str, timeout: float = 10.0) -> tuple[str, str]:
    """Probe with curl, not urllib.

    urllib on this machine cannot verify TLS — it has no certificate store
    unless one is installed for it — so every endpoint came back
    CERTIFICATE_VERIFY_FAILED and this checker reported fourteen live servers
    as dead. curl uses the system store and works. The lesson is not "use
    curl": it is that a checker's own dependencies fail too, and when they do
    the failure wears the costume of the thing being checked.
    """
    r = subprocess.run(
        ["curl", "-s", "-m", str(int(timeout)), "-o", "-", "-w", "\n%{http_code}",
         "-X", "POST", url,
         "-H", "Content-Type: application/json",
         "-H", "Accept: application/json, text/event-stream",
         "-d", HANDSHAKE.decode()],
        capture_output=True, text=True)
    if r.returncode != 0:
        return "unreachable", f"curl exit {r.returncode}: {(r.stderr or '').strip()[:44]}"
    body, _, code = r.stdout.rpartition("\n")
    code = code.strip()
    if "serverInfo" in body or "protocolVersion" in body:
        return "ok", "answers the protocol"
    if code == "401":
        return "gated", "401 — the server is there and wants credentials"
    if code == "404":
        return "gone", "404 — the recorded address is wrong"
    if code.startswith("5"):
        return "unwell", f"{code} — a bad day, not necessarily gone"
    if code == "000":
        return "unreachable", "no response — DNS, TLS or the host is down"
    if code == "200":
        return "not-mcp", "HTTP 200 but no serverInfo — something else is there"
    return "odd", f"HTTP {code}"


def main() -> int:
    if not CONFIG.exists():
        print("  no ~/.claude.json")
        return 0
    servers = (json.loads(CONFIG.read_text(encoding="utf-8")).get("mcpServers") or {})
    http = {k: v.get("url") for k, v in servers.items() if v.get("url")}
    local = sorted(k for k, v in servers.items() if not v.get("url"))

    results = {}
    for name, url in sorted(http.items()):
        results[name] = probe(url)

    if "--json" in sys.argv:
        print(json.dumps({"http": {k: {"state": v[0], "note": v[1]}
                                   for k, v in results.items()},
                          "local": local}, indent=2))
        return 0

    bad = {k: v for k, v in results.items() if v[0] in ("gone", "not-mcp", "unreachable", "error")}
    # If every single endpoint failed the same way, the thing that broke is
    # almost certainly here, not out there. Fourteen independent services do
    # not go down together with an identical message.
    if results and len(bad) == len(results) and len({v[1][:24] for v in bad.values()}) == 1:
        print(f"  all {len(results)} endpoints failed identically:"
              f" {next(iter(bad.values()))[1]}")
        print("  That is this machine, not fourteen services. Fix the local cause")
        print("  before reading anything below as a finding about a server.")
        return 1
    ok = sum(1 for v in results.values() if v[0] in ("ok", "gated"))
    print(f"  {len(http)} remote endpoints · {ok} answering · {len(local)} local (not probed)")
    for name, (state, note) in results.items():
        if state in ("ok", "gated"):
            continue
        print(f"    [{state}] {name}: {note}")
    if bad:
        print("\n  → a recorded server that cannot answer is not a capability. Decide:")
        print("    fix the address, or remove it and write down why.")
        return 1
    print("  every recorded endpoint answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
