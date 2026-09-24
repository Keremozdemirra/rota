"""Repository facts from the GitHub API, the census behind it, and action.yml downloads. Local HTTP only."""
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import (CENSUS, SHA_A, FakeGitHub, Isolated, action_yml, raw, repo_doc, text_file)  # noqa: E402

import action_vitals as av  # noqa: E402


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Api(Isolated):
    def test_answers(self):
        routes = {"/repos/o/fresh": repo_doc("o/fresh"), "/repos/o/archived": "archived.200.json",
                  "/repos/o/nolicence": "nolicence.200.json", "/repos/o/other": "noassertion.200.json",
                  "/repos/o/gone": "gone.404.json"}
        with FakeGitHub(routes) as server:
            net = self.net(server)
            fresh, arch = net.repo_facts("o", "fresh"), net.repo_facts("o", "archived")
            nolic, other, gone = net.repo_facts("o", "nolicence"), net.repo_facts("o", "other"), net.repo_facts("o", "gone")
            net.repo_facts("O", "FRESH")  # cached, whatever the case
        self.assertEqual((fresh["license"], fresh["license_state"], fresh["archived"]), ("MIT", "spdx", False))
        self.assertTrue(arch["archived"])
        self.assertEqual((nolic["license_state"], other["license_state"]), ("none", "non-standard"))
        self.assertTrue(gone["missing"])
        self.assertEqual(len(server.requests), 5)
        headers = server.requests[0][1]
        self.assertEqual((headers["accept"], headers["x-github-api-version"]), ("application/vnd.github+json", "2022-11-28"))
        self.assertNotIn("authorization", headers)

    def test_rename_is_followed_on_the_api_host_only(self):
        token = "ghp_" + "T" * 36
        with FakeGitHub({"/repos/o/old": "renamed.301.json", "/repositories/1296269": "hello-world.200.json"}) as server:
            facts = self.net(server, token=token).repo_facts("o", "old")
        self.assertEqual(server.paths(), ["/repos/o/old", "/repositories/1296269"])
        self.assertEqual([h.get("authorization") for _, h in server.requests], ["Bearer " + token] * 2)
        self.assertEqual(facts["renamed_to"], "octocat/Hello-World")
        away = {"status": 301, "headers": {"Location": "http://127.0.0.2:1/collect"}, "body": {}}
        bare = {"status": 301, "headers": {}, "body": {}}
        with FakeGitHub({"/repos/o/away": away, "/repos/o/bare": bare}) as server:
            net = self.net(server, token=token, census=None)
            self.assertIn("301", net.repo_facts("o", "away")["error"])
            self.assertIn("301", net.repo_facts("o", "bare")["error"])
        self.assertEqual(server.paths(), ["/repos/o/away", "/repos/o/bare"])  # no loop on a 301 without Location

    def test_rate_limit_moves_the_run_to_the_census(self):
        with FakeGitHub({"/repos/octocat/census-old": "ratelimit.403.json"}) as server:
            net = self.net(server)
            first, second = net.repo_facts("octocat", "census-old"), net.repo_facts("octocat", "census-archived")
        self.assertEqual(server.paths(), ["/repos/octocat/census-old"])
        self.assertEqual((net.state, first["source"], first["license_state"]), ("rate-limited", "census 2026-09-23", "none"))
        self.assertTrue(second["archived"])

    def test_short_retry_after_is_waited_once(self):
        busy = {"status": 429, "headers": {"Retry-After": "1"}, "body": {"message": "secondary rate limit"}}
        with FakeGitHub({"/repos/o/r": [busy, repo_doc("o/r")]}) as server:
            t = time.monotonic()
            facts = self.net(server).repo_facts("o", "r")
        self.assertEqual((facts["source"], len(server.requests)), ("GitHub API", 2))
        self.assertGreaterEqual(time.monotonic() - t, 0.9)
        with FakeGitHub({"/repos/o/r": "secondary.429.json"}) as server:  # retry-after 60: not waited for
            net = self.net(server)
            self.assertIn("not in the census", net.repo_facts("o", "r")["error"])
        self.assertEqual((net.state, len(server.requests)), ("rate-limited", 1))

    def test_refusals_unreachable_and_timeouts(self):
        with FakeGitHub() as server:  # the sandbox's 403, no rate-limit headers: this repository only
            net = self.net(server)
            self.assertEqual(net.repo_facts("octocat", "census-fresh")["source"], "census 2026-09-23")
            net.repo_facts("o", "other")
        self.assertEqual((net.state, len(server.requests)), ("ok", 2))
        bad = {"status": 401, "headers": {}, "body": {"message": "Bad credentials"}}
        with FakeGitHub({"/repos/o/r": bad}) as server:
            net = self.net(server, token="x" * 20)
            net.repo_facts("o", "r")
            net.repo_facts("o", "s")
        self.assertEqual((net.state, len(server.requests)), ("token rejected", 1))
        net = av.Net(api=f"http://127.0.0.1:{closed_port()}", proxies={}, census=CENSUS)
        self.assertIn("unreachable", net.repo_facts("o", "r")["error"])
        self.assertEqual(net.state, "unreachable")
        with FakeGitHub(delay=1.5) as server:
            net = self.net(server, timeout=0.3, census=None)
            self.assertIn("timed out", net.repo_facts("o", "r")["error"])

    def test_malformed_answers(self):
        cut = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 500\r\n\r\n{\"full_name\": \"o/cut\""
        routes = {"/repos/o/html": "portal.200.json", "/repos/o/list": {"status": 200, "headers": {}, "body": []},
                  "/repos/o/null": {"status": 200, "headers": {}, "body": "null"},
                  "/repos/o/empty": {"status": 200, "headers": {}, "body": ""},
                  "/repos/o/latin": {"status": 200, "headers": {}, "body": b"\xff\xfe{\"full_name\": 1}"},
                  "/repos/o/cut": {"raw": cut},
                  "/repos/o/garbled": {"raw": b"NOT HTTP AT ALL\r\n\r\n"},
                  "/repos/o/odd": {"status": 200, "headers": {}, "body": {
                      "full_name": "o/odd\u001b[31m", "archived": "yes"}}}
        with FakeGitHub(routes) as server:
            net = self.net(server, census=None)
            for name in ("html", "list", "null", "empty", "latin", "odd"):
                self.assertIn("without a repository", net.repo_facts("o", name)["error"], name)
            for name in ("cut", "garbled"):
                self.assertTrue(net.repo_facts("o", name)["error"], name)

    def test_census_unavailable_or_malformed(self):
        bad = self.tmp / "census.json"
        bad.write_text('{"generated_at": "2026-09-23", "rows": []}', encoding="utf-8")
        for url in (str(bad), str(self.tmp / "missing.json"), bad.as_uri()):
            with FakeGitHub() as server:
                facts = self.net(server, census=url).repo_facts("o", "r")
            self.assertIn("census unavailable", facts["error"], url)

    def test_a_token_with_a_line_break_is_not_used_or_printed(self):
        token = "ghp_" + "L" * 36 + "\nX-Injected: 1"
        with FakeGitHub({"/repos/o/r": repo_doc("o/r")}) as server:
            net = self.net(server, token=token)
            net.repo_facts("o", "r")
        self.assertNotIn("authorization", server.requests[0][1])
        self.assertIn("not used", " ".join(av.notes([], net, True)))
        self.assertNotIn("ghp_", " ".join(av.notes([], net, True)))


class Runtime(Isolated):
    def test_action_yml_then_action_yaml(self):
        routes = {raw("o/js", SHA_A): text_file(action_yml("node20.yml")),
                  raw("o/dock", SHA_A, "action.yaml"): text_file(action_yml("docker.yml")),
                  raw("o/mono", SHA_A, path="sub/dir"): text_file(action_yml("node24.yml")),
                  raw("o/err", SHA_A): {"status": 500, "headers": {}, "body": "oops"},
                  raw("o/html", SHA_A): text_file(action_yml("portal.txt")),
                  raw("o/bin", SHA_A): {"status": 200, "headers": {}, "body": b"\xff\xfe\x00"}}
        with FakeGitHub(routes) as server:
            net = self.net(server)
            net.load_runtimes([("o", "js", SHA_A, ""), ("o", "dock", SHA_A, ""), ("o", "mono", SHA_A, "sub/dir"),
                               ("o", "none", SHA_A, ""), ("o", "err", SHA_A, ""), ("o", "html", SHA_A, ""),
                               ("o", "bin", SHA_A, ""), ("o", "bad", "v1", "")])
        got = net.runtimes
        self.assertEqual(got[("o", "js", SHA_A, "")]["using"], "node20")
        self.assertEqual(got[("o", "dock", SHA_A, "")], {"using": "docker", "file": "action.yaml"})
        self.assertEqual(got[("o", "mono", SHA_A, "sub/dir")]["using"], "node24")
        self.assertTrue(got[("o", "none", SHA_A, "")]["missing"])
        self.assertIn("500", got[("o", "err", SHA_A, "")]["error"])
        self.assertIsNone(got[("o", "html", SHA_A, "")]["using"])
        self.assertIn("not downloaded", got[("o", "bin", SHA_A, "")]["error"])
        self.assertEqual(got[("o", "bad", "v1", "")]["error"], "not looked up")  # only a commit SHA goes in a URL
        self.assertNotIn("authorization", " ".join(str(h) for _, h in server.requests))

    def test_runtime_states_by_date(self):
        import datetime as dt
        self.assertEqual(av.runtime_state("node20", dt.date(2026, 9, 24))[0], "removed")
        self.assertEqual(av.runtime_state("node20", dt.date(2026, 9, 22)),
                         ("deprecated", "GitHub deprecated Node 20 on 2025-09-19; removal set for 2026-09-23"))
        self.assertEqual(av.runtime_state("node20", dt.date(2025, 9, 1))[0], "current")
        self.assertEqual(av.runtime_state("NODE16", dt.date(2026, 9, 24))[0], "removed")
        self.assertEqual(av.runtime_state("node12", dt.date(2026, 9, 24))[1],
                         "Node 12 was removed from GitHub's runners on 2023-08-14")
        for v in ("node24", "docker", "composite"):
            self.assertEqual(av.runtime_state(v, dt.date(2026, 9, 24)), ("current", ""))
        self.assertEqual(av.runtime_state("node99", dt.date(2026, 9, 24))[0], "unknown")
        self.assertEqual(av.runtime_state(None, dt.date(2026, 9, 24))[0], "unknown")


if __name__ == "__main__":
    unittest.main()
