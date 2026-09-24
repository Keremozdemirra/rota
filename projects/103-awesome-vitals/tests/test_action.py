"""action.yml: its structure, and its run block executed by bash with a stand-in python3."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")


def block(text, key):
    """The literal block scalar under `key: |`, dedented, as YAML reads it."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = re.match(rf"^(\s*){re.escape(key)}: \|\s*$", line)
        if m:
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= len(m.group(1)):
                    break
                body.append(nxt)
            while body and not body[-1].strip():
                body.pop()
            indent = min(len(b) - len(b.lstrip()) for b in body if b.strip())
            return "\n".join(b[indent:] for b in body) + "\n"
    raise AssertionError(f"no block scalar {key}")


RUN = block(ACTION, "run")


class Structure(unittest.TestCase):
    def test_inputs_and_composite_step(self):
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml:
            doc = yaml.safe_load(ACTION)
            self.assertEqual(doc["runs"]["using"], "composite")
            self.assertEqual({k: v.get("default") for k, v in doc["inputs"].items()},
                             {"path": "README.md", "mode": "full", "fail-on": "archived,gone",
                              "token": "${{ github.token }}"})
            step = doc["runs"]["steps"][0]
            self.assertEqual(step["shell"], "bash")
            self.assertEqual(step["run"], RUN)  # the block tested below is the one YAML reads
            self.assertEqual(step["env"]["GITHUB_TOKEN"], "${{ inputs.token }}")
        # without PyYAML (it is not in the standard library): the same facts, read as text
        self.assertRegex(ACTION, r"(?m)^runs:\n  using: composite\n  steps:\n")
        for name, default in (("path", "README.md"), ("mode", "full"), ("fail-on", "archived,gone"),
                              ("token", r"\$\{\{ github\.token \}\}")):
            self.assertRegex(ACTION, rf"(?m)^  {name}:\n(    .*\n)*?    default: {default}\n")
        self.assertNotIn("\t", ACTION)

    def test_inputs_are_never_interpolated_into_the_script(self):
        self.assertNotIn("${{", RUN)


@unittest.skipIf(shutil.which("bash") is None, "needs bash")
class RunBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        fake = bin_ / "python3"
        fake.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$FAKE_ARGV"\necho "### report"\nexit "${FAKE_EXIT:-0}"\n')
        fake.chmod(0o755)
        (self.tmp / "run.sh").write_text(RUN)
        self.argv = self.tmp / "argv"
        self.summary = self.tmp / "summary.md"

    def run_block(self, **env):
        base = {"PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}", "FAKE_ARGV": str(self.argv),
                "GITHUB_ACTION_PATH": str(ROOT), "GITHUB_STEP_SUMMARY": str(self.summary),
                "AV_PATH": "README.md", "AV_MODE": "full", "AV_FAIL_ON": "archived,gone", "AV_BASE": ""}
        base.update(env)
        # the way GitHub runs a composite step with shell: bash
        p = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(self.tmp / "run.sh")],
                           env=base, cwd=self.tmp, capture_output=True, text=True)
        argv = self.argv.read_text().split("\n")[:-1] if self.argv.exists() else None
        return p, argv

    def test_full_mode(self):
        p, argv = self.run_block()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(argv, [str(ROOT / "awesome_vitals.py"), "--markdown", "--fail-on", "archived,gone",
                                "--", "README.md"])
        self.assertEqual(self.summary.read_text(), "### report\n")
        self.assertEqual(p.stdout, "### report\n")

    def test_pr_mode_diffs_against_the_checked_out_tree(self):
        _, argv = self.run_block(AV_MODE="pr", AV_BASE="9e02102")
        self.assertEqual(argv[1:5], ["--markdown", "--diff", "9e02102...HEAD", "--fail-on"])

    def test_pr_mode_outside_a_pull_request(self):
        p, argv = self.run_block(AV_MODE="pr")
        self.assertEqual((p.returncode, argv), (2, None))
        self.assertIn("::error::awesome-vitals: mode pr needs a pull_request event", p.stdout)

    def test_unknown_mode_and_empty_path(self):
        self.assertEqual(self.run_block(AV_MODE="weekly")[0].returncode, 2)
        self.assertEqual(self.run_block(AV_PATH=" \n ")[0].returncode, 2)

    def test_several_paths_odd_names_and_no_fail_on(self):
        for fail_on in ("", "none"):
            _, argv = self.run_block(AV_PATH='README.md\n  docs/my list.md  \n\n$(touch pwned) "q".md\n',
                                     AV_FAIL_ON=fail_on)
            self.assertEqual(argv[1:], ["--markdown", "--", "README.md", "docs/my list.md", '$(touch pwned) "q".md'])
        self.assertFalse((self.tmp / "pwned").exists())

    def test_findings_fail_the_step_after_the_summary_is_written(self):
        p, _ = self.run_block(FAKE_EXIT="1")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.summary.read_text(), "### report\n")


if __name__ == "__main__":
    unittest.main()
