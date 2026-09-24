"""A local stand-in for api.github.com that answers from the fixture files.

It speaks real HTTP on 127.0.0.1, so the client's redirect handling, error
handling and timeouts run exactly as they do against GitHub.
"""
import atexit
import json
import os
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Nothing under test reads the home directory. Every test module imports this
# one, so pointing HOME at an empty directory here makes sure of it.
HOME = tempfile.mkdtemp(prefix="awesome-vitals-test-home-")
os.environ["HOME"] = os.environ["USERPROFILE"] = HOME
atexit.register(shutil.rmtree, HOME, True)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CENSUS = (FIXTURES / "census.json").as_uri()
TOKEN = "not-a-real-token"  # a placeholder: the tests check where a token goes, never with a real one


def fixture(name):
    return json.loads((FIXTURES / "github" / name).read_text(encoding="utf-8"))


# The fixture behind each repository in tests/fixtures/sample.md. Anything else
# gets the recorded sandbox 403.
SAMPLE_ROUTES = {
    "/repos/Keremozdemirra/agent-vitals": "agent-vitals.200.json",
    "/repos/octocat/Hello-World": "hello-world.200.json",
    "/repos/octocat/archived-example": "archived.200.json",
    "/repos/octocat/unlicensed-example": "nolicence.200.json",
    "/repos/octocat/other-licence-example": "noassertion.200.json",
    "/repos/octocat/renamed-example": "renamed.301.json",
    "/repositories/1296269": "hello-world.200.json",
    "/repos/octocat/gone-example": "gone.404.json",
}


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a client that timed out and left is what the timeout test is for


class FakeGitHub:
    """`routes` maps a path (any case, as GitHub's) to a fixture file name, a fixture dict,
    or {"raw": text} written to the socket as it is."""

    def __init__(self, routes=None, default="sandbox.403.json", delay=0.0):
        self.routes = {k.lower(): v for k, v in (routes if routes is not None else SAMPLE_ROUTES).items()}
        self.default, self.delay = default, delay
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                if outer.delay:
                    time.sleep(outer.delay)
                fx = outer.routes.get(self.path.lower(), outer.default)
                fx = fixture(fx) if isinstance(fx, str) else fx
                if "raw" in fx:
                    # bytes as they go on the wire, for broken responses send_response cannot produce
                    self.wfile.write(fx["raw"].encode("latin-1"))
                    return
                body = fx["body"]
                data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
                self.send_response(fx["status"])
                for k, v in fx["headers"].items():
                    # the recorded Location names api.github.com; this server stands in for it
                    self.send_header(k, v.replace("https://api.github.com", outer.url) if k.lower() == "location" else v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        # a short poll so shutdown() returns at once rather than after half a second
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def paths(self):
        return [p for p, _ in self.requests]
