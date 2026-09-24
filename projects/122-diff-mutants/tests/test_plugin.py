"""The plugin files, the packaging, the README, and all of them against each other and the code."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT  # noqa: E402

import diff_mutants as dm  # noqa: E402

SKILL = ROOT / "skills" / "diff-mutants" / "SKILL.md"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def text_files():
    for p in ROOT.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts and p.suffix != ".pyc":
            yield p


class Plugin(unittest.TestCase):
    def test_manifest_and_marketplace_agree(self):
        plugin = json.loads(read(".claude-plugin/plugin.json"))
        market = json.loads(read(".claude-plugin/marketplace.json"))
        self.assertEqual(plugin["name"], "diff-mutants")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"] and market["owner"]["name"])
        self.assertEqual(plugin["license"], "MIT")

    def test_versions_agree(self):
        plugin = json.loads(read(".claude-plugin/plugin.json"))
        self.assertEqual(plugin["version"], dm.VERSION)
        self.assertIn(f'version = "{dm.VERSION}"', read("pyproject.toml"))

    def test_skill_only_no_hooks(self):
        self.assertFalse((ROOT / "hooks").exists())
        self.assertNotIn("hooks", json.loads(read(".claude-plugin/plugin.json")))

    def test_skill_front_matter(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: diff-mutants\ndescription: "))
        front = text.split("---\n")[1]
        self.assertIn("do my new tests actually test anything?", front)
        # the tool runs the project's test suite and --test-cmd takes any command: nothing is pre-approved
        self.assertNotIn("allowed-tools", front)

    def test_skill_commands_point_at_the_module(self):
        rels = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", SKILL.read_text(encoding="utf-8"))
        self.assertTrue(rels)
        for rel in rels:
            self.assertEqual(rel, "diff_mutants.py")
            self.assertTrue((ROOT / rel).is_file())

    def test_skill_options_exist(self):
        text = SKILL.read_text(encoding="utf-8")
        help_text = self._help()
        for option in set(re.findall(r"(--[a-z][a-z-]+)", text)):
            self.assertIn(option, help_text, option)

    def test_skill_names_fields_the_json_has(self):
        text = SKILL.read_text(encoding="utf-8")
        report = dm._empty_report()
        mutant = dm.mutant_record(dm.Candidate("a.py", 1, "constant", "`1` → `2`", [(0, 1, "2")], 0))
        for field in ("error", "tests_that_cannot_fail", "status", "before", "after", "output_tail", "detail",
                      "notes", "baseline"):
            self.assertIn(f"`{field}", text)
            self.assertTrue(field in report or field in mutant or field in ("output_tail", "detail"), field)

    def _help(self) -> str:
        import io
        from unittest import mock
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, self.assertRaises(SystemExit):
            dm.main(["--help"])
        return out.getvalue()


class Packaging(unittest.TestCase):
    def test_pyproject(self):
        text = read("pyproject.toml")
        for needed in ('name = "diff-mutants"', 'requires = ["setuptools>=77"]', 'license = "MIT"',
                       'requires-python = ">=3.9"', "dependencies = []", 'diff-mutants = "diff_mutants:main"',
                       'py-modules = ["diff_mutants"]'):
            self.assertIn(needed, text)

    def test_no_generic_module_names(self):
        for name in ("cli.py", "hook.py", "server.py", "utils.py", "doctor.py", "main.py"):
            self.assertFalse((ROOT / name).exists(), name)

    def test_sdist_carries_what_the_tests_read(self):
        manifest = read("MANIFEST.in")
        for needed in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "skills/diff-mutants/SKILL.md",
                       ".github/workflows/test.yml", ".github/workflows/release.yml",
                       "recursive-include tests *.py *.diff *.txt"):
            self.assertIn(needed, manifest)

    def test_workflow_pins(self):
        for wf in ("test.yml", "release.yml"):
            text = read(f".github/workflows/{wf}")
            self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", text)
            self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", text)
            self.assertIn("runs-on: ubuntu-24.04", text)
            self.assertNotIn("ubuntu-latest", text)
        test = read(".github/workflows/test.yml")
        self.assertIn('python: ["3.9", "3.12"]', test)
        self.assertIn("python -m unittest discover -s tests -t .", test)

    def test_licence(self):
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", read("LICENSE"))


class Readme(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_sections_and_last_one(self):
        headings = re.findall(r"^## (.+)$", self.text, re.M)
        for needed in ("Why", "Example", "Install", "Usage", "What it reads, runs and sends", "What this is not"):
            self.assertIn(needed, headings)
        self.assertEqual(headings[-1], "What this is not")

    def test_install_lines(self):
        v = dm.VERSION
        for needed in ("/plugin marketplace add Keremozdemirra/diff-mutants",
                       "/plugin install diff-mutants@diff-mutants", f"uvx diff-mutants@{v}",
                       f"pipx run --spec diff-mutants=={v} diff-mutants",
                       "https://raw.githubusercontent.com/Keremozdemirra/diff-mutants/main/diff_mutants.py",
                       f"https://raw.githubusercontent.com/Keremozdemirra/diff-mutants/v{v}/diff_mutants.py"):
            self.assertIn(needed, self.text)

    def test_evidence_and_dates(self):
        self.assertIn("https://news.ycombinator.com/item?id=47253538", self.text)
        self.assertIn("2026-03-04", self.text)
        self.assertIn("Real output, 2026-09-24", self.text)

    def test_every_option_is_documented(self):
        for option in ("--base", "--staged", "--test-cmd", "--timeout", "--max-mutants", "--exclude", "--repo",
                       "--json", "--markdown", "--strict", "--dry-run"):
            self.assertIn(f"`{option}", self.text, option)

    def test_documented_defaults_match_the_code(self):
        self.assertIn(f"| Mutants per run (`--max-mutants`) | {dm.DEFAULT_MAX_MUTANTS} |", self.text)
        self.assertIn(f"{dm.TIMEOUT_FLOOR:.0f} s + {dm.TIMEOUT_FACTOR:.0f} × the duration of the unmutated run",
                      self.text)
        self.assertIn(f"{dm.BASELINE_TIMEOUT:,.0f} s", self.text)
        self.assertIn(f"| Grace between SIGTERM and SIGKILL | {dm.KILL_GRACE:.0f} s |", self.text)

    def test_every_operator_is_documented(self):
        for op in dm.OPERATORS:
            self.assertRegex(self.text, rf"\n\| {op} \|", op)


class Hygiene(unittest.TestCase):
    TOKENS = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}"
                        r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}")
    HIDDEN = re.compile("[\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")

    def test_no_token_shaped_literal_anywhere(self):
        for p in text_files():
            text = p.read_bytes().decode("utf-8", "replace")
            self.assertIsNone(self.TOKENS.search(text), p)

    def test_no_invisible_or_bidi_characters(self):
        for p in text_files():
            text = p.read_bytes().decode("utf-8", "replace")
            self.assertIsNone(self.HIDDEN.search(text), p)


if __name__ == "__main__":
    unittest.main()
