import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import annex, countries, legal, lookup, xhtml  # noqa: E402

LQ, RQ = chr(0x2018), chr(0x2019)


class NormalizeCn(unittest.TestCase):
    def test_same_code_many_spellings(self):
        for raw in ("1801 00 00", "18010000", "1801.00.00", "1801-00-00", "CN 1801 00 00", "cn:1801.00.00",
                    " 1801 00 00 ", "1801" + chr(0xA0) + "00" + chr(0xA0) + "00", "\uff11\uff18\uff10\uff11\uff10\uff10\uff10\uff10"):
            with self.subTest(raw=raw):
                self.assertEqual(lookup.normalize_cn(raw)[0], "18010000")

    def test_prefix_lengths(self):
        self.assertEqual(lookup.normalize_cn("18")[0], "18")
        self.assertEqual(lookup.normalize_cn("1801")[0], "1801")
        self.assertEqual(lookup.normalize_cn("1801 00")[0], "180100")

    def test_taric_code_uses_first_eight_digits(self):
        digits, notes = lookup.normalize_cn("1801 00 00 10")
        self.assertEqual(digits, "18010000")
        self.assertTrue(any("TARIC" in n for n in notes))

    def test_ex_prefix_is_ignored_with_a_note(self):
        digits, notes = lookup.normalize_cn("ex 0201")
        self.assertEqual(digits, "0201")
        self.assertTrue(any("'ex'" in n for n in notes))

    def test_integer_restores_leading_zero(self):
        digits, notes = lookup.normalize_cn(1022100)
        self.assertEqual(digits, "01022100")
        self.assertTrue(notes)

    def test_rejects(self):
        for bad in ("", "   ", "180", "1801000", "18O1", "1801;rm -rf", "x" * 41, None, True, 3.5, [],
                    "\u0661\u0668\u0660\u0661", "12345678901234"):
            with self.subTest(bad=bad), self.assertRaises(lookup.InputError):
                lookup.normalize_cn(bad)

    def test_error_message_does_not_echo_control_characters(self):
        with self.assertRaises(lookup.InputError) as ctx:
            lookup.normalize_cn("18\x1b[31m01")
        self.assertNotIn("\x1b", str(ctx.exception))


class EntryLines(unittest.TestCase):
    def test_codes_notes_and_continuation(self):
        lines = ["4415  Packing cases, of wood; pallets, of wood;", "pallet collars of wood",
                 "(not including packing material used exclusively as packing material)",
                 "0102 21 , 0102 29  Live cattle",
                 "ex 9403 30 , ex 9403 40  and ex 9403 91  Wooden furniture, and parts thereof",
                 "Pulp and paper of Chapters 47 and 48 of the Combined Nomenclature, with the exception of bamboo-based"]
        e = annex.parse_entry_lines(lines, "Wood")
        self.assertEqual(e[0]["description"], "Packing cases, of wood; pallets, of wood; pallet collars of wood")
        self.assertEqual(len(e[0]["notes"]), 1)
        self.assertEqual([c["code"] for c in e[1]["codes"]], ["010221", "010229"])
        self.assertEqual([(c["code"], c["ex"]) for c in e[2]["codes"]],
                         [("940330", True), ("940340", True), ("940391", True)])
        self.assertEqual([c["code"] for c in e[3]["codes"]], ["47", "48"])

    def test_deferred_date_after_closing_quote(self):
        # Point (6)(g) of 2026/2102 puts the date line after the closing quote.
        e = annex.parse_entry_lines([LQ + "ex 1520 00  Crude glycerol" + RQ + ";",
                                     "(This provision shall apply from 30 December 2027)"], "Oil palm")
        self.assertEqual(e[0]["applies_from"], "2027-12-30")
        self.assertEqual(e[0]["description"], "Crude glycerol")

    def test_number_after_a_code_is_not_part_of_it(self):
        self.assertIsNone(annex.split_codes("2905 45 95 % or more"))

    def test_leaked_footnote_is_rejected(self):
        with self.assertRaises(annex.AnnexError):
            annex.parse_entry_lines(["ex 1520 00  Crude glycerol", "Directive 2001/83/EC (OJ L 311, 28.11.2001, p. 67)"], "Oil palm")

    def test_text_before_any_entry(self):
        with self.assertRaises(annex.AnnexError):
            annex.parse_entry_lines(["(not including waste)"], "Cocoa")


