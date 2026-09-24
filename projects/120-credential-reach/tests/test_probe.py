"""--probe: one GET per GitHub token to api.github.com/user, header parsing, failures, and silence without it."""
import http.client
import io
import json
import os
import socket
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated, Response, cr, synthetic  # noqa: E402

rand = synthetic.rand


class Probe(Isolated):
    def setUp(self):
        super().setUp()
        self.tok = "ghp_" + rand(36)
        os.environ["GITHUB_TOKEN"] = self.tok

    def run_probe(self, *answers, argv=("--json",)):
        web = self.serve(*answers)
        code, out, err = self.run_main(["--probe", "--no-transcripts", *argv])
        self.assertNotIn(self.tok, out + err)
        return code, (json.loads(out) if "--json" in argv else out), err, web

    def test_no_request_without_probe(self):
        self.write(".config/gh/hosts.yml", f"github.com:\n    oauth_token: gho_{rand(36)}\n    user: me\n")
        code, out, err = self.run_main(["--json"])  # the isolated urlopen fails the test on any request
        self.assertEqual(code, 0)
        self.assertNotIn("probe", json.loads(out))

    def test_classic_token_scopes(self):
        answer = Response(json.dumps({"login": "octo-dev", "id": 1}).encode(), headers={
            "X-OAuth-Scopes": "repo, delete_repo, admin:org, bogus scope!, workflow",
            "GitHub-Authentication-Token-Expiration": "2026-12-31 10:00:00 UTC"})
        code, rep, err, web = self.run_probe(answer)
        self.assertEqual(len(web.requests), 1)
        url, headers, timeout = web.requests[0]
        self.assertEqual(url, "https://api.github.com/user")
        self.assertEqual(headers["authorization"], "Bearer " + self.tok)
        self.assertLessEqual(timeout, 10)
        r = rep["probe"]["results"][0]
        self.assertEqual(r["scopes"], ["repo", "delete_repo", "admin:org", "workflow"])
        self.assertEqual((r["login"], r["expires"], r["token_type"]), ("octo-dev", "2026-12-31 10:00:00 UTC",
                                                                      "personal access token (classic)"))
        line = next(b for b in rep["blast_radius"] if b["source"] == "probe")
        self.assertEqual(line["severity"], "high")
        self.assertIn("delete_repo: delete repositories the account administers", line["text"])
        self.assertIn("account-wide", line["text"])
        self.assertIn("sending 1 GitHub token", err)

    def test_fine_grained_token_has_no_scopes_header(self):
        os.environ["GITHUB_TOKEN"] = self.tok = "github_pat_" + rand(22) + "_" + rand(59)
        code, rep, _, _ = self.run_probe(Response(b'{"login":"me"}'))
        r = rep["probe"]["results"][0]
        self.assertIsNone(r["scopes"])
        self.assertIn("not exposed", r["scopes_note"])

    def test_empty_scopes_header(self):
        _, rep, _, _ = self.run_probe(Response(b"{}", headers={"X-OAuth-Scopes": ""}))
        self.assertEqual(rep["probe"]["results"][0]["scopes"], [])

    def test_a_proxy_is_mentioned_but_not_printed(self):
        proxy_pw = rand(16)
        os.environ["HTTPS_PROXY"] = f"http://me:{proxy_pw}@proxy.example:3128"
        code, out, err, _ = self.run_probe(401, argv=())
        self.assertIn("Sent through the HTTPS proxy", out)
        self.assertNotIn(proxy_pw, out + err)
        self.assertNotIn("proxy.example", out + err.replace("HTTPS_PROXY", ""))

    def test_rejected_token(self):
        _, rep, _, _ = self.run_probe(401)
        r = rep["probe"]["results"][0]
        self.assertEqual((r["checked"], r["valid"]), (True, False))
        self.assertIn("rejected (401)", r["result"])
        self.assertFalse(rep["incomplete"])

    def test_recorded_github_401(self):
        fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "github-user-401.json").read_text(encoding="utf-8"))
        hdrs = http.client.HTTPMessage()
        for k, v in fx["headers"].items():
            hdrs[k] = v
        err = urllib.error.HTTPError("https://api.github.com/user", fx["status"], "Unauthorized", hdrs,
                                     io.BytesIO(json.dumps(fx["body"]).encode()))
        _, rep, _, _ = self.run_probe(err)
        r = rep["probe"]["results"][0]
        self.assertEqual((r["status"], r["valid"], r["checked"]), (401, False, True))

    def test_failures_mark_the_run_incomplete(self):
        for failure in (403, 500, urllib.error.URLError("down"), socket.timeout("slow"),
                        http.client.IncompleteRead(b"x"), ConnectionResetError()):
            _, rep, _, _ = self.run_probe(failure)
            r = rep["probe"]["results"][0]
            self.assertFalse(r["checked"], failure)
            self.assertTrue(rep["incomplete"], failure)

    def test_odd_bodies_still_report_scopes(self):
        for body in (b"", b"null", b"[1]", b"\xff\xfe", b'{"login": "bad login\\u001b[31m"}'):
            _, rep, _, _ = self.run_probe(Response(body, headers={"X-OAuth-Scopes": "repo"}))
            r = rep["probe"]["results"][0]
            self.assertEqual(r["scopes"], ["repo"], body)
            self.assertNotIn("login", r, body)

    def test_same_token_in_two_places_is_sent_once(self):
        self.write(".git-credentials", f"https://me:{self.tok}@github.com\nhttps://me:{self.tok}@gitlab.com\n")
        _, rep, _, web = self.run_probe(Response(b"{}", headers={"X-OAuth-Scopes": "repo"}))
        self.assertEqual(len(web.requests), 1)
        self.assertEqual(rep["probe"]["results"][0]["sources"], ["$GITHUB_TOKEN", "~" + os.sep + ".git-credentials"])

    def test_only_github_com_tokens_of_a_valid_shape_are_sent(self):
        del os.environ["GITHUB_TOKEN"]
        ghe, oauth = "gho_" + rand(36), "gho_" + rand(36)
        self.write(".config/gh/hosts.yml", f"ghe.corp.example:\n    oauth_token: {ghe}\n    user: a\n"
                                           f"github.com:\n    oauth_token: {oauth}\n    user: b\n")
        self.write(".netrc", "machine github.com login x password not-a-token\n")
        self.write(".git-credentials", "https://me:ghp_short@github.com\n")
        os.environ["GH_ENTERPRISE_TOKEN"] = "ghp_" + rand(36)
        os.environ["GH_TOKEN"] = "ghp_" + rand(36) + "\r\nX-Injected: yes"
        _, rep, _, web = self.run_probe(Response(b"{}", headers={"X-OAuth-Scopes": "gist"}))
        self.assertEqual([h["authorization"] for _, h, _ in web.requests], ["Bearer " + oauth])
        self.assertEqual(rep["probe"]["results"][0]["sources"], ["~" + os.sep + os.path.join(".config", "gh", "hosts.yml")])

    def test_nothing_to_probe_sends_nothing(self):
        del os.environ["GITHUB_TOKEN"]
        code, out, err, web = self.run_probe(argv=())
        self.assertEqual(web.requests, [])
        self.assertIn("nothing sent", err)
        self.assertIn("no GitHub token for github.com was found", out)

    def test_text_and_markdown_carry_every_probe_result(self):
        _, out, _, _ = self.run_probe(Response(b"{}", headers={"X-OAuth-Scopes": "repo"}), argv=())
        self.assertIn("GitHub probe: personal access token (classic) in $GITHUB_TOKEN is valid, scopes repo", out)
        self.assertIn("$GITHUB_TOKEN: personal access token (classic): valid; scopes repo", out)
        _, out, _, _ = self.run_probe(401, argv=())
        self.assertIn("$GITHUB_TOKEN: personal access token (classic): rejected (401)", out)
        _, out, _, _ = self.run_probe(401, argv=("--markdown",))
        self.assertIn("### GitHub probe", out)
        self.assertIn("rejected (401)", out)


class HeaderHelper(unittest.TestCase):
    def test_header_lookup(self):
        self.assertIsNone(cr._header(None, "X"))
        self.assertEqual(cr._header({"x-oauth-scopes": "repo"}, "X-OAuth-Scopes"), "repo")
        self.assertIsNone(cr._header(42, "X"))


if __name__ == "__main__":
    unittest.main()
