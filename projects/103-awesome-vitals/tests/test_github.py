"""Repository facts: GitHub answers, GitHub failures, and the census behind them."""
import datetime as dt
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import awesome_vitals as av  # noqa: E402
from fakegithub import CENSUS, TOKEN, FakeGitHub, fixture  # noqa: E402

TODAY = dt.date(2026, 9, 24)


def entries(*names):
    return [{"repository": n, "locations": [{"file": "list.md", "line": i}]} for i, n in enumerate(names, 1)]


def check(server, *names, **kw):
    kw.setdefault("sleep", lambda seconds: None)  # the one retry waits, the tests need not
    gh = av.GitHub(api=server.url, proxies={}, census_url=kw.pop("census_url", CENSUS), **kw)
    return gh, {r["repository"]: r for r in av.examine(entries(*names), gh, TODAY)}


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Answers(unittest.TestCase):
    def test_recorded_repository(self):
        with FakeGitHub() as server:
            gh, r = check(server, "Keremozdemirra/agent-vitals")
        r = r["Keremozdemirra/agent-vitals"]
        self.assertEqual((r["source"], r["status"], r["license"], r["license_state"], r["findings"]),
                         ("github", "active", "MIT", "spdx", []))
        self.assertEqual(r["pushed_at"], "2026-09-24")
        headers = server.requests[0][1]
        self.assertEqual((headers["accept"], headers["x-github-api-version"]), ("application/vnd.github+json", "2022-11-28"))
        self.assertTrue(headers["user-agent"].startswith("awesome-vitals/"))
        self.assertNotIn("authorization", headers)  # no token set, none sent

    def test_archived_no_licence_file_and_noassertion_are_three_different_things(self):
        with FakeGitHub() as server:
            _, r = check(server, "octocat/archived-example", "octocat/unlicensed-example", "octocat/other-licence-example")
        self.assertEqual(r["octocat/archived-example"]["findings"], ["archived"])
        self.assertEqual(r["octocat/unlicensed-example"]["findings"], ["no-licence"])
        # NOASSERTION: a licence file GitHub cannot identify, which is not the same as none
        self.assertEqual(r["octocat/other-licence-example"]["findings"], ["stale", "non-standard-licence"])

    def test_renamed_follows_the_301_with_the_token_and_reports_the_new_name(self):
        with FakeGitHub() as server:
            _, r = check(server, "octocat/renamed-example", token=TOKEN)
        r = r["octocat/renamed-example"]
        self.assertEqual(server.paths(), ["/repos/octocat/renamed-example", "/repositories/1296269"])
        self.assertEqual([h.get("authorization") for _, h in server.requests], ["Bearer " + TOKEN] * 2)
        self.assertEqual((r["renamed_to"], r["findings"]), ("octocat/Hello-World", ["renamed", "abandoned"]))

    def test_a_redirect_off_the_api_host_is_not_followed(self):
        away = {"status": 301, "headers": {"Location": "http://127.0.0.2:1/collect"}, "body": {"message": "Moved"}}
        with FakeGitHub({"/repos/o/moved": away}) as server:
            _, r = check(server, "o/moved", token=TOKEN)
        self.assertEqual(server.paths(), ["/repos/o/moved"])
        self.assertEqual((r["o/moved"]["status"], r["o/moved"]["github"]), ("unchecked", "GitHub API answered 301"))

    def test_case_only_difference_is_not_a_rename(self):
        with FakeGitHub() as server:
            _, r = check(server, "OCTOCAT/hello-world")
        self.assertIsNone(r["OCTOCAT/hello-world"]["renamed_to"])

    def test_404_is_gone(self):
        with FakeGitHub() as server:
            _, r = check(server, "octocat/gone-example")
        r = r["octocat/gone-example"]
        self.assertEqual((r["status"], r["findings"], r["http_status"], r["source"]), ("gone", ["gone"], 404, "github"))


