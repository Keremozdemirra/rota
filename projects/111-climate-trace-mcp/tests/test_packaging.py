"""Release metadata stays consistent: registry name, versions, pinned actions, snapshot hash, no secrets."""
import hashlib
import json
import re
import unittest
from pathlib import Path

try:
    from . import ctfixtures as fx
except ImportError:
    import ctfixtures as fx

import climate_trace_mcp
from climate_trace_mcp import provenance as prov

ROOT = Path(__file__).resolve().parent.parent
NAME = "io.github.Keremozdemirra/climate-trace-mcp"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class PackagingTest(fx.HomeIsolated):
    def test_registry_entry_matches_package(self):
        server = json.loads(read("server.json"))
        version = re.search(r'(?m)^version = "([^"]+)"', read("pyproject.toml")).group(1)
        self.assertEqual(server["name"], NAME)
        self.assertEqual(server["$schema"], "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
        self.assertLess(len(server["description"]), 100)
        self.assertEqual(server["repository"], {"url": "https://github.com/Keremozdemirra/climate-trace-mcp", "source": "github"})
        pkg = server["packages"][0]
        self.assertEqual((pkg["registryType"], pkg["identifier"], pkg["runtimeHint"], pkg["transport"]),
                         ("pypi", "climate-trace-mcp", "uvx", {"type": "stdio"}))
        self.assertEqual({server["version"], pkg["version"], version, climate_trace_mcp.__version__}, {version})
        self.assertIn("<!-- mcp-name: %s -->" % NAME, read("README.md"))

    def test_pyproject(self):
        p = read("pyproject.toml")
        for line in ('requires = ["setuptools>=77"]', 'license = "MIT"', 'requires-python = ">=3.9"',
                     "dependencies = []", 'climate-trace-mcp = "climate_trace_mcp.cli:main"',
                     'packages = ["climate_trace_mcp"]'):
            self.assertIn(line, p)
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", read("LICENSE"))

    def test_workflows_use_the_pinned_actions(self):
        test = read(".github/workflows/test.yml")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("runs-on: ubuntu-24.04", test)
        self.assertIn('python: ["3.9", "3.12"]', test)
        self.assertIn("python -m unittest discover -s tests", test)
        release = read(".github/workflows/release.yml")
        self.assertIn("id-token: write", release)
        self.assertIn('test "$TAG" = "v$VERSION"', release)
        self.assertNotRegex(release, r"(?i)password|api[_-]?token:")

    def test_snapshot_matches_its_sources_record(self):
        raw = (ROOT / "climate_trace_mcp" / "data" / "subsectors.json").read_bytes()
        sources = read("climate_trace_mcp/data/SOURCES.md")
        self.assertIn(hashlib.sha256(raw).hexdigest(), sources)
        snap = prov.Snapshot.load()
        self.assertIsNone(snap.error)
        self.assertEqual((len(snap.sectors), len(snap.subsectors)), (10, 69))
        self.assertIn("Retrieved | %s" % snap.retrieved, sources)
        # Every subsector named by the terms mapping exists in the API's list.
        self.assertEqual(set(prov.TERMS_SUBSECTORS) - set(snap.subsectors), set())

    def test_sdist_manifest_carries_tests_and_data(self):
        m = read("MANIFEST.in")
        for line in ("recursive-include tests *.py *.json *.yaml", "recursive-include climate_trace_mcp/data *.json *.md",
                     "recursive-include .github *.yml",
                     "include LICENSE README.md server.json"):
            self.assertIn(line, m)

    def test_no_credentials_anywhere(self):
        # The patterns publish.sh refuses to ship.
        pattern = re.compile(r"sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}"
                             r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}")
        for path in ROOT.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and ".git" not in path.parts:
                text = path.read_bytes().decode("utf-8", "ignore")
                self.assertIsNone(pattern.search(text), str(path))

    def test_no_invisible_or_bidi_characters_in_sources(self):
        # They can make code read differently from what runs ("Trojan Source"); tests spell them as escapes.
        invisible = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".md", ".yml", ".toml", ".json", ".yaml", ".in") \
                    and "__pycache__" not in path.parts:
                self.assertIsNone(invisible.search(path.read_text(encoding="utf-8")), str(path))

    def test_readme_ends_with_what_this_is_not(self):
        headings = re.findall(r"(?m)^## (.+)$", read("README.md"))
        self.assertEqual(headings[-1], "What this is not")

    def test_no_generic_top_level_modules(self):
        top = {p.stem for p in ROOT.glob("*.py")}
        self.assertEqual(top & {"hook", "doctor", "server", "cli", "utils"}, set())


if __name__ == "__main__":
    unittest.main()