class MalformedDocuments(unittest.TestCase):
    def test_no_annex(self):
        root = xhtml.parse("<html><body><p>nothing</p></body></html>")
        with self.assertRaises(annex.AnnexError):
            annex.parse_consolidated_annex(root)

    def test_annex_without_a_commodity_row(self):
        text = (support.FIXTURES / "cons_02023R1115-20251226.xhtml").read_text(encoding="utf-8")
        text = text.replace('<p class="tbl-norm">Coffee</p>', '<p class="tbl-norm">Tea</p>')
        with self.assertRaises(annex.AnnexError):
            annex.parse_consolidated_annex(xhtml.parse(text))

    def test_unbalanced_markup_does_not_raise_in_the_tree_builder(self):
        root = xhtml.parse("<div id='anx_I'><table><tr><td>Cattle<td><p>0102 Live cattle</div></body>")
        self.assertIsNotNone(root.find_id("anx_I"))

    def test_article_missing(self):
        with self.assertRaises(legal.LegalTextError):
            legal.article_lines(xhtml.parse("<html></html>"), "38")

    def test_article_38_without_a_date(self):
        paras = {"1": "This Regulation shall enter into force on the twentieth day following that of its publication",
                 "2": "Subject to paragraph 3 of this Article, Articles 3 to 13 shall apply from a date to be fixed.",
                 "3": "Except as regards ..., established as such by 31 December 2024, shall apply from 30 June 2027."}
        with self.assertRaises(legal.LegalTextError):
            legal.read_article_38(paras)

    def test_unknown_entry_into_force_rule(self):
        with self.assertRaises(legal.LegalTextError):
            legal.entry_into_force("shall enter into force on the fifth day following that of its publication",
                                   "2026-01-01")


class Instructions(unittest.TestCase):
    def setUp(self):
        self.base = annex.parse_consolidated_annex(xhtml.parse(
            (support.FIXTURES / "cons_02023R1115-20251226.xhtml").read_text(encoding="utf-8")))["entries"]
        for i, e in enumerate(self.base, 1):
            e.update({"id": f"B{i:02d}", "valid_from": None, "valid_to": None,
                      "source": {"celex": "02023R1115-20251226", "provision": "Annex I"}})

    def op(self, instruction, content=()):
        points = [annex.Point("(6)", ["the column " + LQ + "Relevant products" + RQ + " is amended as follows:"],
                              [annex.Point("(a)", [instruction] + list(content), [])])]
        return annex.parse_instructions(points)

    def test_unknown_instruction_wording(self):
        with self.assertRaises(annex.AnnexError):
            self.op("the entry " + LQ + "1801 Cocoa beans" + RQ + " is moved to the end of the table;")

    def test_target_that_matches_no_entry(self):
        ops = self.op("the entry " + LQ + "1809 Cocoa beans, whole or broken, raw or roasted" + RQ + " is deleted;")
        with self.assertRaises(annex.AnnexError):
            annex.apply_instructions(self.base, ops, {"celex": "32026R2102"}, "2026-09-18")

    def test_target_with_the_right_code_but_other_text(self):
        ops = self.op("the entry " + LQ + "1801 Roasted coffee substitutes of chicory" + RQ + " is deleted;")
        with self.assertRaises(annex.AnnexError):
            annex.apply_instructions(self.base, ops, {"celex": "32026R2102"}, "2026-09-18")

    def test_replacement_keeps_history(self):
        ops = self.op("the entry " + LQ + "1201 Soya beans, whether or not broken" + RQ
                      + " is deleted and replaced by the following:",
                      [LQ + "1201 90 00  Soya beans, whether or not broken: other" + RQ + ";"])
        entries, _, log = annex.apply_instructions(self.base, ops, {"celex": "32026R2102"}, "2026-09-18")
        old = next(e for e in entries if e["label"] == "1201")
        new = next(e for e in entries if e["label"] == "1201 90 00")
        self.assertEqual(old["valid_to"], "2026-09-17")
        self.assertEqual(new["valid_from"], "2026-09-18")
        self.assertEqual(new["replaces"], [old["id"]])
        self.assertEqual(log[0]["action"], "replace")


class CountryNames(unittest.TestCase):
    def setUp(self):
        rows = [{k: v["value"] for k, v in b.items()} for b in support.load("sparql_nal.json")["results"]["bindings"]]
        alts = [{k: v["value"] for k, v in b.items()} for b in support.load("sparql_nal_alt.json")["results"]["bindings"]]
        self.countries = countries.build_countries(rows, alts)

    def test_deprecated_and_codeless_entries_are_dropped(self):
        iso3 = {c["iso3"] for c in self.countries}
        self.assertNotIn("YUG", iso3)
        self.assertFalse(any(c["iso2"] in ("EU", "IC") for c in self.countries))

    def test_annex_spellings(self):
        mapped = dict((n, iso3) for n, iso3, _ in countries.map_annex_names(
            ["Vietnam", "Iran (Islamic Republic of)", "Netherlands (Kingdom of the)", "Solomon Island",
             "T\u00fcrkiye", "Democratic People\u2019s Republic of Korea"], self.countries))
        self.assertEqual(mapped, {"Vietnam": "VNM", "Iran (Islamic Republic of)": "IRN",
                                  "Netherlands (Kingdom of the)": "NLD", "Solomon Island": "SLB",
                                  "T\u00fcrkiye": "TUR", "Democratic People\u2019s Republic of Korea": "PRK"})

    def test_unknown_annex_name_stops_the_refresh(self):
        with self.assertRaises(countries.CountryError):
            countries.map_annex_names(["Atlantis"], self.countries)

    def test_name_list_with_an_empty_item(self):
        with self.assertRaises(countries.CountryError):
            countries.split_names("Austria, , China.")


if __name__ == "__main__":
    unittest.main()
