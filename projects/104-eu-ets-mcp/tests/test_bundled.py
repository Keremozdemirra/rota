"""The snapshot shipped in data/: what the manifest says is what the files hold, and nothing else."""
import csv
import gzip
import io
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import ROOT, Isolated, eu_ets  # noqa: E402

DATA = ROOT / "data"


class BundledSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))

    def test_manifest_matches_the_files(self):
        for name, f in self.manifest["files"].items():
            self.assertEqual(eu_ets.sha256_file(DATA / name), f["sha256"], name)
            lines = gzip.decompress((DATA / name).read_bytes()).decode("utf-8").count("\n")
            self.assertEqual(lines - 1, f["rows"], name)
        sources = (DATA / "SOURCES.md").read_text(encoding="utf-8")
        for s in self.manifest["sources"]:
            self.assertIn(s["sha256"], sources)
        self.assertIn(eu_ets.TERMS_URL, sources)
        self.assertIn("identifiable private individuals", sources)
        self.assertEqual((self.manifest["licence"], self.manifest["snapshot_date"]), ("CC BY 4.0", "2026-09-24"))

    def test_only_allowlisted_columns(self):
        first = lambda name: gzip.decompress((DATA / name).read_bytes()).decode("utf-8").split("\n", 1)[0]  # noqa: E731
        self.assertEqual(first("installations.csv.gz").split(","), list(eu_ets.OPERATOR_COLUMNS))
        self.assertEqual(first("yearly.csv.gz").split(","), list(eu_ets.YEARLY_COLUMNS))
        for name in eu_ets.SNAPSHOT_FILES:
            head = first(name)
            for col in ("ACCOUNT_HOLDER_NAME", "ACCOUNT_IDENTIFIER_IN_REG", "ADDRESS1", "POSTAL_CODE"):
                self.assertNotIn(col, head)

    def rows(self):
        return list(csv.DictReader(io.StringIO(gzip.decompress((DATA / "installations.csv.gz").read_bytes()).decode("utf-8"))))

    def test_installations_the_review_found_to_name_persons_are_withheld(self):
        # The 2026-09-24 review found these installation names to name natural persons. Only ids are
        # written here, and a failure reports only the id.
        nine = {("ES", "287"), ("CZ", "310"), ("ES", "142"), ("IT", "1012"), ("NL", "423"), ("NL", "414"),
                ("DE", "219960"), ("DE", "222989"), ("DE", "223061")}
        found = {(r["REGISTRY_CODE"], r["INSTALLATION_IDENTIFIER"]): r for r in self.rows()
                 if (r["REGISTRY_CODE"], r["INSTALLATION_IDENTIFIER"]) in nine}
        self.assertEqual(set(found), nine)
        for key, r in found.items():
            self.assertTrue(r["INSTALLATION_NAME"] == eu_ets.WITHHELD and r["CITY"] == "", f"{key} is not withheld")

    def test_withheld_counts_agree(self):
        withheld = sum(1 for r in self.rows() if r["INSTALLATION_NAME"] == eu_ets.WITHHELD)
        self.assertEqual(withheld, self.manifest["counts"]["names_withheld"])
        ops = next(s for s in self.manifest["sources"] if s["kind"] == "operators")
        self.assertEqual(sum(ops["names_withheld_by_reason"].values()), withheld)
        self.assertIn(f"{withheld} installation names", (DATA / "SOURCES.md").read_text(encoding="utf-8"))

    def test_default_path_builds_the_cache_from_the_bundle(self):
        with Isolated() as env:
            os.environ["EU_ETS_SNAPSHOT_DIR"] = str(DATA)
            ds = eu_ets.Dataset()
            info = ds.dataset_info()
            self.assertEqual((info["origin"], info["counts"]["installations"]), ("bundled snapshot", self.manifest["counts"]["installations"]))
            self.assertEqual(Path(info["database"]).parent, env.cache)
            top = ds.top_emitters(country="DE", activity="steel", limit=1)
            self.assertEqual(top["installations"][0]["activity_code"], 24)


if __name__ == "__main__":
    unittest.main()