class Fallback(unittest.TestCase):
    def test_primary_rate_limit_moves_the_rest_of_the_run_to_the_census(self):
        with FakeGitHub({"/repos/lharries/whatsapp-mcp": "ratelimit.403.json",
                         "/repos/octocat/hello-world": "hello-world.200.json"}) as server:
            gh, r = check(server, "lharries/whatsapp-mcp", "octocat/Hello-World", "TransformerOptimus/SuperAGI")
        self.assertEqual(server.paths(), ["/repos/lharries/whatsapp-mcp"])  # nothing more was asked
        self.assertEqual(gh.state, "rate-limited")
        self.assertEqual((r["lharries/whatsapp-mcp"]["source"], r["lharries/whatsapp-mcp"]["source_date"]),
                         ("census", "2026-09-23"))
        self.assertEqual(r["TransformerOptimus/SuperAGI"]["status"], "abandoned")
        self.assertEqual(r["octocat/Hello-World"]["note"], "not in the census")
        self.assertIn("Set GITHUB_TOKEN", " ".join(av.source_notes(list(r.values()), gh)))

    def test_secondary_rate_limit_429(self):
        with FakeGitHub({"/repos/n8n-io/n8n": "secondary.429.json"}) as server:
            gh, r = check(server, "n8n-io/n8n", "anthropics/skills")
        self.assertEqual((gh.state, len(server.requests)), ("rate-limited", 2))  # retry-after 60, one retry
        self.assertEqual(r["n8n-io/n8n"]["findings"], ["non-standard-licence"])
        self.assertEqual(r["anthropics/skills"]["findings"], ["no-licence"])

    def test_a_refusal_that_is_not_a_rate_limit_falls_back_for_that_repository_only(self):
        # the recorded sandbox 403 carries no rate-limit headers
        with FakeGitHub() as server:
            gh, r = check(server, "punkpeye/awesome-mcp-clients", "Keremozdemirra/agent-vitals")
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(gh.state, "ok")
        self.assertEqual((r["punkpeye/awesome-mcp-clients"]["source"], r["punkpeye/awesome-mcp-clients"]["status"],
                          r["punkpeye/awesome-mcp-clients"]["github"]), ("census", "stale", "GitHub API answered 403"))
        self.assertEqual(r["Keremozdemirra/agent-vitals"]["source"], "github")

    def test_rejected_token(self):
        bad = {"status": 401, "headers": {}, "body": {"message": "Bad credentials"}}
        with FakeGitHub({"/repos/n8n-io/n8n": bad}) as server:
            gh, r = check(server, "n8n-io/n8n", "anthropics/skills", token=TOKEN)
        self.assertEqual((gh.state, len(server.requests)), ("token rejected", 1))
        self.assertEqual(r["anthropics/skills"]["source"], "census")

    def test_network_down(self):
        gh = av.GitHub(api=f"http://127.0.0.1:{closed_port()}", proxies={}, census_url=CENSUS, sleep=lambda s: None)
        r = {x["repository"]: x for x in av.examine(entries("BrowserMCP/mcp", "anthropics/skills"), gh, TODAY)}
        self.assertEqual((gh.state, gh.requests), ("unreachable", 2))  # the first request and its one retry
        self.assertTrue(gh.stop_reason.startswith("GitHub API unreachable"))
        self.assertEqual(r["BrowserMCP/mcp"]["status"], "abandoned")

    def test_timeout(self):
        with FakeGitHub(delay=2.0) as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS, timeout=0.3, sleep=lambda s: None)
            r = av.examine(entries("appcypher/awesome-mcp-servers", "BrowserMCP/mcp"), gh, TODAY)
        self.assertEqual((gh.state, gh.requests), ("unreachable", 2))  # the first request and its one retry
        self.assertIn("timed out", gh.stop_reason)
        self.assertEqual(r[0]["findings"], ["archived", "no-licence"])

    def test_malformed_payloads(self):
        routes = {"/repos/o/portal": "portal.200.json",
                  "/repos/o/list": {"status": 200, "headers": {}, "body": []},
                  "/repos/o/cut": {"status": 200, "headers": {}, "body": '{"full_name": "o/cut", "pushed'}}
        with FakeGitHub(routes) as server:
            gh, r = check(server, "o/portal", "o/list", "o/cut")
        for name in ("o/portal", "o/list", "o/cut"):
            self.assertEqual((r[name]["status"], r[name]["github"]),
                             ("unchecked", "GitHub API answered 200 without a repository in it"))
        self.assertEqual((gh.state, len(server.requests)), ("ok", 3))

    def test_census_unavailable_or_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "census.json"
            bad.write_text('{"generated_at": "2026-09-23", "rows": []}', encoding="utf-8")
            for url in (bad.as_uri(), str(Path(d) / "missing.json"), (Path(d) / "missing.json").as_uri()):
                with FakeGitHub() as server:
                    gh, r = check(server, "n8n-io/n8n", census_url=url)
                self.assertTrue(r["n8n-io/n8n"]["note"].startswith("census unavailable"), url)
                self.assertEqual(r["n8n-io/n8n"]["findings"], ["unchecked"])

    def test_source_census_sends_nothing_to_github(self):
        with FakeGitHub() as server:
            gh, r = check(server, "n8n-io/n8n", "octocat/Hello-World", source="census")
        self.assertEqual((server.requests, gh.state), ([], "not asked"))
        self.assertEqual(r["n8n-io/n8n"]["source"], "census")
        self.assertEqual(r["octocat/Hello-World"]["findings"], ["unchecked"])

    def test_source_github_never_reads_the_census(self):
        with FakeGitHub() as server:
            gh, r = check(server, "n8n-io/n8n", source="github", census_url="file:///nonexistent/census.json")
        self.assertEqual((r["n8n-io/n8n"]["status"], r["n8n-io/n8n"]["github"]), ("unchecked", "GitHub API answered 403"))
        self.assertEqual(gh.census_error, "")  # never tried


