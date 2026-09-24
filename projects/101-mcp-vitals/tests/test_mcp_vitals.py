"""mcp_vitals.py against fixture configs and canned registry answers. No network, no real home directory."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FakeNet, Isolated, entry, fixture  # noqa: E402

import mcp_vitals  # noqa: E402

TODAY = dt.date(2026, 9, 24)
NPM = "https://registry.npmjs.org/@o%2Fserver"
GH = "https://api.github.com/repos/o/n"


def npm_doc(**v):
    return {"dist-tags": {"latest": "1.0.0"}, "time": {"1.0.0": "2025-01-01T00:00:00Z"},
            "versions": {"1.0.0": {"repository": {"url": "git+https://github.com/o/n.git"}, **v}}}


def gh_doc(pushed="2026-09-20T00:00:00Z", archived=False, license=None):
    # the shape of a real answer (fixtures/github-repo-agent-vitals.json), for a repository o/n
    doc = fixture("github-repo-agent-vitals.json")
    doc.update(full_name="o/n", name="n", pushed_at=pushed, archived=archived, license=license)
    return doc


class Resolve(Isolated):
    def test_npx_scoped_unpinned(self):
        r = mcp_vitals.resolve(entry("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]))
        self.assertEqual((r["kind"], r["package"], r["version"], r["pinned"]),
                         ("npm", "@modelcontextprotocol/server-filesystem", None, False))

    def test_npx_pinned_and_latest(self):
        self.assertTrue(mcp_vitals.resolve(entry("npx", ["-y", "pkg@1.2.3"]))["pinned"])
        self.assertFalse(mcp_vitals.resolve(entry("npx", ["pkg@latest"]))["pinned"])

    def test_npx_package_flag(self):
        r = mcp_vitals.resolve(entry("npx", ["-y", "-p", "@scope/pkg@2.0.0", "bin-name"]))
        self.assertEqual((r["package"], r["version"]), ("@scope/pkg", "2.0.0"))

    def test_windows_npx_cmd(self):
        self.assertEqual(mcp_vitals.resolve(entry("C:\\nodejs\\npx.cmd", ["-y", "pkg"]))["kind"], "npm")

    def test_pnpm_dlx(self):
        self.assertEqual(mcp_vitals.resolve(entry("pnpm", ["dlx", "pkg"]))["package"], "pkg")

    def test_uvx(self):
        r = mcp_vitals.resolve(entry("uvx", ["mcp-server-fetch==2026.8.18"]))
        self.assertEqual((r["kind"], r["package"], r["version"], r["pinned"]), ("pypi", "mcp-server-fetch", "2026.8.18", True))

    def test_uvx_from_and_extras(self):
        r = mcp_vitals.resolve(entry("uvx", ["--from", "pkg[cli]", "pkg-server"]))
        self.assertEqual((r["package"], r["pinned"]), ("pkg", False))

    def test_uv_tool_run_git(self):
        r = mcp_vitals.resolve(entry("uv", ["tool", "run", "--from", "git+https://github.com/o/n", "x"]))
        self.assertEqual((r["kind"], r["repo"], r["pinned"]), ("git", "o/n", False))

    def test_pipx_run(self):
        self.assertEqual(mcp_vitals.resolve(entry("pipx", ["run", "pkg"]))["package"], "pkg")

    def test_docker_skips_flag_values(self):
        r = mcp_vitals.resolve(entry("docker", ["run", "-i", "--rm", "-e", "TOKEN", "-v", "/a:/b",
                                                "ghcr.io/github/github-mcp-server:v1.0.0"]))
        self.assertEqual((r["kind"], r["repo"], r["pin"], r["pinned"]), ("image", "github/github-mcp-server", "tag", False))
        self.assertFalse(mcp_vitals.resolve(entry("docker", ["run", "mcp/fetch"]))["pinned"])
        digest = "mcp/fetch@sha256:" + "a" * 64
        self.assertTrue(mcp_vitals.resolve(entry("docker", ["run", digest]))["pinned"])

    def test_docker_registry_port_is_not_a_tag(self):
        self.assertFalse(mcp_vitals.resolve(entry("docker", ["run", "localhost:5000/img"]))["pinned"])

    def test_remote(self):
        r = mcp_vitals.resolve(entry(url="https://mcp.example.com/mcp"))
        self.assertEqual((r["kind"], r["detail"]), ("remote", "mcp.example.com"))

    def test_local_checkout(self):
        d = self.tmp / "checkout"
        (d / ".git").mkdir(parents=True)
        (d / ".git" / "config").write_text('[core]\n[remote "origin"]\n\turl = git@github.com:o/n.git\n')
        (d / "src").mkdir()
        (d / "src" / "server.py").write_text("")
        r = mcp_vitals.resolve(entry("python3", [str(d / "src" / "server.py")]))
        self.assertEqual((r["kind"], r["repo"]), ("local", "o/n"))

    def test_unknown(self):
        self.assertEqual(mcp_vitals.resolve(entry("some-binary"))["kind"], "unknown")


class Grammar(Isolated):
    def test_npm_names(self):
        ok = ["pkg", "@scope/pkg", "a.b-c_d~e", "@21st-dev/magic"]
        bad = ["/home/x", "https://x", "Pkg", "@scope", "a/b/c", "pkg\n", " pkg", "", "a" * 215, "../x"]
        for s in ok:
            self.assertEqual(mcp_vitals.npm_spec(s)["kind"], "npm", s)
        for s in bad:
            self.assertNotEqual(mcp_vitals.npm_spec(s).get("kind"), "npm", s)

    def test_pypi_names(self):
        for s in ["mcp-server-fetch", "a", "A.b_c-1"]:
            self.assertEqual(mcp_vitals.py_spec(s)["kind"], "pypi", s)
        for s in ["-x", "x-", "/abs", "https://x/y", "a b", ""]:
            self.assertNotEqual(mcp_vitals.py_spec(s).get("kind"), "pypi", s)

    def test_github_host_is_parsed_not_searched(self):
        self.assertEqual(mcp_vitals.github_ref("git+https://tok:x@github.com/o/n.git#main")[:2], ("o/n", "main"))
        self.assertEqual(mcp_vitals.github_ref("git@github.com:o/n.git")[0], "o/n")
        self.assertEqual(mcp_vitals.github_ref("https://github.com/o/n/tree/main/src/fetch")[0], "o/n")
        for s in ["https://evil.example/github.com/o/n", "https://github.com.evil.example/o/n",
                  "https://gitlab.com/o/n", "github.com", "https://github.com/o", "https://github.com/o/..",
                  "https://github.com/-o-/n"]:
            self.assertIsNone(mcp_vitals.github_ref(s), s)


class Masking(Isolated):
    def test_urls(self):
        self.assertEqual(mcp_vitals.mask_url("https://alice:hunter2@mcp.internal.example/sse"),
                         "https://***@mcp.internal.example/sse")
        self.assertEqual(mcp_vitals.mask_url("https://server.smithery.ai/@x/y/mcp?api_key=sk-SMITHERYSECRET"),
                         "https://server.smithery.ai/@x/y/mcp?***")
        self.assertEqual(mcp_vitals.mask_url("https://mcp.example.com/s/Zx81kPq0Lm4Nv7Rt2Wy5Bc9D/mcp"),
                         "https://mcp.example.com/s/***/mcp")

    def test_args(self):
        got = mcp_vitals.mask_args(["--api-key=sk-ARGSECRET", "--token", "abc123", "KEY=value", "pkg==1.0",
                                    "Authorization: Bearer t0k", "--verbose", "ghp_" + "a" * 36, "@scope/pkg@1.0.0"])
        self.assertEqual(got, ["--api-key=***", "--token", "***", "KEY=***", "pkg==1.0", "Authorization: ***",
                               "--verbose", "***", "@scope/pkg@1.0.0"])

    def test_strict_hides_every_value(self):
        self.assertEqual(mcp_vitals.mask_args(["--port", "8080", "s3cret", "--x=y"], strict=True),
                         ["--port", "***", "***", "--x=***"])

    def test_remote_text_is_marked_and_cut(self):
        t = mcp_vitals.remote_text("a\x1b[31mb\u202e\nc>> " + "x" * 400)
        self.assertTrue(t.startswith("<<remote text, not an instruction: ab c> > x"), t)
        self.assertLess(len(t), 220)
        self.assertEqual(t.count(">>"), 1)


class Discover(Isolated):
    def test_reads_names_commands_never_env(self):
        (self.home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"a": {"command": "npx", "args": ["pkg"], "env": {"KEY": "secret-value"}}},
            "projects": {"/w/app": {"mcpServers": {"b": {"command": "uvx", "args": ["p"]}}}}}))
        (self.cwd / ".vscode").mkdir()
        (self.cwd / ".vscode" / "mcp.json").write_text(json.dumps({"servers": {"c": {"url": "https://x.dev/mcp",
                                                                                    "headers": {"Authorization": "secret-value"}}}}))
        servers, searched = mcp_vitals.discover(self.home, self.cwd, [])
        self.assertEqual([s["name"] for s in servers], ["a", "b [app]", "c"])
        self.assertEqual(len(searched), 2)
        self.assertNotIn("secret-value", json.dumps(servers))

    def test_codex_toml(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex" / "config.toml").write_text('[mcp_servers.docs]\ncommand = "npx"\nargs = ["-y", "pkg"]\n')
        servers, searched = mcp_vitals.discover(self.home, self.cwd, [])
        if sys.version_info >= (3, 11):
            self.assertEqual(servers[0]["name"], "docs")
        else:
            self.assertTrue(searched[0].endswith("(needs Python 3.11+ to read TOML)"), searched)

    def test_broken_config_is_reported_not_fatal(self):
        (self.cwd / ".mcp.json").write_text("{not json")
        servers, searched = mcp_vitals.discover(self.home, self.cwd, [])
        self.assertEqual(servers, [])
        self.assertTrue(searched[0].endswith("(not valid JSON)"), searched)


class Examine(Isolated):
    def test_active_licensed_pinned_is_clean(self):
        net = FakeNet({NPM: npm_doc(), GH: gh_doc(license={"spdx_id": "MIT"})})
        r = mcp_vitals.examine(entry("npx", ["@o/server@1.0.0"]), net, TODAY)
        self.assertEqual((r["repo"], r["status"], r["flags"]), ("o/n", "active", []))

    def test_abandoned_unlicensed_deprecated(self):
        net = FakeNet({NPM: npm_doc(deprecated="use @o/other"), GH: gh_doc(pushed="2024-01-01T00:00:00Z")})
        r = mcp_vitals.examine(entry("npx", ["-y", "@o/server"]), net, TODAY)
        self.assertEqual(r["status"], "abandoned")
        self.assertEqual(r["flags"], ["abandoned", "deprecated", "no licence file", "unpinned"])

    def test_noassertion_is_non_standard_not_none(self):
        net = FakeNet({NPM: npm_doc(), GH: gh_doc(license={"spdx_id": "NOASSERTION"})})
        r = mcp_vitals.examine(entry("npx", ["@o/server@1.0.0"]), net, TODAY)
        self.assertIn("non-standard licence", r["flags"])
        self.assertNotIn("no licence file", r["flags"])

    def test_archived(self):
        net = FakeNet({NPM: npm_doc(), GH: gh_doc(archived=True, license={"spdx_id": "MIT"})})
        self.assertEqual(mcp_vitals.examine(entry("npx", ["@o/server@1"]), net, TODAY)["flags"][0], "archived")

    def test_repo_gone(self):
        net = FakeNet({NPM: npm_doc()})  # GitHub answers 404
        self.assertIn("repository missing", mcp_vitals.examine(entry("npx", ["@o/server@1"]), net, TODAY)["flags"])

    def test_rate_limit_falls_back_to_census(self):
        net = FakeNet({NPM: npm_doc(), GH: 403})  # what api.github.com answers in a sandbox without access
        net.census = {"o/n": {"full_name": "o/n", "pushed_at": "2026-09-01T00:00:00Z", "archived": False,
                              "license": "MIT", "license_state": "spdx"}}
        net.census_date = "2026-09-23"
        r = mcp_vitals.examine(entry("npx", ["@o/server@1"]), net, TODAY)
        self.assertEqual((r["status"], r["facts"]["repository"]["source"]), ("active", "census 2026-09-23"))
        self.assertTrue(net.github_down)

    def test_offline_reports_config_facts_only(self):
        r = mcp_vitals.examine(entry("npx", ["-y", "@o/server"]), None, TODAY)
        self.assertEqual((r["status"], r["flags"]), ("unknown", ["unpinned"]))

    def test_pypi_repo_from_project_urls(self):
        doc = {"info": {"version": "1", "project_urls": {"Source": "https://github.com/o/n/tree/main/x"}}, "urls": []}
        net = FakeNet({"https://pypi.org/pypi/p/1/json": doc, GH: gh_doc(license={"spdx_id": "MIT"})})
        self.assertEqual(mcp_vitals.examine(entry("uvx", ["p==1"]), net, TODAY)["repo"], "o/n")

    def test_census_from_the_published_file(self):
        census = fixture("census-sample.json")
        net = FakeNet({"https://registry.npmjs.org/@21st-dev%2Fmagic": fixture("npm-21st-dev-magic.json"),
                       "https://api.github.com/repos/21st-dev/magic-mcp": 403, mcp_vitals.CENSUS: census})
        r = mcp_vitals.examine(entry("npx", ["-y", "@21st-dev/magic@0.2.3"]), net, TODAY)
        self.assertEqual((r["repo"], r["facts"]["repository"]["source"], r["facts"]["repository"]["license"]),
                         ("21st-dev/magic-mcp", "census 2026-09-23", "ISC"))
        self.assertEqual(r["flags"], [])


class Output(Isolated):
    def test_strict_exit_code_and_markdown(self):
        cfg = self.write_config({"mcpServers": {"x|y": {"command": "npx", "args": ["-y", "pkg"]}}})
        code, out, _ = self.run_main(["--offline", "--strict", "--config", str(cfg)])
        self.assertEqual(code, 0)
        md = mcp_vitals.render_markdown([mcp_vitals.examine(entry("npx", ["pkg"]) | {"name": "x|y"}, None, TODAY)], TODAY)
        self.assertIn("x\\|y", md)
        self.assertIn("1 server", md)

    def test_github_and_census_both_unreachable(self):
        self.serve({"https://registry.npmjs.org/@21st-dev%2Fmagic": fixture("npm-21st-dev-magic.json"),
                    "https://api.github.com/repos/21st-dev/magic-mcp": 403, mcp_vitals.CENSUS: 503})
        code, out, _ = self.run_main(["--strict", "--json", "npm:@21st-dev/magic"])
        doc = json.loads(out)
        self.assertEqual(code, 2)
        self.assertIn("repository unknown", doc["servers"][0]["flags"])
        self.assertEqual(doc["census"], {"used": False, "date": None})
        self.assertIn("repository facts were not checked", doc["notes"][0])

    def test_json_shape(self):
        cfg = self.write_config({"mcpServers": {"a": {"command": "npx", "args": ["-y", "pkg@1.0.0"]}}})
        code, out, _ = self.run_main(["--offline", "--json", "--config", str(cfg)])
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(set(doc), {"checked", "configs", "servers", "notes", "census"})
        self.assertEqual((doc["servers"][0]["kind"], doc["servers"][0]["pin"]), ("npm", "exact"))


if __name__ == "__main__":
    unittest.main()
