"""The snapshot shipped in data/: internally consistent, and saying what the
live refresh of 2026-09-24 found."""
import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import annex, lookup  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class Integrity(unittest.TestCase):
    def test_manifest_hashes_match_files(self):
        manifest = load("manifest.json")
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), digest, name)
        sources = (DATA / "SOURCES.md").read_text(encoding="utf-8")
        for doc in manifest["documents"]:
            self.assertIn(doc["sha256"], sources)
            self.assertTrue(doc["final_url"].startswith("https://publications.europa.eu/"))

    def test_statuses_and_counts(self):
        manifest = load("manifest.json")
        for name in ("annex_i.json", "application_dates.json", "country_risk.json"):
            self.assertEqual(load(name)["status"], "verified", name)
        counts = manifest["counts"]
        self.assertEqual((counts["low_risk_countries"], counts["high_risk_countries"]), (140, 4))
        self.assertGreater(counts["authority_table_countries"], 240)

    def test_entries_are_well_formed(self):
        entries = load("annex_i.json")["entries"]
        self.assertEqual({e["commodity"] for e in entries}, set(annex.COMMODITIES))
        ids = [e["id"] for e in entries]
        self.assertEqual(len(ids), len(set(ids)))
        for e in entries:
            for c in e["codes"]:
                self.assertRegex(c["code"], r"^\d{2}(\d{2}){0,3}$")
            self.assertNotRegex(" ".join([e["description"]] + e["notes"]), r"https?://|OJ [LC] \d")
            if e["valid_from"] and e["valid_to"]:
                self.assertLessEqual(e["valid_from"], e["valid_to"])

    def test_no_arrow_markers_left(self):
        for name in ("annex_i.json", "application_dates.json"):
            text = (DATA / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search("[" + chr(0x25BA) + chr(0x25BC) + chr(0x25C4) + "]", text), name)


class LiveFindings(unittest.TestCase):
    def setUp(self):
        self.env = support.SnapshotEnv(DATA)
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)

    def test_scope_on_2026_09_24(self):
        self.assertEqual(lookup.eudr_scope("1801 00 00")["status"], "relevant_product")
        self.assertEqual(lookup.eudr_scope("4401")["status"], "partly_ex")
        self.assertEqual(lookup.eudr_scope("4010")["status"], "not_listed")
        self.assertEqual(lookup.eudr_scope("3401 11 00", "2027-12-30")["status"], "partly_ex")

    def test_dates(self):
        a38 = load("application_dates.json")["article_38"]
        self.assertEqual((a38["p2_date"], a38["p3_date"]), ("2026-12-30", "2027-06-30"))

    def test_countries(self):
        self.assertEqual(lookup.country_risk("BR")["risk"], "standard")
        self.assertEqual(lookup.country_risk("Belarus")["risk"], "high")
        self.assertEqual(lookup.country_risk("DE")["risk"], "low")


if __name__ == "__main__":
    unittest.main()
