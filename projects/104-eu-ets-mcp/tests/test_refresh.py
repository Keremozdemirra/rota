"""Refresh end to end against the loopback registry, the snapshot it writes, and which data wins."""
import gzip
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import FILES, PLACEHOLDERS, Isolated, Registry, build_fixture_db, eu_ets, gz, no_sleep  # noqa: E402


def quiet(_msg):
    return None


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()
        self.reg = Registry().__enter__()

    def tearDown(self):
        self.reg.__exit__()
        self.env.__exit__()

    def refresh(self, **kw):
        return eu_ets.refresh(listing_url=self.reg.listing_url, timeout=5, sleep=no_sleep, log=quiet, **kw)

    def test_refresh_builds_the_cache_and_tolerates_missing_compliance_files(self):
        meta = self.refresh()
        self.assertEqual(meta["counts"]["installations"], 15)
        self.assertEqual(meta["compliance_years"], [2024])
        # the listing offers 2021-2023 too; the loopback registry answers 404 for them
        self.assertEqual(sorted(e["file"] for e in meta["errors"]),
                         ["compliance_2021_code_en.xlsx", "compliance_2022_code_en.xlsx", "compliance_2023_code_en.xlsx"])
        ops = next(s for s in meta["sources"] if s["kind"] == "operators")
        self.assertEqual((ops["sha256"], ops["malformed_rows"]), (eu_ets.sha256_file(FILES[ops["file"]]), 3))
        self.assertEqual(meta["snapshot_date"], "2026-09-24")
        self.assertEqual(list((self.env.cache / "raw").iterdir()), [])  # downloads removed
        self.assertEqual(eu_ets.read_meta(self.env.cache / eu_ets.DB_NAME)["origin"], "live")

    def test_failed_refresh_keeps_the_old_cache(self):
        first = self.refresh()
        broken = FILES["operators_yearly_activity_daily.csv.gz"].read_bytes()[:3000]  # complete HTTP, truncated gzip
        self.reg.faults["operators_yearly_activity_daily.csv.gz"] = [("serve", broken)]
        with self.assertRaisesRegex(eu_ets.ParseError, "truncated"):
            self.refresh()
        self.assertEqual(eu_ets.read_meta(self.env.cache / eu_ets.DB_NAME)["built_at"], first["built_at"])
        self.assertEqual([p.name for p in self.env.cache.iterdir() if p.is_file()], [eu_ets.DB_NAME])
        self.assertEqual(list((self.env.cache / "raw").iterdir()), [])

    def test_an_extract_without_rows_does_not_replace_the_cache(self):
        first = self.refresh()
        header = gzip.decompress(FILES["operators_daily.csv.gz"].read_bytes()).split(b"\r\n")[0].decode()
        self.reg.faults["operators_daily.csv.gz"] = [("serve", gz(header + "\r\n"))]
        with self.assertRaisesRegex(eu_ets.ParseError, "no installations"):
            self.refresh()
        self.assertEqual(eu_ets.read_meta(self.env.cache / eu_ets.DB_NAME)["built_at"], first["built_at"])

    def test_listing_down_leaves_nothing_behind(self):
        self.reg.faults["listing"] = [("status", 404)]
        with self.assertRaises(eu_ets.FetchError):
            self.refresh()
        self.assertFalse((self.env.cache / eu_ets.DB_NAME).exists())


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()
        self.db = build_fixture_db(self.env.cache)

    def tearDown(self):
        self.env.__exit__()

    def test_snapshot_is_reproducible_byte_for_byte(self):
        a, b = self.env.path / "a", self.env.path / "b"
        eu_ets.export_snapshot(self.db, a)
        db2 = self.env.path / "rebuilt" / eu_ets.DB_NAME
        eu_ets.build_from_snapshot(a, db2)
        eu_ets.export_snapshot(db2, b)
        for name in eu_ets.SNAPSHOT_FILES + ("snapshot.json", "SOURCES.md"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
        manifest = json.loads((a / "snapshot.json").read_text(encoding="utf-8"))
        for name, f in manifest["files"].items():
            self.assertEqual(f["sha256"], eu_ets.sha256_file(a / name))
        self.assertIn(manifest["files"]["installations.csv.gz"]["sha256"], (a / "SOURCES.md").read_text(encoding="utf-8"))

    def test_snapshot_and_cache_hold_only_allowlisted_columns_and_no_placeholder_text(self):
        out = self.env.path / "snap"
        eu_ets.export_snapshot(self.db, out)
        inst = gzip.decompress((out / "installations.csv.gz").read_bytes()).decode("utf-8")
        yearly = gzip.decompress((out / "yearly.csv.gz").read_bytes()).decode("utf-8")
        self.assertEqual(inst.splitlines()[0].split(","), list(eu_ets.OPERATOR_COLUMNS))
        self.assertEqual(yearly.splitlines()[0].split(","), list(eu_ets.YEARLY_COLUMNS))
        everything = inst + yearly + (out / "SOURCES.md").read_text(encoding="utf-8") + \
            (out / "snapshot.json").read_text(encoding="utf-8")
        db_bytes = self.db.read_bytes()
        for p in PLACEHOLDERS:
            self.assertNotIn(p, everything)
            self.assertNotIn(p.encode("utf-8"), db_bytes)


class WhichDataTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()

    def tearDown(self):
        self.env.__exit__()

    def snapshot(self, date: str) -> Path:
        tmp = self.env.path / "build"
        db = build_fixture_db(tmp)
        snap = self.env.path / f"snap-{date}"
        eu_ets.export_snapshot(db, snap)
        manifest = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
        manifest["snapshot_date"] = date
        (snap / "snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")
        return snap

    def test_no_cache_and_no_bundle(self):
        with self.assertRaisesRegex(eu_ets.DataUnavailable, "eu-ets refresh"):
            eu_ets.ensure_database()

    def test_bundle_builds_the_cache_on_first_use(self):
        import os
        os.environ["EU_ETS_SNAPSHOT_DIR"] = str(self.snapshot("2026-09-24"))
        db = eu_ets.ensure_database()
        self.assertEqual((db.parent, eu_ets.read_meta(db)["origin"]), (self.env.cache, "bundled"))

    def test_newer_bundle_replaces_an_older_cache_and_an_older_bundle_does_not(self):
        import os
        build_fixture_db(self.env.cache)  # snapshot 2026-09-24, origin live
        os.environ["EU_ETS_SNAPSHOT_DIR"] = str(self.snapshot("2026-01-01"))
        self.assertEqual(eu_ets.read_meta(eu_ets.ensure_database())["origin"], "live")
        os.environ["EU_ETS_SNAPSHOT_DIR"] = str(self.snapshot("2027-01-01"))
        meta = eu_ets.read_meta(eu_ets.ensure_database())
        self.assertEqual((meta["origin"], meta["snapshot_date"]), ("bundled", "2027-01-01"))

    def test_a_corrupt_cache_is_rebuilt_from_the_bundle(self):
        import os
        self.env.cache.mkdir(parents=True)
        (self.env.cache / eu_ets.DB_NAME).write_bytes(b"not a database")
        os.environ["EU_ETS_SNAPSHOT_DIR"] = str(self.snapshot("2026-09-24"))
        self.assertEqual(eu_ets.read_meta(eu_ets.ensure_database())["origin"], "bundled")

    def test_cache_dir_honours_the_environment_and_never_the_real_home(self):
        import os
        self.assertEqual(eu_ets.cache_dir(), self.env.cache)
        del os.environ["EU_ETS_CACHE_DIR"]
        if sys.platform.startswith("linux"):
            self.assertEqual(eu_ets.cache_dir(), self.env.path / "xdg" / "eu-ets-mcp")
        self.assertTrue(str(eu_ets.cache_dir()).startswith(str(self.env.path)))


if __name__ == "__main__":
    unittest.main()
