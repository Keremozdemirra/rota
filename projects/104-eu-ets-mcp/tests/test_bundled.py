"""The snapshot shipped in data/: what the manifest says is what the files hold, and nothing else."""
import gzip
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
        self.assertIn("https://commission.europa.eu/legal-notice_en", sources)
        self.assertEqual((self.manifest["licence"], self.manifest["snapshot_date"]), ("CC BY 4.0", "2026-09-24"))

    def test_only_allowlisted_columns(self):
        first = lambda name: gzip.decompress((DATA / name).read_bytes()).decode("utf-8").split("\n", 1)[0]  # noqa: E731
        self.assertEqual(first("installations.csv.gz").split(","), list(eu_ets.OPERATOR_COLUMNS))
        self.assertEqual(first("yearly.csv.gz").split(","), list(eu_ets.YEARLY_COLUMNS))
        for name in eu_ets.SNAPSHOT_FILES:
            head = first(name)
            for col in ("ACCOUNT_HOLDER_NAME", "ACCOUNT_IDENTIFIER_IN_REG", "ADDRESS1", "POSTAL_CODE"):
                self.assertNotIn(col, head)

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
