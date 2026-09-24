"""doctor.py against fixture configs and canned registry answers. No network."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import doctor  # noqa: E402

TODAY = dt.date(2026, 9, 24)


def entry(command="", args=(), url=""):
    return {"client": "test", "config": "x", "name": "s", "command": command, "args": list(args), "url": url}


class FakeNet(doctor.Net):
    """Answers from a dict keyed by URL instead of the network."""

    def __init__(self, answers):
        super().__init__(False, None)
        self.answers = answers

    def get(self, url, headers=None):
        return self.answers.get(url, {"_error": 404})


class Resolve(unittest.TestCase):
    def test_npx_scoped_unpinned(self):
        r = doctor.resolve(entry("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]))
        self.assertEqual((r["kind"], r["package"], r["version"], r["pinned"]),
                         ("npm", "@modelcontextprotocol/server-filesystem", None, False))

    def test_npx_pinned_and_latest(self):
        self.assertTrue(doctor.resolve(entry("npx", ["-y", "pkg@1.2.3"]))["pinned"])
        self.assertFalse(doctor.resolve(entry("npx", ["pkg@latest"]))["pinned"])

    def test_npx_package_flag(self):
        r = doctor.resolve(entry("npx", ["-y", "-p", "@scope/pkg@2.0.0", "bin-name"]))
        self.assertEqual((r["package"], r["version"]), ("@scope/pkg", "2.0.0"))

    def test_windows_npx_cmd(self):
        self.assertEqual(doctor.resolve(entry("C:\\nodejs\\npx.cmd", ["-y", "pkg"]))["kind"], "npm")

    def test_pnpm_dlx(self):
        self.assertEqual(doctor.resolve(entry("pnpm", ["dlx", "pkg"]))["package"], "pkg")

    def test_uvx(self):
        r = doctor.resolve(entry("uvx", ["mcp-server-fetch==2026.8.18"]))
        self.assertEqual((r["kind"], r["package"], r["version"], r["pinned"]), ("pypi", "mcp-server-fetch", "2026.8.18", True))

    def test_uvx_from_and_extras(self):
        r = doctor.resolve(entry("uvx", ["--from", "pkg[cli]", "pkg-server"]))
        self.assertEqual((r["package"], r["pinned"]), ("pkg", False))

    def test_uv_tool_run_git(self):
        r = doctor.resolve(entry("uv", ["tool", "run", "--from", "git+https://github.com/o/n", "x"]))
        self.assertEqual((r["kind"], r["repo"], r["pinned"]), ("git", "o/n", False))

    def test_pipx_run(self):
        self.assertEqual(doctor.resolve(entry("pipx", ["run", "pkg"]))["package"], "pkg")

    def test_docker_skips_flag_values(self):
        r = doctor.resolve(entry("docker", ["run", "-i", "--rm", "-e", "TOKEN", "-v", "/a:/b",
                                            "ghcr.io/github/github-mcp-server:v1.0.0"]))
        self.assertEqual((r["kind"], r["repo"], r["pinned"]), ("image", "github/github-mcp-server", True))
        self.assertFalse(doctor.resolve(entry("docker", ["run", "mcp/fetch"]))["pinned"])

    def test_docker_registry_port_is_not_a_tag(self):
        self.assertFalse(doctor.resolve(entry("docker", ["run", "localhost:5000/img"]))["pinned"])

    def test_remote(self):
        r = doctor.resolve(entry(url="https://mcp.example.com/mcp"))
        self.assertEqual((r["kind"], r["detail"]), ("remote", "mcp.example.com"))

    def test_local_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            (Path(d) / ".git" / "config").write_text('[core]\n[remote "origin"]\n\turl = git@github.com:o/n.git\n')
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "server.py").write_text("")
            r = doctor.resolve(entry("python3", [str(Path(d) / "src" / "server.py")]))
        self.assertEqual((r["kind"], r["repo"]), ("local", "o/n"))

    def test_unknown(self):
        self.assertEqual(doctor.resolve(entry("some-binary"))["kind"], "unknown")


class Discover(unittest.TestCase):
    def test_reads_names_commands_never_env(self):
        with tempfile.TemporaryDirectory() as d:
            home, cwd = Path(d) / "home", Path(d) / "proj"
            home.mkdir(), cwd.mkdir()
            (home / ".claude.json").write_text(json.dumps({
                "mcpServers": {"a": {"command": "npx", "args": ["pkg"], "env": {"KEY": "secret-value"}}},
                "projects": {"/w/app": {"mcpServers": {"b": {"command": "uvx", "args": ["p"]}}}}}))
            (cwd / ".vscode").mkdir()
            (cwd / ".vscode" / "mcp.json").write_text(json.dumps({"servers": {"c": {"url": "https://x.dev/mcp",
                                                                                    "headers": {"Authorization": "secret-value"}}}}))
            servers, searched = doctor.discover(home, cwd, [])
        self.assertEqual([s["name"] for s in servers], ["a", "b [app]", "c"])
        self.assertEqual(len(searched), 2)
        self.assertNotIn("secret-value", json.dumps(servers))

    def test_codex_toml(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".codex").mkdir()
            (home / ".codex" / "config.toml").write_text('[mcp_servers.docs]\ncommand = "npx"\nargs = ["-y", "pkg"]\n')
            servers, _ = doctor.discover(home, home, [])
        if sys.version_info >= (3, 11):
            self.assertEqual(servers[0]["name"], "docs")

    def test_broken_config_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".mcp.json").write_text("{not json")
            servers, searched = doctor.discover(Path(d) / "nohome", Path(d), [])
        self.assertEqual(servers, [])
        self.assertTrue(searched[0].endswith("(unreadable)"))


class Examine(unittest.TestCase):
    NPM = "https://registry.npmjs.org/@o%2Fserver"
    GH = "https://api.github.com/repos/o/n"

    def npm(self, **v):
        return {"dist-tags": {"latest": "1.0.0"}, "time": {"1.0.0": "2025-01-01T00:00:00Z"},
                "versions": {"1.0.0": {"repository": {"url": "git+https://github.com/o/n.git"}, **v}}}

    def gh(self, pushed="2026-09-20T00:00:00Z", archived=False, license=None):
        return {"full_name": "o/n", "pushed_at": pushed, "archived": archived, "stargazers_count": 5,
                "open_issues_count": 1, "license": license}

    def test_active_licensed_pinned_is_clean(self):
        net = FakeNet({self.NPM: self.npm(), self.GH: self.gh(license={"spdx_id": "MIT"})})
        r = doctor.examine(entry("npx", ["@o/server@1.0.0"]), net, TODAY)
        self.assertEqual((r["repo"], r["status"], r["flags"]), ("o/n", "active", []))

    def test_abandoned_unlicensed_deprecated(self):
        net = FakeNet({self.NPM: self.npm(deprecated="use @o/other"), self.GH: self.gh(pushed="2024-01-01T00:00:00Z")})
        r = doctor.examine(entry("npx", ["-y", "@o/server"]), net, TODAY)
        self.assertEqual(r["status"], "abandoned")
        self.assertEqual(r["flags"], ["abandoned", "deprecated", "no licence file", "unpinned"])

    def test_noassertion_is_non_standard_not_none(self):
        net = FakeNet({self.NPM: self.npm(), self.GH: self.gh(license={"spdx_id": "NOASSERTION"})})
        r = doctor.examine(entry("npx", ["@o/server@1.0.0"]), net, TODAY)
        self.assertIn("non-standard licence", r["flags"])
        self.assertNotIn("no licence file", r["flags"])

    def test_archived(self):
        net = FakeNet({self.NPM: self.npm(), self.GH: self.gh(archived=True, license={"spdx_id": "MIT"})})
        self.assertEqual(doctor.examine(entry("npx", ["@o/server@1"]), net, TODAY)["flags"][0], "archived")

    def test_repo_gone(self):
        net = FakeNet({self.NPM: self.npm()})  # GitHub answers 404
        self.assertIn("repository missing", doctor.examine(entry("npx", ["@o/server@1"]), net, TODAY)["flags"])

    def test_rate_limit_falls_back_to_census(self):
        class Limited(FakeNet):
            def get(self, url, headers=None):
                return {"_error": 403} if "api.github.com" in url else super().get(url, headers)
        net = Limited({self.NPM: self.npm()})
        net.census = {"o/n": {"full_name": "o/n", "pushed_at": "2026-09-01T00:00:00Z", "archived": False,
                              "license": "MIT", "license_state": "spdx"}}
        net.census_date = "2026-09-23"
        r = doctor.examine(entry("npx", ["@o/server@1"]), net, TODAY)
        self.assertEqual((r["status"], r["facts"]["repository"]["source"]), ("active", "census 2026-09-23"))
        self.assertTrue(net.github_down)

    def test_offline_reports_config_facts_only(self):
        r = doctor.examine(entry("npx", ["-y", "@o/server"]), None, TODAY)
        self.assertEqual((r["status"], r["flags"]), ("unknown", ["unpinned"]))

    def test_pypi_repo_from_project_urls(self):
        net = FakeNet({"https://pypi.org/pypi/p/json": {"info": {"version": "1", "project_urls": {"Source": "https://github.com/o/n/tree/main/x"}},
                                                        "urls": []},
                       self.GH: self.gh(license={"spdx_id": "MIT"})})
        self.assertEqual(doctor.examine(entry("uvx", ["p==1"]), net, TODAY)["repo"], "o/n")


class Output(unittest.TestCase):
    def test_strict_exit_code_and_markdown(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text(json.dumps({"mcpServers": {"x|y": {"command": "npx", "args": ["-y", "pkg"]}}}))
            self.assertEqual(doctor.main(["--offline", "--strict", "--config", str(cfg)]), 0)
            md = doctor.render_markdown([doctor.examine(entry("npx", ["pkg"]) | {"name": "x|y"}, None, TODAY)], TODAY)
        self.assertIn("x\\|y", md)
        self.assertIn("1 server", md)


if __name__ == "__main__":
    unittest.main()
