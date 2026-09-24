"""Release metadata agrees with itself, and the shipped snapshot still says what the README quotes."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import ROOT, IsolatedTestCase  # noqa: E402

from ghg_factors_mcp import VERSION  # noqa: E402
from ghg_factors_mcp import factors as F  # noqa: E402
from ghg_factors_mcp import refresh as R  # noqa: E402

PYPI_NAME = "ghg-factors-mcp"
REGISTRY_NAME = f"io.github.Keremozdemirra/{PYPI_NAME}"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class Metadata(IsolatedTestCase):
    def test_versions_and_names_agree(self):
        pyproject = text("pyproject.toml")
        server = json.loads(text("server.json"))
        self.assertIn(f'name = "{PYPI_NAME}"', pyproject)
        self.assertIn(f'version = "{VERSION}"', pyproject)
        self.assertEqual((server["name"], server["version"]), (REGISTRY_NAME, VERSION))
        pkg = server["packages"][0]
        self.assertEqual((pkg["registryType"], pkg["identifier"], pkg["version"], pkg["runtimeHint"], pkg["transport"]),
                         ("pypi", PYPI_NAME, VERSION, "uvx", {"type": "stdio"}))
        self.assertLess(len(server["description"]), 100)
        self.assertIn(f"<!-- mcp-name: {REGISTRY_NAME} -->", text("README.md"))

    def test_pyproject_rules(self):
        pyproject = text("pyproject.toml")
        for line in ('requires = ["setuptools>=77"]', 'license = "MIT"', 'requires-python = ">=3.9"',
                     "dependencies = []", 'ghg-factors-mcp = "ghg_factors_mcp.__main__:main"'):
            self.assertIn(line, pyproject)
        self.assertIn("Copyright (c) 2026 Kerem Özdemir", text("LICENSE"))
        manifest = text("MANIFEST.in")
        self.assertIn("recursive-include data", manifest)
        self.assertIn("recursive-include tests", manifest)

    def test_workflows_pin_actions(self):
        test = text(".github/workflows/test.yml")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("runs-on: ubuntu-24.04", test)
        self.assertIn('python: ["3.9", "3.12"]', test)
        release = text(".github/workflows/release.yml")
        self.assertIn("id-token: write", release)
        self.assertNotRegex(release, r"(?i)password|api[_-]?token")
        for wf in (test, release):
            for uses in re.findall(r"uses: (\S+)", wf):
                self.assertRegex(uses, r"@[0-9a-f]{40}$", uses)

    def test_no_forbidden_top_level_modules(self):
        self.assertFalse(any((ROOT / f"{m}.py").exists() for m in ("server", "cli", "hook", "doctor", "utils")))
        self.assertFalse(any((ROOT / "ghg_factors_mcp" / f"{m}.py").exists() for m in ("server", "cli")))


class ShippedSnapshot(IsolatedTestCase):
    """data/ as committed: consistent with its manifest, and with the numbers the README shows."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GHG_FACTORS_DATA": str(ROOT / "data")})
        patcher.start()
        self.addCleanup(patcher.stop)
        F._cache.clear()
        self.addCleanup(F._cache.clear)

    def test_manifest_matches_files(self):
        manifest = json.loads(text("data/manifest.json"))
        self.assertEqual(sorted(manifest["sources"]), ["desnz-2025", "desnz-2026", "ember", "uba"])
        for key, m in manifest["sources"].items():
            self.assertRegex(m["raw_sha256"], r"^[0-9a-f]{64}$", key)
            path = ROOT / "data" / m["file"]
            if path.suffix == ".csv":
                with path.open(encoding="utf-8", newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), m["rows"], key)
                if key.startswith("desnz"):
                    self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertEqual(text("data/SOURCES.md"), R.sources_markdown(manifest))  # generated, never hand-edited

    def test_readme_numbers(self):
        readme = text("README.md")
        diesel = F.convert(1000, "litres", "desnz-2026:1_101_1011_8_1")
        gas = F.convert(1000, "kWh (Gross CV)", "desnz-2026:1_100_1004_6_1")
        poland = F.grid_intensity("Poland", 2025)
        germany = F.grid_intensity("Germany", 2025, "all")["answers"]
        for shown in (diesel["arithmetic"], gas["arithmetic"], poland["value_text"] + " g CO2e/kWh",
                      germany[0]["value_text"] + " g CO2e/kWh", germany[1]["value_text"] + " g CO2/kWh"):
            self.assertIn(shown, readme)


if __name__ == "__main__":
    import unittest
    unittest.main()