class Untrusted(unittest.TestCase):
    def test_only_strict_owner_repo_names_reach_the_network(self):
        bad = ["o/r?x=1", "o/r#x", "../../etc/passwd", "o/..", "o/.", "o/r/extra", "-o/r", "o/r%2F..", "o r/x",
               "o/" + "r" * 101, "", "o", "o/r\n", "ö/r"]
        with FakeGitHub() as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS)
            for name in bad:
                self.assertEqual(gh.facts(name)["note"], "not a repository name, not looked up", name)
        self.assertEqual(server.requests, [])

    def test_values_from_github_are_held_to_their_form(self):
        odd = {"status": 200, "headers": {}, "body": {
            "full_name": "o/odd", "archived": "yes", "pushed_at": "yesterday", "stargazers_count": "many",
            "license": {"spdx_id": "MIT\n| <b>injected</b>"}}}
        spoofed = {"status": 200, "headers": {}, "body": {"full_name": "o/r\u001b[31m | x", "pushed_at": "2026-09-01"}}
        with FakeGitHub({"/repos/o/odd": odd, "/repos/o/spoofed": spoofed}) as server:
            _, r = check(server, "o/odd", "o/spoofed")
        self.assertEqual((r["o/odd"]["archived"], r["o/odd"]["pushed_at"], r["o/odd"]["stars"], r["o/odd"]["status"]),
                         (False, None, None, "unknown"))
        self.assertEqual((r["o/odd"]["license"], r["o/odd"]["license_state"]), (None, "non-standard"))
        self.assertEqual(r["o/spoofed"]["github"], "GitHub API answered 200 without a repository in it")

    def test_values_from_the_census_are_held_to_their_form(self):
        rows = [{"full_name": "o/a", "license": "MIT | x", "license_state": "spdx", "archived": "no",
                 "pushed_at": 20250101, "stars": "12"},
                {"full_name": "o/b\n[x](y)", "license": "MIT", "license_state": "spdx"},
                {"full_name": "o/c", "license": None, "license_state": "free-for-all", "pushed_at": "2026-09-20"}]
        with tempfile.TemporaryDirectory() as d:
            census = Path(d) / "census.json"
            census.write_text(json.dumps({"generated_at": "not a date", "repositories": rows}), encoding="utf-8")
            with FakeGitHub() as server:
                gh, r = check(server, "o/a", "o/b", "o/c", source="census", census_url=str(census))
        self.assertEqual({k: r["o/a"][k] for k in ("license", "license_state", "archived", "pushed_at", "stars")},
                         {"license": None, "license_state": None, "archived": False, "pushed_at": None, "stars": None})
        self.assertEqual(r["o/b"]["note"], "not in the census")  # a row whose name is not a name is dropped
        self.assertEqual((r["o/c"]["license_state"], r["o/c"]["findings"]), (None, []))
        self.assertEqual(gh.census_date, "")

    def test_broken_responses_do_not_stop_the_run(self):
        routes = {
            "/repos/o/empty": {"status": 200, "headers": {}, "body": ""},
            "/repos/o/null": {"status": 200, "headers": {}, "body": "null"},
            "/repos/o/latin": {"raw": "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n\xff\xfe\xfd\xfc"},
            "/repos/o/cut": {"raw": "HTTP/1.1 200 OK\r\nContent-Length: 400\r\n\r\n{\"full_name\": \"o/cut\""},
            "/repos/o/garbled": {"raw": "SMTP ready\r\n\r\n"},
        }
        with FakeGitHub(routes) as server:
            gh, r = check(server, "o/empty", "o/null", "o/latin", "o/cut", "o/garbled", "anthropics/skills")
        for name in ("o/empty", "o/null", "o/latin"):
            self.assertEqual(r[name]["github"], "GitHub API answered 200 without a repository in it", name)
        # a response cut short or not HTTP at all says the connection is broken, not the repository
        self.assertEqual(r["o/cut"]["status"], "unchecked")
        self.assertTrue(gh.stop_reason.startswith("GitHub API unreachable"), gh.stop_reason)
        self.assertEqual(r["anthropics/skills"]["source"], "census")
        self.assertEqual(server.paths()[-1], "/repos/o/cut")  # nothing asked after that


