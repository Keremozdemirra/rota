"""Packaging, plugin and registry files agree with each other and with the code."""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT  # noqa: E402

import vsme_kit  # noqa: E402

NAME = "io.github.Keremozdemirra/vsme-kit"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class Packaging(unittest.TestCase):
    def test_versions_agree(self):
        plugin, server = json.loads(read(".claude-plugin/plugin.json")), json.loads(read("server.json"))
        v = vsme_kit.VERSION
        self.assertIn(f'version = "{v}"', read("pyproject.toml"))
        self.assertEqual((plugin["version"], server["version"], server["packages"][0]["version"]), (v, v, v))
        self.assertIn(f"vsme-kit@{v}", read("README.md"))

    def test_registry_listing(self):
        server = json.loads(read("server.json"))
        self.assertEqual(server["name"], NAME)
        self.assertLess(len(server["description"]), 100)
        pkg = server["packages"][0]
        self.assertEqual((pkg["registryType"], pkg["identifier"], pkg["runtimeHint"], pkg["transport"]["type"]),
                         ("pypi", "vsme-kit", "uvx", "stdio"))
        self.assertEqual(pkg["packageArguments"], [{"type": "positional", "value": "mcp"}])
        self.assertIn(f"<!-- mcp-name: {NAME} -->", read("README.md"))

    def test_plugin_and_marketplace(self):
        plugin, market = json.loads(read(".claude-plugin/plugin.json")), json.loads(read(".claude-plugin/marketplace.json"))
        self.assertEqual([p["name"] for p in market["plugins"]], [plugin["name"]])
        self.assertEqual(market["plugins"][0]["source"], "./")
        self.assertTrue(market["description"])
        self.assertFalse((ROOT / "hooks").exists())  # a skill-only plugin

    def test_skill_front_matter_and_commands(self):
        text = read("skills/vsme-kit/SKILL.md")
        self.assertTrue(text.startswith("---\nname: vsme-kit\ndescription: "))
        self.assertIn("help me fill the VSME", text)
        self.assertIn("check our VSME report", text)
        rels = set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", text))
        self.assertEqual(rels, {"vsme-kit.py"})
        proc = subprocess.run([sys.executable, str(ROOT / "vsme-kit.py"), "disclosures", "--json"], capture_output=True,
                              timeout=60, env=dict(os.environ, HOME=str(ROOT / "tests")))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(json.loads(proc.stdout)["disclosures"]), 20)

    def test_module_names_do_not_collide(self):
        top = {p.stem for p in ROOT.glob("*.py")}
        self.assertEqual(top, {"vsme-kit"})  # a script, not an importable module
        self.assertIn('packages = ["vsme_kit", "vsme_kit.data"]', read("pyproject.toml"))
        self.assertIn('vsme-kit = "vsme_kit.cli:main"', read("pyproject.toml"))

    def test_sdist_carries_what_the_tests_read(self):
        manifest = read("MANIFEST.in")
        for needed in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "skills/vsme-kit/SKILL.md",
                       "server.json", "vsme-kit.py", "vsme_kit/data/*.json", ".github/workflows/test.yml",
                       ".github/workflows/release.yml", "recursive-include tests *.py *.xhtml *.md", "THIRD_PARTY_NOTICES.md"):
            self.assertIn(needed, manifest)

    def test_workflows_pin_the_actions(self):
        test = read(".github/workflows/test.yml")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("runs-on: ubuntu-24.04", test)
        self.assertIn('python: ["3.9", "3.12"]', test)
        release = read(".github/workflows/release.yml")
        self.assertIn("id-token: write", release)
        self.assertIn('test "$TAG" = "v$VERSION"', release)

    def test_snapshots_match_their_sources_file(self):
        sources = read("vsme_kit/data/SOURCES.md")
        for edition in ("2025", "2026"):
            snap = json.loads(read(f"vsme_kit/data/standard-{edition}.json"))
            self.assertIn(snap["source"]["sha256"], sources)
            self.assertIn(snap["celex"], sources)
            self.assertEqual(snap["licence"]["terms"], "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html")
        for needed in ("Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial "
                       "or non-commercial purposes.", "All documents shall be available for reuse",
                       "the editorial content of this website, the summaries of EU legislation and the consolidated texts",
                       "web.archive.org/web/20260922160312"):
            self.assertIn(needed, " ".join(sources.split()))
        for rel in ("README.md", "THIRD_PARTY_NOTICES.md", "tests/fixtures/README.md"):
            text = " ".join(read(rel).split())
            self.assertNotRegex(text, r"(Official Journal|OJ|bundled|EU texts?)[^.]{0,80}CC BY 4\.0", rel)

    def test_no_token_shaped_literals(self):
        pattern = re.compile("|".join([r"sk-ant-[A-Za-z0-9_-]{20}", r"sk-[A-Za-z0-9]{32}", r"ghp_[A-Za-z0-9]{36}",
                                       r"github_pat_[A-Za-z0-9_]{40}", r"AKIA[0-9A-Z]{16}",
                                       r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"r8_[A-Za-z0-9]{32}"]))
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.suffix in (".py", ".md", ".json", ".yml", ".toml", ".xhtml", ".in", ""):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8", errors="replace")), str(path))


if __name__ == "__main__":
    unittest.main()
