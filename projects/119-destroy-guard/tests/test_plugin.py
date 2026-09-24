"""The plugin files, the packaging and the workflows, checked against each other and against the code."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated  # noqa: E402

import destroy_guard as dg  # noqa: E402

CHECKOUT = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class Plugin(Isolated):
    def test_manifest_and_marketplace_agree(self):
        plugin, market = load(".claude-plugin/plugin.json"), load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"] and market["owner"]["name"])
        self.assertEqual(plugin["version"], dg.VERSION)

    def test_one_handler_for_bash_and_powershell(self):
        # hook fan-out: every matching handler is its own process, so one handler, filtering inside the script
        hooks = load("hooks/hooks.json")["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse"})
        [group] = hooks["PreToolUse"]
        self.assertEqual(group["matcher"], "Bash|PowerShell")
        [handler] = group["hooks"]
        self.assertNotIn("if", handler)
        self.assertEqual(handler["type"], "command")
        self.assertLessEqual(handler["timeout"], 60)  # seconds
        rels = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", handler["command"])
        self.assertEqual(rels, ["destroy_guard_hook.py"])
        self.assertTrue((ROOT / rels[0]).is_file())

    def test_skill(self):
        text = (ROOT / "skills" / "destroy-guard" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: destroy-guard\ndescription: "))
        rels = set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text))
        self.assertEqual(rels, {"destroy_guard.py"})
        for sub in re.findall(r"destroy_guard\.py\" (\w+)", text):
            self.assertIn(sub, ("backup", "check", "list"))


class Packaging(Isolated):
    def test_pyproject(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for needed in ('requires = ["setuptools>=77"]', 'license = "MIT"', 'requires-python = ">=3.9"',
                       "dependencies = []", f'version = "{dg.VERSION}"', 'destroy-guard = "destroy_guard:main"',
                       'destroy-guard-hook = "destroy_guard_hook:main"',
                       'py-modules = ["destroy_guard", "destroy_guard_hook"]'):
            self.assertIn(needed, text)
        for name in ("hook.py", "cli.py", "utils.py", "server.py", "doctor.py"):
            self.assertFalse((ROOT / name).exists(), name)

    def test_sdist_carries_what_the_tests_read(self):
        text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        for needed in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "hooks/hooks.json",
                       "skills/destroy-guard/SKILL.md", ".github/workflows/test.yml", "recursive-include tests *.py"):
            self.assertIn(needed, text)

    def test_workflows_pin_actions(self):
        for name in ("test.yml", "release.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertIn(CHECKOUT, text)
            self.assertIn(SETUP_PYTHON, text)
            self.assertIn("runs-on: ubuntu-24.04", text)
            self.assertNotIn("ubuntu-latest", text)
        self.assertIn('python: ["3.9", "3.12"]', (ROOT / ".github" / "workflows" / "test.yml").read_text())

    def test_licence(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", text)

    def test_no_token_shaped_literals(self):
        # a token-shaped string anywhere trips secret scanning; the tests build theirs at run time
        pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|"
                             r"github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                             r"r8_[A-Za-z0-9]{32}")
        for p in ROOT.rglob("*"):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertIsNone(pattern.search(text), p)

    def test_readme_sections(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("/plugin marketplace add Keremozdemirra/destroy-guard", text)
        self.assertIn("/plugin install destroy-guard@destroy-guard", text)
        self.assertIn(f"uvx destroy-guard@{dg.VERSION}", text)
        self.assertTrue(text.rstrip().split("\n## ")[-1].startswith("What this is not"))


if __name__ == "__main__":
    unittest.main()