class Review(unittest.TestCase):
    """Regressions from the review of 2026-09-24; the number is the finding's."""

    def test_4_exception_text_that_may_carry_the_token_is_never_echoed(self):
        gh = av.GitHub(api="http://127.0.0.1:9", proxies={}, census_url=CENSUS, sleep=lambda s: None)

        def refuse(*args, **kwargs):
            raise ValueError("Invalid header value b'Bearer ghp_SECRETpart1\\nghp_SECRETpart2'")

        gh.opener.open = refuse
        f = gh.facts("n8n-io/n8n")
        self.assertNotIn("SECRET", gh.stop_reason + f["github"] + f["note"])
        self.assertEqual(f["source"], "census")

    def test_7_one_retry_after_a_short_wait(self):
        waits = []
        limited = {"status": 429, "headers": {"Retry-After": "1"},
                   "body": {"message": "You have exceeded a secondary rate limit."}}
        routes = {"/repos/Keremozdemirra/agent-vitals": [limited, "agent-vitals.200.json"],
                  "/repos/octocat/Hello-World": [{"status": 502, "headers": {}, "body": "<html>bad gateway</html>"},
                                                 "hello-world.200.json"],
                  "/repos/octocat/archived-example": [dict(fixture("archived.200.json"), delay=1.5), "archived.200.json"]}
        with FakeGitHub(routes) as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS, timeout=0.5, sleep=waits.append)
            r = av.examine(entries("Keremozdemirra/agent-vitals", "octocat/Hello-World", "octocat/archived-example"),
                           gh, TODAY)
        self.assertEqual([x["source"] for x in r], ["github", "github", "github"])
        self.assertEqual((gh.state, len(server.requests)), ("ok", 6))
        self.assertEqual(waits[0], 1)  # as long as retry-after asked

    def test_7_gives_up_after_one_retry_and_never_waits_long(self):
        waits = []
        again = {"status": 429, "headers": {"Retry-After": "2"}, "body": {"message": "secondary rate limit"}}
        with FakeGitHub({"/repos/n8n-io/n8n": [again, again, "agent-vitals.200.json"]}) as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS, sleep=waits.append)
            r = av.examine(entries("n8n-io/n8n", "anthropics/skills"), gh, TODAY)
        self.assertEqual((gh.state, len(server.requests), waits), ("rate-limited", 2, [2]))
        self.assertEqual([x["source"] for x in r], ["census", "census"])
        waits.clear()
        hour = {"status": 429, "headers": {"Retry-After": "3600"}, "body": {}}
        with FakeGitHub({"/repos/n8n-io/n8n": hour}) as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS, sleep=waits.append)
            av.examine(entries("n8n-io/n8n"), gh, TODAY)
        self.assertEqual((gh.state, len(server.requests), waits), ("rate-limited", 1, []))

    def test_10_a_301_without_location_is_asked_once(self):
        moved = {"status": 301, "headers": {}, "body": {"message": "Moved Permanently"}}
        with FakeGitHub({"/repos/o/noloc": moved}) as server:
            gh = av.GitHub(api=server.url, proxies={}, census_url=CENSUS, sleep=lambda s: None)
            r = av.examine(entries("o/noloc"), gh, TODAY)
        self.assertEqual(server.paths(), ["/repos/o/noloc"])
        self.assertEqual(r[0]["github"], "GitHub API answered 301 without a Location")


class Buckets(unittest.TestCase):
    def test_boundaries_match_the_census(self):
        cases = [(0, "active"), (30, "active"), (31, "slowing"), (90, "slowing"), (91, "stale"),
                 (365, "stale"), (366, "abandoned"), (None, "unknown")]
        for days, status in cases:
            self.assertEqual(av.bucket(days, False), status, days)
        self.assertEqual(av.bucket(5, True), "archived")

    def test_days_since(self):
        self.assertEqual(av.days_since("2026-09-23T23:59:59Z", TODAY), 1)
        self.assertEqual(av.days_since("2025-09-24", TODAY), 365)
        self.assertIsNone(av.days_since("yesterday", TODAY))
        self.assertIsNone(av.days_since(None, TODAY))

    def test_fixture_provenance_is_stated(self):
        for p in (HERE / "fixtures" / "github").glob("*.json"):
            self.assertRegex(fixture(p.name)["_provenance"], r"^(Recorded|Constructed)")


if __name__ == "__main__":
    unittest.main()
