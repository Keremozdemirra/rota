"""The plugin files, the packaging, and the repository itself (no token-shaped text anywhere)."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, cr  # noqa: E402

# the patterns ship.sh and publish.sh scan every commit for
SHIP_PATTERNS = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}"
                           r"|AKIA[0-9A-Z]{16}|-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}|r8_[A-Za-z0-9]{32}")


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class Plugin(unittest.TestCase):
    def test_manifest_and_marketplace_agree(self):
        plugin, market = load(".claude-plugin/plugin.json"), load(".claude-plugin/marketplace.json")
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"])
        self.assertTrue(market["owner"]["name"])

    def test_versions_agree(self):
        plugin = load(".claude-plugin/plugin.json")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{plugin["version"]}"', pyproject)
        self.assertEqual(cr.VERSION, plugin["version"])

    def test_no_hooks(self):
        self.assertFalse((ROOT / "hooks").exists())

    def test_skill_front_matter_and_commands(self):
        text = (ROOT / "skills" / "credential-reach" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: credential-reach\ndescription: "))
        rels = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text)
        self.assertTrue(rels)
        for rel in rels:
            self.assertEqual(rel, "credential_reach.py")
            self.assertTrue((ROOT / rel).is_file())


class Packaging(unittest.TestCase):
    def test_module_name_and_script(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('py-modules = ["credential_reach"]', pyproject)
        self.assertIn('credential-reach = "credential_reach:main"', pyproject)
        self.assertIn('requires-python = ">=3.9"', pyproject)
        self.assertIn("dependencies = []", pyproject)

    def test_sdist_carries_what_the_tests_read(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        for needed in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "skills/credential-reach/SKILL.md",
                       ".github/workflows/test.yml", ".github/workflows/release.yml", "recursive-include tests *.py"):
            self.assertIn(needed, manifest)

    def test_readme_install_lines(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for line in (f"uvx credential-reach@{cr.VERSION}", "/plugin marketplace add Keremozdemirra/credential-reach",
                     "/plugin install credential-reach@credential-reach",
                     "https://raw.githubusercontent.com/Keremozdemirra/credential-reach/main/credential_reach.py"):
            self.assertIn(line, readme)
        self.assertTrue(readme.rstrip().split("\n## ")[-1].startswith("What this is not"))


class Repository(unittest.TestCase):
    def test_no_token_shaped_text_in_any_file(self):
        hits = []
        for p in ROOT.rglob("*"):
            if p.is_file() and not {"__pycache__", ".git", "build", "dist"} & set(p.parts):
                text = p.read_bytes().decode("utf-8", "replace")
                hits += [f"{p.relative_to(ROOT)}: {m.group(0)[:12]}..." for m in SHIP_PATTERNS.finditer(text)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
