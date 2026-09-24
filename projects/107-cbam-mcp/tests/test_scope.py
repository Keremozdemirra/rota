"""cbam_scope over data built from the trimmed real Annex I, II, III and CN 2026."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import DataEnv  # noqa: E402
from cbam_mcp import lookup  # noqa: E402
from cbam_mcp.codes import InputError  # noqa: E402
from cbam_mcp.remote import plain  # noqa: E402


class Scope(unittest.TestCase):
    def setUp(self):
        self.env = DataEnv()
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()

    def test_in_scope_code_under_a_chapter_line(self):
        r = lookup.cbam_scope("7208 51 20")
        self.assertEqual((r["status"], r["basis"]), ("in_scope", "listed"))
        self.assertEqual((r["goods_category"], r["greenhouse_gases"]), ("Iron and steel", "Carbon dioxide"))
        self.assertEqual(r["annex_i_line"]["cn_code"], "72")
        self.assertEqual(r["annex_ii"]["status"], "listed")
        self.assertEqual(plain(r["cn"]["label"]), "Of a thickness exceeding 15 mm")
        self.assertTrue(r["de_minimis"]["applies_to_these_goods"])
        self.assertIn("50 tonnes of net mass", r["de_minimis"]["annex_vii_point_1"])

    def test_every_answer_names_the_binding_act_and_version(self):
        for code in ("7208 51 20", "2507 00 80", "7317", "2716 00 00"):
            r = lookup.cbam_scope(code)
            self.assertIs(r["legally_binding"], False)
            self.assertIn("Regulation (EU) 2023/956", r["legally_binding_source"])
            self.assertIn("02023R0956-20251020", r["data_version"])
            self.assertIn("retrieved 2026-09-24", r["attribution"])

    def test_ex_code_is_never_fully_in_scope(self):
        for code in ("2507 00 80", "ex 2507 00 80", "2507008080"):
            r = lookup.cbam_scope(code)
            self.assertEqual((r["status"], r["basis"]), ("partially_in_scope", "ex_code"), code)
            self.assertTrue(r["annex_i_line"]["ex"])
            self.assertIn("only the goods its text describes", r["explanation"])
            self.assertEqual(plain(r["annex_i_line"]["text"]), "Other kaolinic clays except non-calcined kaolinic clays")
        self.assertEqual(lookup.cbam_scope("2507 00 20")["status"], "not_in_scope")

    def test_heading_with_mixed_children_lists_them(self):
        r = lookup.cbam_scope("7202")
        self.assertEqual(r["status"], "partially_in_scope")
        sub = r["subcodes"]
        in_scope = [x["cn_code"] for x in sub["in_scope"]]
        out = {x["cn_code"]: x.get("excluded_by") for x in sub["not_in_scope"]}
        self.assertIn("7202 11 20", in_scope)
        self.assertIn("7202 60 00", in_scope)
        self.assertEqual(out["7202 30 00"], "7202 30 00")
        self.assertEqual(out["7202 21 00"], "7202 2")
        self.assertEqual(sub["counts"]["in_scope"] + sub["counts"]["not_in_scope"], len(in_scope) + len(out))

    def test_subheading_whose_children_are_all_excepted(self):
        r = lookup.cbam_scope("7202 99")
        self.assertEqual((r["status"], r["basis"]), ("not_in_scope", "no_cn_subcode_in_scope"))

    def test_heading_fully_covered(self):
        r = lookup.cbam_scope("2523")
        self.assertEqual((r["status"], r["basis"]), ("in_scope", "all_cn_subcodes_in_scope"))
        self.assertEqual(r["subcodes"]["counts"]["in_scope"], 5)

    def test_out_of_scope(self):
        r = lookup.cbam_scope("7317 00")
        self.assertEqual((r["status"], r["basis"]), ("not_in_scope", "not_listed"))
        self.assertNotIn("de_minimis", r)
        self.assertEqual(lookup.cbam_scope("9999")["status"], "not_in_scope")
        r = lookup.cbam_scope("7204 10 00")
        self.assertEqual((r["status"], r["basis"]), ("not_in_scope", "excluded_by_exception"))
        self.assertEqual(lookup.cbam_scope("3105 60 00")["basis"], "excluded_by_exception")

    def test_electricity(self):
        r = lookup.cbam_scope("2716 00 00")
        self.assertEqual((r["status"], r["goods_category"]), ("in_scope", "Electricity"))
        self.assertFalse(r["de_minimis"]["applies_to_these_goods"])
        self.assertIn("electricity or hydrogen", r["de_minimis"]["article_2a_4"])
        r4 = lookup.cbam_scope("2716")
        self.assertEqual((r4["status"], r4["goods_category"]), ("in_scope", "Electricity"))

    def test_hydrogen(self):
        r = lookup.cbam_scope("2804 10 00")
        self.assertEqual((r["status"], r["goods_category"], r["greenhouse_gases"]), ("in_scope", "Chemicals", "Carbon dioxide"))
        self.assertFalse(r["de_minimis"]["applies_to_these_goods"])
        heading = lookup.cbam_scope("2804")
        self.assertEqual(heading["status"], "partially_in_scope")
        self.assertEqual([x["cn_code"] for x in heading["subcodes"]["in_scope"]], ["2804 10 00"])

    def test_prefix_wider_than_the_bundled_cn_is_not_fully_in_scope(self):
        # Review finding 3: only 2716 of chapter 27 (and 2601 of 26) is bundled; that must not read as "all covered".
        for code in ("27", "26", "260"):
            r = lookup.cbam_scope(code)
            self.assertEqual(r["status"], "partially_in_scope", code)
            self.assertFalse(r["subcodes"]["complete"], code)
            self.assertIn("bundled CN chapters", r["subcodes"]["note"])
        self.assertEqual(lookup.cbam_scope("2716")["status"], "in_scope")
        self.assertEqual(lookup.cbam_scope("84")["status"], "not_in_scope")

    def test_depends_on_names_the_missing_fact(self):
        self.assertIn("'ex' line", lookup.cbam_scope("2507 00 80")["depends_on"])
        self.assertIn("8 digits", lookup.cbam_scope("7202")["depends_on"])
        self.assertNotIn("depends_on", lookup.cbam_scope("7208 51 20"))

    def test_annex_ii_absent_for_goods_with_indirect_emissions(self):
        r = lookup.cbam_scope("2601 12 00")
        self.assertEqual((r["status"], r["annex_ii"]["status"]), ("in_scope", "not listed"))

    def test_code_missing_from_cn_is_flagged(self):
        r = lookup.cbam_scope("7208 99 99")
        self.assertEqual(r["status"], "in_scope")
        self.assertIn("not a CN 2026 code", r["warnings"][0])

    def test_limit(self):
        r = lookup.cbam_scope("7202", limit=2)
        self.assertEqual(len(r["subcodes"]["in_scope"]), 2)
        self.assertTrue(r["subcodes"]["truncated"])
        with self.assertRaises(InputError):
            lookup.cbam_scope("7202", limit="many")

    def test_invalid_code(self):
        with self.assertRaises(InputError):
            lookup.cbam_scope("72O8")


class MissingData(unittest.TestCase):
    def test_empty_data_directory_is_a_data_error(self):
        import tempfile
        with DataEnv(Path(tempfile.mkdtemp())):
            with self.assertRaises(lookup.DataError) as cm:
                lookup.cbam_scope("7208")
        self.assertIn("run `cbam-mcp refresh`", str(cm.exception))

    def test_corrupt_file_is_a_data_error(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "annex_i.json").write_bytes(b"\xff{not json")
        with DataEnv(d):
            with self.assertRaises(lookup.DataError):
                lookup.cbam_scope("7208")


if __name__ == "__main__":
    unittest.main()
