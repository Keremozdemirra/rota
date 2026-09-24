"""Header detection, layouts and datapoint fields, on the synthetic workbooks."""
from support import CLEAN, IG3, MAPPING, VARIANTS, Isolated
import xlsxmake as xm

from esrs_datapoints_mcp import parse


def by_id(ix):
    return {d["id"]: d for d in ix["datapoints"]}


class Layouts(Isolated):
    def test_ig3_layout(self):
        ix = parse.parse_workbook(IG3)
        self.assertEqual((ix["key"], ix["layout"], ix["variant"], ix["official"]), ("ig3", "ig3", None, None))
        self.assertIn("not byte-identical", ix["title"])
        self.assertEqual(ix["columns_missing"], [])
        self.assertEqual(ix["skipped_sheets"], [{"sheet": "Index", "reason": "no header row with an ID and a Name "
                                                                             "column"}])
        self.assertEqual(len(ix["datapoints"]), 17)
        self.assertEqual({s["sheet"]: s["header_row"] for s in ix["sheets"]}["ESRS E1"], 2)

    def test_revised_layouts_and_version_date(self):
        clean, mapping = parse.parse_workbook(CLEAN), parse.parse_workbook(MAPPING)
        self.assertEqual(clean["key"], "revised-2030-01-01-clean")
        self.assertEqual(mapping["key"], "revised-2030-01-01-mapping")
        self.assertEqual(clean["columns_missing"], ["voluntary"])
        self.assertEqual(clean["phase_in_columns"],
                         ["other_undertakings", "wave_one_above_threshold", "wave_one_below_threshold"])
        dp = by_id(mapping)["ESRS26_E1-8_02"]
        self.assertEqual(dp["ig3_mapping"], ["E1-6_02", "E1-6_03"])
        self.assertEqual(dp["ig3_reference"], {"standard": "E1", "dr": "E1-6", "paragraph": "44 c", "related": "AR 46"})
        self.assertNotIn("ig3_mapping", by_id(clean)["ESRS26_E1-8_02"])
        self.assertEqual([d["id"] for d in clean["datapoints"]], [d["id"] for d in mapping["datapoints"]])

    def test_header_variants(self):
        ix = parse.parse_workbook(VARIANTS)
        self.assertEqual(ix["layout"], "list")
        self.assertEqual(ix["sheets"][0]["header_row"], 5)
        dps = by_id(ix)
        self.assertEqual(sorted(dps), ["G1-1_01", "G1-1_01#2", "G1-1_02", "G1-1_03", "G1-3_01"])
        self.assertEqual(ix["duplicate_ids"], ["G1-1_01"])
        self.assertEqual((ix["rows_without_id"], ix["invalid_ids"]), (1, 1))
        # vertically merged DR cells belong to every row they span
        self.assertEqual([dps[i]["dr"] for i in ("G1-1_01", "G1-1_02", "G1-1_03")], ["G1-1"] * 3)
        self.assertEqual(dps["G1-1_02"]["paragraph"], "8")  # a numeric cell, not "8.0"
        self.assertEqual((dps["G1-1_02"]["voluntary"], dps["G1-1_01"]["voluntary"]), (True, False))
        self.assertEqual(dps["G1-1_03"]["standard"], "G1")
        self.assertIn("Ünïcödé", dps["G1-1_01"]["name"])
        self.assertEqual({s["sheet"] for s in ix["skipped_sheets"]}, {"Old copy", "Notes"})
        self.assertEqual(ix["columns_missing"], ["conditional", "eu_legislation", "phase_in"])

    def test_missing_columns_are_reported_not_fatal(self):
        p = xm.simple(self.tmp / "min.xlsx", [["ID", "Name"], ["E2-1_01", "Placeholder datapoint"]])
        ix = parse.parse_workbook(p)
        self.assertEqual(ix["columns_missing"], [c for c in parse.CORE_FIELDS if c != "name"])
        self.assertEqual(ix["datapoints"][0]["standard"], "E2")  # from the ID when no column says so
        self.assertNotIn("voluntary", ix["datapoints"][0])


class Fields(Isolated):
    def setUp(self):
        super().setUp()
        self.dps = by_id(parse.parse_workbook(IG3))

    def test_voluntary_phase_in_conditional_and_eu_legislation(self):
        d = self.dps["E1-6_03"]
        self.assertEqual((d["voluntary"], d["conditional"]), (True, "alternative"))
        self.assertEqual(d["phase_in"], {"under_750_employees": "1 year"})
        self.assertTrue(parse.subject_to_phase_in(d))
        self.assertEqual(self.dps["E1-6_01"]["eu_legislation"], ["SFDR", "Pillar 3", "Benchmark Regulation"])
        self.assertEqual(self.dps["E1-1_02"]["eu_legislation"], ["EU Climate Law"])
        self.assertEqual(self.dps["S1-6_02"]["eu_legislation"], ["SFDR", "Benchmark Regulation"])
        self.assertFalse(self.dps["MDR-P_01"]["voluntary"])  # a non-breaking space is empty

    def test_disclose_when_phasing_in_is_not_subject_to_phase_in(self):
        d = self.dps["SBM-3_01"]
        self.assertIn("disclose_when_using_phase_in", d["phase_in"])
        self.assertFalse(parse.subject_to_phase_in(d))

    def test_standard_comes_from_the_sheet_and_dr_is_trimmed(self):
        self.assertEqual(self.dps["E1.MDR-P_01-02"]["standard"], "E1")
        self.assertEqual(self.dps["MDR-P_01"]["standard"], "ESRS 2")
        self.assertEqual(self.dps["E1-6_01"]["dr"], "E1-6")

    def test_section_note_heads_the_rows_below(self):
        self.assertNotIn("section_note", self.dps["MDR-P_02"])
        self.assertIn("stated case", self.dps["MDR-P_07"]["section_note"])

    def test_header_classification(self):
        c = lambda h: parse.classify(parse.normalize_header(h))  # noqa: E731
        self.assertEqual(c("May \n[V]"), ("voluntary", None))
        self.assertEqual(c("Conditionality defined in a different paragraph"), ("condition_ref", None))
        self.assertEqual(c("Mapping with 2024 IG 3 (2023 ESRS ID)"), ("ig3_mapping", None))
        self.assertEqual(c("2023 ESRS DR"), ("ig3_dr", None))
        self.assertEqual(c("Phase-ins for 'Wave-one' undertakings NOT exceeding x"),
                         ("phase_in", "wave_one_below_threshold"))
        self.assertIsNone(c("Comment"))

    def test_standard_codes(self):
        for raw, want in (("ESRS E1", "E1"), ("e1", "E1"), ("ESRS 2 MDR", "ESRS 2"), ("2", "ESRS 2"),
                          ("Index", None), ("2023 data", None), ("E9", None)):
            self.assertEqual(parse.standard_code(raw), want, raw)
