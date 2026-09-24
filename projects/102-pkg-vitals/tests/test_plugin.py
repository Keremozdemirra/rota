"""The plugin files and the packaging, checked against each other and against the parser."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Case, pkg_vitals as pv  # noqa: E402

CHECKOUT = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def handlers():
    return [h for group in load("hooks/hooks.json")["hooks"]["PreToolUse"] for h in group["hooks"]]


class Plugin(Case):
    def test_manifest_and_marketplace_agree(self):
        plugin = load(".claude-plugin/plugin.json")
        market = load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"] and market["owner"]["name"])

    def test_versions_agree(self):
        plugin = load(".claude-plugin/plugin.json")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{plugin["version"]}"', pyproject)
        self.assertEqual(pv.VERSION, plugin["version"])

    def test_one_handler_for_both_shells(self):
        # Claude Code runs every matching handler as its own process, so there is exactly one, with no `if`
        # list: the script picks out install commands itself (standards point 13, review finding 2)
        groups = load("hooks/hooks.json")["hooks"]
        self.assertEqual(list(groups), ["PreToolUse"])
        self.assertEqual([g["matcher"] for g in groups["PreToolUse"]], ["Bash|PowerShell"])
        self.assertEqual(len(handlers()), 1)
        self.assertNotIn("if", handlers()[0])

    def test_quick_filter_is_the_same_in_both_modules(self):
        import pkg_vitals_hook
        self.assertEqual(pkg_vitals_hook.QUICK.pattern, pv.QUICK.pattern)

    def test_hook_commands_point_at_files_that_exist(self):
        for h in handlers():
            self.assertEqual(h["type"], "command")
            for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", h["command"]):
                self.assertTrue((ROOT / rel).is_file(), rel)

    def test_hook_timeouts_are_seconds_above_the_budget(self):
        for h in handlers():
            # seconds (a value in ms would be a typo), and above the hook's own 15 s budget
            self.assertTrue(15 < h["timeout"] <= 60, h["timeout"])

    def test_skill_front_matter(self):
        text = (ROOT / "skills" / "pkg-vitals" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: pkg-vitals\ndescription: "))
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text):
            self.assertTrue((ROOT / rel).is_file(), rel)


class Packaging(Case):
    def test_pyproject(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for line in ('requires = ["setuptools>=77"]', 'license = "MIT"', 'requires-python = ">=3.9"', "dependencies = []",
                     'pkg-vitals = "pkg_vitals:main"', 'pkg-vitals-hook = "pkg_vitals_hook:main"',
                     'py-modules = ["pkg_vitals", "pkg_vitals_hook"]'):
            self.assertIn(line, text)

    def test_no_generic_top_level_modules(self):
        # two tools shipping a module called hook.py would overwrite each other in one environment
        names = {p.stem for p in ROOT.glob("*.py")}
        self.assertFalse(names & {"hook", "doctor", "server", "cli", "utils", "main"})
        self.assertTrue(all(n.startswith("pkg_vitals") for n in names), names)

    def test_sdist_manifest_carries_what_the_tests_need(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        for needed in ("tests", "fixtures", ".claude-plugin", "hooks", "skills", "pkg_vitals_hook.py"):
            self.assertIn(needed, manifest)

    def test_workflows_pin_their_actions(self):
        for name in ("test.yml", "release.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn(CHECKOUT, text)
            self.assertIn(SETUP_PYTHON, text)
            self.assertIn("runs-on: ubuntu-24.04", text)
            for uses in re.findall(r"uses:\s*(\S+)", text):
                self.assertRegex(uses, r"@[0-9a-f]{40}$")
        self.assertIn('python: ["3.9", "3.12"]', (ROOT / ".github" / "workflows" / "test.yml").read_text())

    def test_licence_file(self):
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", (ROOT / "LICENSE").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
