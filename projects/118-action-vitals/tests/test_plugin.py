"""The plugin files, the packaging and the CI workflow, checked against each other."""
import fnmatch
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, Isolated  # noqa: E402

import action_vitals as av  # noqa: E402
import action_vitals_hook as hook  # noqa: E402


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class Plugin(Isolated):
    def test_manifest_marketplace_and_versions_agree(self):
        plugin, market = load(".claude-plugin/plugin.json"), load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual((market["plugins"][0]["source"], bool(market["description"])), ("./", True))
        self.assertIn(f'version = "{plugin["version"]}"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(av.VERSION, plugin["version"])

    def test_one_handler_per_tool_and_extension(self):
        groups = load("hooks/hooks.json")["hooks"]
        self.assertEqual(list(groups), ["PostToolUse"])
        [group] = groups["PostToolUse"]
        self.assertEqual(group["matcher"], "Write|Edit|MultiEdit")
        rules = [h["if"] for h in group["hooks"]]
        # an `if` rule names one tool; each (tool, extension) once, so no call starts two processes
        self.assertEqual(sorted(rules), sorted(f"{t}(//**/.github/workflows/*.{e})"
                                               for t in ("Write", "Edit", "MultiEdit") for e in ("yml", "yaml")))
        for h in group["hooks"]:
            self.assertEqual(h["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/action_vitals_hook.py"')
            self.assertLessEqual(h["timeout"], 60)  # seconds
        self.assertTrue((ROOT / "action_vitals_hook.py").is_file())
        self.assertLess(hook.BUDGET, group["hooks"][0]["timeout"])

    def test_the_script_filters_as_the_rules_do(self):
        paths = ["/r/.github/workflows/ci.yml", "/r/.github/workflows/ci.yaml", "/r/.github/workflows/sub/ci.yml",
                 "/r/.github/workflows/ci.yml.bak", "/r/github/workflows/ci.yml", "/a/b/.github/workflows/x.yml"]
        for p in paths:
            by_rule = any(fnmatch.fnmatchcase(p, "*/.github/workflows/" + e) and "/" not in p.split("/.github/workflows/")[1]
                          for e in ("*.yml", "*.yaml"))
            self.assertEqual(bool(hook.WORKFLOW.search(p)), by_rule, p)

    def test_skill(self):
        text = (ROOT / "skills" / "action-vitals" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: action-vitals\ndescription: "))
        self.assertIn("pin my actions", text)
        self.assertIn("are my GitHub Actions up to date", text)
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text):
            self.assertEqual(rel, "action_vitals.py")


class Packaging(Isolated):
    def test_modules_scripts_and_manifest(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for line in ('py-modules = ["action_vitals", "action_vitals_hook"]', 'action-vitals = "action_vitals:main"',
                     'action-vitals-hook = "action_vitals_hook:main"', 'license = "MIT"', 'requires-python = ">=3.9"',
                     'requires = ["setuptools>=77"]', "dependencies = []"):
            self.assertIn(line, pyproject)
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        for needed in (".claude-plugin/plugin.json", "hooks/hooks.json", "skills/action-vitals/SKILL.md",
                       "recursive-include tests *.py *.json *.txt *.yml *.yaml"):
            self.assertIn(needed, manifest)
        for f in (ROOT / "tests").rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                self.assertIn(f.suffix, (".py", ".json", ".txt", ".yml", ".yaml"), f)

    def test_ci_uses_the_pinned_actions(self):
        text = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        files, _ = av.gather([ROOT / ".github" / "workflows" / "test.yml"])
        self.assertEqual([u["value"] for u in files[0]["uses"]],
                         ["actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
                          "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"])
        self.assertIn("runs-on: ubuntu-24.04", text)
        self.assertIn('python: ["3.9", "3.12"]', text)

    def test_readme_names_what_it_installs(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for line in ("/plugin marketplace add Keremozdemirra/action-vitals", "/plugin install action-vitals@action-vitals",
                     f"uvx action-vitals@{av.VERSION}", "## What this is not"):
            self.assertIn(line, readme)
        self.assertTrue(readme.rstrip().split("\n## ")[-1].startswith("What this is not"))


if __name__ == "__main__":
    unittest.main()
