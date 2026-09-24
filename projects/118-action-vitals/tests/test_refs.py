"""Reference classification, git ls-remote parsing and running, and what may reach the network."""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import (CHECKOUT_V6, LS, PYPA_V1_14_2, SHA_A, FakeGitHub, Isolated, workflow)  # noqa: E402

import action_vitals as av  # noqa: E402


class Classify(unittest.TestCase):
    def kind_pin(self, v):
        r = av.parse_ref(v)
        return r["kind"], r["pin"]

    def test_forms_github_documents(self):
        self.assertEqual(self.kind_pin(f"actions/checkout@{CHECKOUT_V6}"), ("remote", "sha"))
        self.assertEqual(self.kind_pin(f"actions/checkout@{CHECKOUT_V6.upper()}"), ("remote", "sha"))
        self.assertEqual(self.kind_pin("actions/checkout@v6"), ("remote", "ref"))
        self.assertEqual(self.kind_pin("actions/aws/ec2@main"), ("remote", "ref"))
        self.assertEqual(av.parse_ref("actions/aws/ec2@main")["path"], "ec2")
        self.assertEqual(self.kind_pin("actions/checkout"), ("remote", "missing"))
        self.assertEqual(self.kind_pin("o/r/.github/workflows/w.yml@v1")[0], "remote")
        self.assertEqual(self.kind_pin("./.github/actions/x"), ("local", "local"))
        self.assertEqual(self.kind_pin("$/.github/actions/x"), ("self", "local"))
        self.assertEqual(self.kind_pin("$/.github/actions/x@v1"), ("self", "invalid"))
        self.assertEqual(self.kind_pin("docker://alpine:3.8"), ("docker", "image tag"))
        self.assertEqual(self.kind_pin("docker://ghcr.io/o/img"), ("docker", "no image tag"))
        self.assertEqual(self.kind_pin("docker://alpine:latest"), ("docker", "no image tag"))
        self.assertEqual(self.kind_pin("docker://alpine@sha256:" + "0" * 64), ("docker", "digest"))
        self.assertEqual(self.kind_pin("docker://alpine@sha256:abc"), ("docker", "invalid"))
        self.assertEqual(self.kind_pin("${{ matrix.action }}")[0], "expression")

    def test_strict_names(self):
        for v in ("-o/r@v1", "o/../x@v1", "o/..@v1", "https://github.com/o/r@v1", "o r/x@v1", "ö/r@v1", "o@v1",
                  "o//r@v1", "o/r/../x@v1", "o/r/p q@v1", "", " ", "git@github.com:o/r", "o/" + "r" * 101 + "@v1"):
            self.assertIn(av.parse_ref(v)["kind"], ("unrecognised",), v)
        self.assertEqual(av.parse_ref("o/r@v1..2")["pin"], "invalid")
        self.assertEqual(av.parse_ref("o/r@-x")["pin"], "invalid")

    def test_versions(self):
        tags = {"v6": CHECKOUT_V6, "v6.1.0": CHECKOUT_V6, "v6.1": CHECKOUT_V6, "v5.0.0": SHA_A, "v7.0.0-beta": SHA_A,
                "latest": CHECKOUT_V6}
        self.assertEqual(av.best_tag(tags, CHECKOUT_V6, "v6"), "v6.1.0")
        self.assertEqual(av.best_tag(tags, CHECKOUT_V6), "v6.1.0")
        self.assertIsNone(av.best_tag(tags, "c" * 40))
        self.assertEqual(av.highest_tag(tags), "v6.1.0")  # the pre-release is not a release
        self.assertEqual(av.highest_tag({"1.2.3": SHA_A, "v1.10.0": SHA_A}), "v1.10.0")


class LsRemoteOutput(unittest.TestCase):
    def test_recorded_output_with_annotated_tags(self):
        refs = av.parse_ls_remote(LS["https://github.com/actions/checkout"])
        self.assertEqual(refs["tags"]["v6.1.0"], CHECKOUT_V6)
        # v6.0.3 is an annotated tag: its tag object is 9f69817..., the commit it points to df4cb1c...
        self.assertEqual(refs["tags"]["v6.0.3"], "df4cb1c069e1874edd31b4311f1884172cec0e10")
        self.assertIn("main", refs["heads"])
        self.assertNotIn("v6.0.3^{}", refs["tags"])
        pypa = av.parse_ls_remote(LS["https://github.com/pypa/gh-action-pypi-publish"])
        self.assertEqual(pypa["tags"]["v1.14.2"], PYPA_V1_14_2)
        self.assertEqual(pypa["heads"]["release/v1"], PYPA_V1_14_2)

    def test_malformed_lines_are_ignored(self):
        text = ("\r\n" + SHA_A + "\trefs/tags/v1\r\n" + "zz" * 20 + "\trefs/tags/bad\n" + SHA_A + " refs/tags/space\n"
                + SHA_A + "\trefs/pull/1/head\n" + SHA_A + "\trefs/tags/ctl\x1b[31m\n" + SHA_A + "\trefs/tags/ok-ü\n")
        refs = av.parse_ls_remote(text)
        self.assertEqual(sorted(refs["tags"]), ["ok-ü", "v1"])
        self.assertEqual(av.parse_ls_remote(""), {"tags": {}, "heads": {}})


