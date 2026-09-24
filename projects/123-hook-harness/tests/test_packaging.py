"""Packaging, workflows and the README, checked against each other."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, hh  # noqa: E402

CHECKOUT = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0"


class Packaging(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_pyproject(self):
        text = self.read("pyproject.toml")
        for line in ('requires = ["setuptools>=77"]', 'license = "MIT"', 'requires-python = ">=3.9"', "dependencies = []",
                     'hook-harness = "hook_harness:main"', 'py-modules = ["hook_harness"]', f'version = "{hh.VERSION}"'):
            self.assertIn(line, text)

    def test_no_generic_top_level_modules(self):
        self.assertEqual({p.stem for p in ROOT.glob("*.py")}, {"hook_harness"})

    def test_workflows_pin_their_actions(self):
        for name in ("test.yml", "release.yml"):
            text = self.read(f".github/workflows/{name}")
            self.assertIn(CHECKOUT, text)
            self.assertIn(SETUP_PYTHON, text)
            self.assertIn("runs-on: ubuntu-24.04", text)
            for uses in re.findall(r"uses:\s*(\S+)", text):
                self.assertRegex(uses, r"@[0-9a-f]{40}$")
        self.assertIn('python: ["3.9", "3.12"]', self.read(".github/workflows/test.yml"))

    def test_readme_snippet_uses_the_pinned_actions(self):
        readme = self.read("README.md")
        self.assertIn(CHECKOUT, readme)
        self.assertIn(SETUP_PYTHON, readme)
        self.assertIn(f"hook-harness=={hh.VERSION}", readme)
        self.assertEqual(re.findall(r"^## .*", readme, re.M)[-1], "## What this is not")

    def test_manifest_carries_what_the_tests_need(self):
        text = self.read("MANIFEST.in")
        for needed in ("tests", "fixtures", "examples", "tools", ".github"):
            self.assertIn(needed, text)

    def test_licence(self):
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", self.read("LICENSE"))

    def test_examples_are_valid_case_files(self):
        for path in (ROOT / "examples").glob("*.cases.json"):
            self.assertTrue(hh.load_suite(path).cases, path)


if __name__ == "__main__":
    unittest.main()
