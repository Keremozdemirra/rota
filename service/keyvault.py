"""Custody of somebody else's Anthropic API key, for as short a time as possible.

Be clear about what this is. A bring-your-own-key platform that executes agents
server-side must hold the caller's key in the server process for the duration of
the run. There is no cryptography that removes this: the process that calls the
Anthropic API needs the plaintext key. Everything below is about shrinking the
window and the blast radius, not about pretending the trust requirement is gone.

  - the key exists only in process memory, in one dict, never on disk
  - the client holds an opaque token, never the key, after the first request
  - TTL is short and sliding; expiry drops the reference
  - __repr__/__str__ are redacted so a stray log line cannot spill it
  - a per-session USD cap is enforced by the SDK, so a stolen token cannot
    run up an unbounded bill on the owner's account

The consequence for deployment: single process, no worker fan-out, no Redis,
no session affinity puzzle to get wrong. Scale by running more isolated
instances, not by sharing this store.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TTL_S = int(os.environ.get("ROTA_SESSION_TTL", "1800"))
MAX_SESSIONS = int(os.environ.get("ROTA_MAX_SESSIONS", "50"))
DEFAULT_SPEND_CAP = float(os.environ.get("ROTA_SPEND_CAP_USD", "2.00"))
ANTHROPIC_VERSION = "2023-06-01"


class SessionError(RuntimeError):
    pass


class Secret:
    """A string that refuses to print itself."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<Secret redacted>"

    __str__ = __repr__


@dataclass
class Session:
    token: str
    key: Secret | None            # None means owner mode: use ambient credentials
    created_at: float
    last_seen: float
    spend_cap_usd: float
    spent_usd: float = 0.0
    runs: int = 0
    label: str = ""                       # e.g. "sk-ant-…4f2a", for the UI only
    history: list[dict] = field(default_factory=list)

    def remaining_usd(self) -> float:
        return max(0.0, self.spend_cap_usd - self.spent_usd)

    def public(self) -> dict:
        return {
            "token": self.token,
            "key_label": self.label,
            "expires_in_s": int(TTL_S - (time.time() - self.last_seen)),
            "spend_cap_usd": self.spend_cap_usd,
            "spent_usd": round(self.spent_usd, 4),
            "remaining_usd": round(self.remaining_usd(), 4),
            "runs": self.runs,
        }


class Vault:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def open(self, api_key: str, spend_cap_usd: float | None = None) -> Session:
        api_key = api_key.strip()
        if not api_key.startswith("sk-ant-"):
            raise SessionError("that does not look like an Anthropic API key")
        verify_key(api_key)                     # fail before we store anything
        self._evict_expired()
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise SessionError("server at capacity — try again shortly")
            now = time.time()
            session = Session(
                token=secrets.token_urlsafe(32),
                key=Secret(api_key),
                created_at=now,
                last_seen=now,
                spend_cap_usd=min(float(spend_cap_usd or DEFAULT_SPEND_CAP), DEFAULT_SPEND_CAP),
                label=f"{api_key[:10]}…{api_key[-4:]}",
            )
            self._sessions[session.token] = session
        return session

    def get(self, token: str) -> Session:
        self._evict_expired()
        with self._lock:
            session = self._sessions.get(token or "")
            if session is None:
                raise SessionError("session expired or unknown — enter your key again")
            session.last_seen = time.time()
            return session

    def close(self, token: str) -> bool:
        with self._lock:
            return self._sessions.pop(token or "", None) is not None

    def _evict_expired(self) -> None:
        cutoff = time.time() - TTL_S
        with self._lock:
            for token in [t for t, s in self._sessions.items() if s.last_seen < cutoff]:
                del self._sessions[token]

    # -- accounting --------------------------------------------------------

    def charge(self, session: Session, usd: float, entry: dict) -> None:
        """Charged against the object, not the token, so an owner-mode session
        that was never registered here still has its cap enforced."""
        with self._lock:
            session.spent_usd += max(0.0, usd or 0.0)
            session.runs += 1
            session.history.append(entry)
            del session.history[:-20]

    def assert_budget(self, session: Session, need_usd: float) -> None:
        if session.remaining_usd() < need_usd:
            raise SessionError(
                f"session spend cap reached (${session.spend_cap_usd:.2f}). "
                "Start a new session to continue."
            )


def verify_key(api_key: str) -> None:
    """One free round-trip against /v1/models. Rejects a typo before the user
    watches a workflow fail three minutes in, and proves the key is live
    without spending a token on it."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models?limit=1",
        headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SessionError("Anthropic rejected that key (401/403)") from None
        raise SessionError(f"key check failed: HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise SessionError(f"cannot reach api.anthropic.com: {exc.reason}") from None


def owner_session(spend_cap_usd: float = 10.0) -> Session:
    """A session for the operator's own unattended runs. No key is held: the
    Claude Code CLI the SDK spawns uses whatever credentials it already has,
    which for a Max subscription is not an API key at all."""
    now = time.time()
    return Session(token="owner", key=None, created_at=now, last_seen=now,
                   spend_cap_usd=spend_cap_usd, label="ambient credentials")


VAULT = Vault()
