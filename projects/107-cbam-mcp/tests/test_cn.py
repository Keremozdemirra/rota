"""cn_describe and sources over data built from the trimmed real CN 2025/2026 answers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import DataEnv  # noqa: E402
from cbam_mcp import lookup  # noqa: E402
from cbam_mcp.codes import InputError  # noqa: E402


class Describe(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_electricity(self):
        r = lookup.cn_describe("2716 00 00")
        self.assertEqual((r["found"], r["label"], r["year"]), (True, "Electrical energy", 2026))
        self.assertEqual([h["cn_code"] for h in r["hierarchy"]], ["V", "27"])
        self.assertEqual(r["in_cn_2025"], "same label")
        self.assertIn("2025/1926", r["legally_binding_source"])
        self.assertIs(r["legally_binding"], False)

    def test_heading_written_with_zeros(self):
        self.assertEqual(lookup.cn_describe("2716")["cn_code"], "2716 00 00")

    def test_hierarchy_includes_unnumbered_lines(self):
        r = lookup.cn_describe("7208.51.98")
        labels = [h["label"] for h in r["hierarchy"]]
        self.assertIn("Of a thickness exceeding 10 mm but not exceeding 15 mm, of a width of", labels)
        self.assertEqual(r["label"], "Less than 2050 mm")
        self.assertIn("Flat-rolled products of iron or non-alloy steel", r["self_explanatory_text"])

    def test_sub_codes(self):
        r = lookup.cn_describe("7202 99")
        self.assertEqual([s["cn_code"] for s in r["sub_codes"]], ["7202 99 10", "7202 99 30", "7202 99 80"])

    def test_code_new_in_2026(self):
        r = lookup.cn_describe("7308 20 10")
        self.assertEqual(r["label"], "Tubular wind turbine steel towers and tower-sections")
        self.assertEqual(r["in_cn_2025"], "no such code")
        old = lookup.cn_describe("7308 20 00", year=2025)
        self.assertTrue(old["found"])
        self.assertEqual(old["in_cn_2026"], "no such code")
        self.assertIn("2024/2522", old["legally_binding_source"])

    def test_taric_digits_are_cut(self):
        r = lookup.cn_describe("2804 10 00 00")
        self.assertEqual(r["cn_code"], "2804 10 00")
        self.assertIn("TARIC", r["warnings"][0])

    def test_outside_the_bundle(self):
        r = lookup.cn_describe("8501 10")
        self.assertFalse(r["found"])
        self.assertIn("Outside the bundled subset", r["explanation"])
        self.assertIn("not a code of CN 2026", lookup.cn_describe("7208 99 99")["explanation"])

    def test_bad_year(self):
        for year in (2024, "last", None):
            with self.assertRaises(InputError):
                lookup.cn_describe("2716", year=year)


class Sources(unittest.TestCase):
    def test_lists_every_dataset_with_hash_licence_and_status(self):
        with DataEnv():
            r = lookup.sources()
        names = [d["file"] for d in r["datasets"]]
        self.assertEqual(names, ["annex_i.json", "default_values.json", "cn_2026.json", "cn_2025.json"])
        for d in r["datasets"]:
            self.assertIs(d["legally_binding"], False)
            self.assertTrue(d["licence"]["terms"].startswith("http"))
            self.assertEqual(d["retrieved"], "2026-09-24")
        self.assertEqual(r["datasets"][1]["official_journal_check"]["rows_identical"],
                         r["datasets"][1]["official_journal_check"]["rows_compared"])
        self.assertEqual(r["later_acts"]["checked"], "2026-09-24")


if __name__ == "__main__":
    unittest.main()