class RunningGit(Isolated):
    def test_command_and_environment(self):
        self.answer_git({"https://github.com/actions/checkout": LS["https://github.com/actions/checkout"]})
        got = av.ls_remote("actions", "checkout", 3)
        self.assertEqual(got["refs"]["tags"]["v6"], CHECKOUT_V6)
        cmd, kw = self.git.calls[0]
        self.assertEqual(cmd, ["git", "-c", "credential.helper=", "-c", "core.askPass=", "ls-remote", "--heads",
                               "--tags", "https://github.com/actions/checkout"])
        self.assertEqual((kw["env"]["GIT_TERMINAL_PROMPT"], kw["env"]["GIT_ASKPASS"], kw["timeout"]), ("0", "", 3))
        self.assertIs(kw["stdin"], subprocess.DEVNULL)

    def test_failures(self):
        self.answer_git({"https://github.com/o/timeout": subprocess.TimeoutExpired("git", 3),
                         "https://github.com/o/nogit": FileNotFoundError(),
                         "https://github.com/o/down": 2,
                         "https://github.com/o/secret": (128, ("fatal: unable to access 'https://x-access-token:"
                                                              + "ghp_" + "Q" * 36 + "@github.com/o/secret/'").encode())})
        self.assertEqual(av.ls_remote("o", "private", 3), {"error": "not visible: private, deleted, or no such repository",
                                                            "missing": True})
        self.assertIn("timed out", av.ls_remote("o", "timeout", 3)["error"])
        self.assertEqual(av.ls_remote("o", "nogit", 3)["error"], "git is not installed")
        self.assertEqual(av.ls_remote("o", "down", 3), {"error": "git ls-remote failed (network or proxy)", "missing": False})
        got = av.ls_remote("o", "secret", 3)
        self.assertNotIn("ghp_", str(got))  # git's message is never passed on
        self.assertEqual(av.ls_remote("o/x", "r", 3)["error"], "not a repository name, not looked up")

    def test_only_validated_names_reach_git_or_github(self):
        hostile = ["o/r@v1; rm -rf /", "--upload-pack=touch/x@v1", "o/r@$(id)", "https://evil.example/o/r@v1",
                   "../../etc/passwd@v1", "o/r/..@v1", "o/r?x=1@v1", "o/r#x@v1", "\u202eo/r@v1", "o/r\n@v1",
                   "docker://user:pw@registry.example/i:1", "./local", "$/self", "${{ inputs.x }}", "ok-owner/ok.repo@v1"]
        text = "jobs:\n  a:\n    steps:\n" + "".join(f"      - uses: {av.json.dumps(h)}\n" for h in hostile)
        root = self.repo({".github/workflows/ci.yml": text})
        with FakeGitHub() as server:
            code, out, _ = self.run_main(["--json", root], net=self.net(server))
        # `o/r@v1; rm -rf /` names a valid o/r; its ref is compared locally and never sent
        self.assertEqual(sorted(self.git.urls), ["https://github.com/o/r", "https://github.com/ok-owner/ok.repo"])
        self.assertEqual(sorted(server.paths()), ["/repos/o/r", "/repos/ok-owner/ok.repo"])
        self.assertNotIn("pw@", out)


class OriginHost(Isolated):
    def test_repository_on_another_host_sends_nothing(self):
        root = self.repo({".github/workflows/ci.yml": workflow("o/r@v1", f"o/s@{SHA_A}")},
                         origin="https://ghe.example.com/team/app.git")
        with FakeGitHub() as server:
            code, out, _ = self.run_main(["--strict", root], net=self.net(server))
        self.assertEqual((self.git.calls, server.requests), ([], []))
        self.assertIn("origin is ghe.example.com", out)
        self.assertEqual(code, 1)  # o/r@v1 is still a tag, whatever the host

    def test_own_repository_is_not_third_party(self):
        root = self.repo({".github/workflows/ci.yml": workflow("me/app/.github/workflows/w.yml@main")},
                         origin="git@github.com:me/app.git")
        self.answer_git({"https://github.com/me/app": "%s\trefs/heads/main\n" % SHA_A})
        code, out, _ = self.run_main(["--strict", "--no-runtime", "--json", root], net=self.net())
        row = av.json.loads(out)["uses"][0]
        self.assertEqual((row["third_party"], row["pin"], "unpinned" in row["flags"]), (False, "branch", False))


if __name__ == "__main__":
    unittest.main()
