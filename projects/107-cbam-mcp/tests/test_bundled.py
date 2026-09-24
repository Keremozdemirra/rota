"""The snapshot that ships in the wheel, and the packaging files around it."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import ROOT  # noqa: E402
from cbam_mcp import __version__, lookup  # noqa: E402
from cbam_mcp.codes import ISO_BY_TABLE_NAME  # noqa: E402

DATA = ROOT / "cbam_mcp" / "data"


class Snapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = lookup.Store(DATA)

    def test_scope_snapshot(self):
        a = self.s.annex
        self.assertEqual(a["meta"]["celex"], "02023R0956-20251020")
        self.assertEqual(len(a["annex_i"]), 42)
        ex = [e["code"] for e in a["annex_i"] if e["ex"]]
        self.assertEqual(ex, ["25070080"])
        self.assertIn("50 tonnes of net mass", a["quotes"]["annex_vii_1"])

    def test_default_value_snapshot(self):
        v = self.s.values
        m = v["meta"]
        self.assertEqual((m["version"], m["version_date"], m["tables"], m["lines"], m["rows"]), ("2", "2026-08-06", 122, 283, 12540))
        # Spot values, also printed in the Official Journal (OJ L, 2026/1740): India and Türkiye, CN 7601.
        self.assertEqual(v["tables"]["India"]["7601"], "1,870|N/A|1,870|(K)")
        self.assertEqual(v["tables"]["Türkiye"]["7601"], "1,700|N/A|1,700|(K)")
        check = m["oj_check"]
        self.assertEqual((check["rows_identical"], check["rows_compared"]), (12540, 12540))
        self.assertEqual((check["annex_iv_identical"], check["annex_iv_compared"]), (283, 283))

    def test_every_country_table_has_an_iso_code(self):
        names = [n for n in self.s.values["tables"] if n != self.s.values["other_table"]]
        self.assertEqual(len(names), 121)
        self.assertEqual(sorted(set(names) - set(ISO_BY_TABLE_NAME)), [])

    def test_cn_snapshots(self):
        for year in (2026, 2025):
            self.assertGreater(self.s.cn(year)["meta"]["concepts"], 1500)
        self.assertEqual(self.s.cn_lookup(2026, "27160000")[1][1], "Electrical energy")

    def test_sources_md_matches_the_files(self):
        text = (DATA / "SOURCES.md").read_text(encoding="utf-8")
        for name in ("annex_i.json", "default_values.json"):
            meta = json.loads((DATA / name).read_text(encoding="utf-8"))["meta"]
            self.assertIn(meta["sha256"], text, name)
            self.assertIn(meta["retrieved"], text, name)
        for year in (2026, 2025):
            for h in self.s.cn(year)["meta"]["sha256_of_responses"]:
                self.assertIn(h, text)


class Packaging(unittest.TestCase):
    def test_versions_and_registry_name_agree(self):
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f'version = "{__version__}"', pyproject)
        self.assertEqual(server["version"], __version__)
        self.assertEqual(server["packages"][0]["version"], __version__)
        self.assertEqual(server["packages"][0]["identifier"], "cbam-mcp")
        self.assertIn(f"<!-- mcp-name: {server['name']} -->", readme)
        self.assertLess(len(server["description"]), 100)

    def test_data_ships_in_wheel_and_sdist(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('packages = ["cbam_mcp", "cbam_mcp.data"]', pyproject)
        self.assertIn('"cbam_mcp.data" = ["*.json", "SOURCES.md"]', pyproject)
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertIn("recursive-include cbam_mcp/data", manifest)
        self.assertIn("recursive-include tests", manifest)

    def test_workflows_pin_actions(self):
        test = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0", test)
        self.assertIn("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0", test)
        self.assertIn("ubuntu-24.04", test)
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            for ref in re.findall(r"uses: (\S+)", wf.read_text(encoding="utf-8")):
                self.assertRegex(ref, r"@[0-9a-f]{40}$", f"{wf.name}: {ref} is not pinned to a commit")

    def test_no_module_reads_the_home_directory(self):
        for py in (ROOT / "cbam_mcp").glob("*.py"):
            text = py.read_text(encoding="utf-8")
            for pattern in ("Path.home", "expanduser", "os.environ[\"HOME\"]", "getenv(\"HOME\")"):
                self.assertNotIn(pattern, text, f"{py.name} uses {pattern}")


if __name__ == "__main__":
    unittest.main()
