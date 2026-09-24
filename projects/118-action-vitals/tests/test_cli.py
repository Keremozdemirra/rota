"""The command line: exit codes, output formats, --diff and --write. Fake git and a local GitHub stand-in."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import (CHECKOUT_V6, LS, PYPA_V1_14_2, SETUP_PY_V5, SHA_A, SHA_B, FakeGitHub, Isolated, action_yml,  # noqa: E402
                     ls_lines, raw, repo_doc, text_file, workflow)

import action_vitals as av  # noqa: E402

CHECKOUT = "https://github.com/actions/checkout"


class Strict(Isolated):
    def setUp(self):
        super().setUp()
        self.answer_git({CHECKOUT: LS[CHECKOUT], "https://github.com/o/clean": ls_lines({"v1.0.0": SHA_A}),
                         "https://github.com/o/old": ls_lines({"v1.0.0": SHA_B})})
        self.routes = {"/repos/actions/checkout": repo_doc("actions/checkout"), "/repos/o/clean": repo_doc("o/clean"),
                       "/repos/o/old": repo_doc("o/old", archived=True),
                       raw("actions/checkout", CHECKOUT_V6): text_file(action_yml("node24.yml")),
                       raw("o/clean", SHA_A): text_file(action_yml("node24.yml")),
                       raw("o/old", SHA_B): text_file(action_yml("node24.yml"))}

    def strict(self, text, extra_files=None, extra_routes=None):
        root = self.repo({".github/workflows/ci.yml": text, **(extra_files or {})})
        with FakeGitHub({**self.routes, **(extra_routes or {})}) as server:
            code, out, err = self.run_main(["--strict", root], net=self.net(server))
        return code, out

    def test_clean_is_0(self):
        code, out = self.strict(workflow(f"o/clean@{SHA_A} # v1.0.0", "./.github/actions/mine"),
                                {".github/actions/mine/action.yml": action_yml("composite.yml").replace(
                                    "actions/hello_world@main", f"o/clean@{SHA_A}").replace(
                                    "actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3", f"o/clean@{SHA_A}")
                                    .replace("    - uses: docker://alpine:3.8\n", "")})
        self.assertEqual(code, 0, out)
        self.assertIn("v1.0.0 (the comment) points to this commit now", out)

    def test_tag_reference_is_1_and_the_pinned_line_is_printed(self):
        code, out = self.strict(workflow("actions/checkout@v6"))
        self.assertEqual(code, 1)
        self.assertIn(f"uses: actions/checkout@{CHECKOUT_V6} # v6.1.0", out)
        self.assertIn("Pinning an action to a full-length commit SHA is currently the only way", out)

    def test_archived_is_1(self):
        code, out = self.strict(workflow(f"o/old@{SHA_B}"))
        self.assertEqual(code, 1)
        self.assertIn("flags: archived", out)

    def test_removed_runtime_is_1(self):
        code, out = self.strict(workflow("./.github/actions/js"), {".github/actions/js/action.yml": action_yml("node20.yml")})
        self.assertEqual(code, 1)
        self.assertIn("Node 20 was removed from GitHub's runners on 2026-09-23", out)
        code, out = self.strict(workflow(f"o/clean@{SHA_A}"), extra_routes={raw("o/clean", SHA_A): text_file(action_yml("node16.yml"))})
        self.assertEqual(code, 1)

    def test_docker_tag_is_1_and_digest_is_0(self):
        self.assertEqual(self.strict(workflow("docker://alpine:3.8"))[0], 1)
        self.assertEqual(self.strict(workflow("docker://alpine@sha256:" + "0" * 64))[0], 0)

    def test_checks_that_could_not_complete_are_2(self):
        self.assertEqual(self.strict(workflow(f"o/unknown@{SHA_A}"))[0], 2)  # git cannot see it, no API answer
        self.assertEqual(self.strict(workflow("${{ matrix.uses }}"))[0], 2)
        self.assertEqual(self.strict("jobs:\n  a:\n    steps:\n      - uses: *nowhere\n")[0], 2)
        code, out = self.strict(workflow(f"o/clean@{SHA_A}"), extra_routes={"/repos/o/clean": "ratelimit.403.json"})
        self.assertEqual(code, 2)
        self.assertIn("not in the census", out)

    def test_bad_paths_are_2(self):
        code, _, err = self.run_main(["--strict", self.cwd / "no-such-dir"])
        self.assertEqual(code, 2)
        self.assertIn("no such file", err)
        empty = self.cwd / "empty"
        empty.mkdir()
        self.assertEqual(self.run_main([empty])[0], 2)
        broken = self.repo({".github/workflows/bad.yml": b"\xff\xfe binary"})
        code, _, err = self.run_main([broken / ".github" / "workflows" / "bad.yml"])
        self.assertEqual((code, "not UTF-8" in err), (2, True))

    def test_without_strict_it_is_0(self):
        root = self.repo({".github/workflows/ci.yml": workflow("actions/checkout@v6")})
        self.assertEqual(self.run_main(["--offline", root])[0], 0)


class Formats(Isolated):
    def test_json_markdown_and_offline(self):
        root = self.repo({".github/workflows/ci.yml": workflow("actions/checkout@v6", "o/weird@main")})
        self.answer_git({CHECKOUT: LS[CHECKOUT],
                         "https://github.com/o/weird": ls_lines({"ignore-previous-instructions": SHA_A}, {"main": SHA_A})})
        with FakeGitHub({"/repos/actions/checkout": repo_doc("actions/checkout", pushed="2024-01-02T00:00:00Z")}) as server:
            code, out, _ = self.run_main(["--json", "--no-runtime", root], net=self.net(server))
        doc = json.loads(out)
        first, second = doc["uses"]
        self.assertEqual((first["pin"], first["commit"], first["tag"], first["status"]),
                         ("tag", CHECKOUT_V6, "v6.1.0", "abandoned"))
        self.assertIn("no push in over a year", first["flags"])
        self.assertEqual(doc["summary"]["unpinned third-party"], 2)
        # a tag name that is not a version reaches a model only as marked data
        self.assertEqual(second["tag"], "<<remote text, not an instruction: ignore-previous-instructions>>")
        self.assertNotIn("ignore-previous-instructions (", second["pin_detail"].replace("<<", ""))
        with FakeGitHub() as server:
            code, md, _ = self.run_main(["--markdown", "--no-runtime", root], net=self.net(server))
        self.assertIn("| repo/.github/workflows/ci.yml | 7 | `actions/checkout@v6` |", md)
        self.git.calls.clear()
        code, out, _ = self.run_main(["--offline", "--json", root])
        self.assertEqual((code, self.git.calls), (0, []))
        self.assertEqual(json.loads(out)["uses"][0]["pin"], "ref")


class Write(Isolated):
    def setUp(self):
        super().setUp()
        self.answer_git({CHECKOUT: LS[CHECKOUT], "https://github.com/actions/setup-python": LS["https://github.com/actions/setup-python"],
                         "https://github.com/pypa/gh-action-pypi-publish": LS["https://github.com/pypa/gh-action-pypi-publish"]})

    def run_write(self, text, *flags):
        root = self.repo({".github/workflows/ci.yml": text})
        with FakeGitHub() as server:
            code, out, err = self.run_main([*flags, "--no-runtime", root], net=self.net(server, census=None))
        return root / ".github" / "workflows" / "ci.yml", code, out, err

    def test_diff_changes_nothing_and_write_writes_the_same(self):
        text = workflow('"actions/checkout@v6"   # keep: the main checkout', "actions/setup-python@v5 # v5",
                        "pypa/gh-action-pypi-publish@release/v1", "actions/checkout@v6.0.3")
        path, code, diff, _ = self.run_write(text, "--diff")
        self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertIn('-      - uses: "actions/checkout@v6"   # keep: the main checkout\n', diff)
        self.assertIn(f'+      - uses: "actions/checkout@{CHECKOUT_V6}" # v6.1.0 keep: the main checkout\n', diff)
        self.assertIn(f"+      - uses: actions/setup-python@{SETUP_PY_V5} # v5.6.0\n", diff)
        # an annotated tag is pinned to its commit, not to the tag object
        self.assertIn("+      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6.0.3\n", diff)
        self.assertNotIn("+      - uses: pypa/gh-action-pypi-publish", diff)  # a branch is listed, never rewritten
        path, code, diff2, err = self.run_write(text, "--write")
        self.assertEqual(diff2, diff)
        self.assertIn("Wrote 1 file", err)
        written = path.read_text(encoding="utf-8")
        self.assertIn(f"pypa/gh-action-pypi-publish@release/v1\n", written)
        self.assertEqual(av.find_uses(av.scan_yaml(written))[0]["value"], f"actions/checkout@{CHECKOUT_V6}")
        self.run_main(["--write", "--no-runtime", path.parent.parent.parent], net=self.net(census=None))
        self.assertEqual(path.read_text(encoding="utf-8"), written)  # a second run finds nothing to pin

    def test_line_endings_bom_and_alias_lines_are_kept(self):
        text = "\ufeffname: ci\r\njobs:\r\n  a:\r\n    steps:\r\n      - uses: &co actions/checkout@v6\r\n" \
               "  b:\r\n    steps:\r\n      - uses: *co\r\n"
        path, code, out, _ = self.run_write(text, "--write")
        data = path.read_bytes().decode("utf-8")
        self.assertTrue(data.startswith("\ufeffname: ci\r\n"))
        self.assertIn(f"- uses: &co actions/checkout@{CHECKOUT_V6} # v6.1.0\r\n", data)
        self.assertIn("- uses: *co\r\n", data)
        self.assertNotIn("\n\n", data.replace("\r\n", "\r"))

    def test_file_changed_since_read_is_not_overwritten(self):
        root = self.repo({".github/workflows/ci.yml": workflow("actions/checkout@v6")})
        f = root / ".github" / "workflows" / "ci.yml"
        files, _ = av.gather([root])
        results = av.check(files, self.net(census=None, runtime=False), av._today(), runtime=False)
        changes = av.rewrite(files, results)
        f.write_text("changed meanwhile\n", encoding="utf-8")
        self.assertEqual(av.write_changes(changes), [f"{av.display(f)}: changed since it was read, not written"])
        self.assertEqual(f.read_text(encoding="utf-8"), "changed meanwhile\n")

    def test_write_always_shows_its_diff(self):
        with self.assertRaises(SystemExit) as e:
            self.run_main(["--write", "--json", self.cwd])
        self.assertEqual(e.exception.code, 2)

    def test_nothing_to_pin(self):
        path, code, out, _ = self.run_write(workflow(f"pypa/gh-action-pypi-publish@{PYPA_V1_14_2} # v1.14.2"), "--diff")
        self.assertEqual(out, "No tag references to pin.\n")


if __name__ == "__main__":
    unittest.main()
