"""Matching: rounding, percentages, scale, units from labels, ambiguity, signs and qualifiers."""
import unittest
from decimal import Decimal

from tests.support import IsolatedTestCase, S, cell, kept, sheet_xml, tieout, xlsx


def cells(*values, sheet="Model"):
    out = []
    for i, v in enumerate(values, 1):
        c = tieout.Cell("model.xlsx", sheet, f"B{i}", i, 2, tieout.excel15(Decimal(str(v))))
        c.order = i
        out.append(c)
    return out


def tie(text, source_cells, locale="en", **kw):
    n = kept(text, locale, **kw)[0]
    tieout.match_number(n, tieout.Index(source_cells))
    return n


class Rounding(IsolatedTestCase):
    def test_percentage_of_a_fraction(self):
        n = tie("61% of revenue", cells(0.6134))
        self.assertEqual(n.status, "tied")
        self.assertEqual(n.candidates[0]["how"], "percentage")
        self.assertIn("0.6134 × 100 = 61.34, rounds to 61", n.candidates[0]["detail"])

    def test_rounding_edge_61_not_62(self):
        self.assertEqual(tie("61%", cells(0.6149)).status, "tied")
        n = tie("62%", cells(0.6149))
        self.assertEqual(n.status, "untied")
        self.assertEqual(n.nearest["cell"].cell, "B1")
        self.assertIn("rounds to 61", n.nearest["detail"])
        self.assertEqual(tie("61.5%", cells(0.6149)).status, "tied")

    def test_half_up_and_half_even_both_tie(self):
        self.assertEqual(tie("63%", cells(0.625)).status, "tied")
        n = tie("62%", cells(0.625))
        self.assertEqual(n.status, "tied")
        self.assertIn("half-even", n.candidates[0]["detail"])
        self.assertEqual(tie("64%", cells(0.625)).status, "untied")

    def test_source_read_at_fifteen_significant_digits(self):
        noisy = tieout.excel15(Decimal("2.6749999999999998"))
        self.assertEqual(noisy, Decimal("2.675"))
        c = tieout.Cell("m.xlsx", "S", "A1", 1, 1, noisy)
        self.assertEqual(tie("2.68", [c]).status, "tied")
        self.assertEqual(tie("2.67", [c]).status, "untied")

    def test_written_precision_is_respected(self):
        self.assertEqual(tie("4.20bn", cells(4213500000)).status, "untied")
        self.assertEqual(tie("4.21bn", cells(4213500000)).status, "tied")
        self.assertEqual(tie("4bn", cells(4213500000)).status, "tied")

    def test_exact(self):
        n = tie("4,213,500,000", cells(4213500000))
        self.assertEqual((n.status, n.candidates[0]["how"], n.candidates[0]["exact"]), ("tied", "exact", True))
        self.assertEqual(tie("1.8x", cells(1.7549724218619422)).candidates[0]["how"], "rounded")


class Scale(IsolatedTestCase):
    def test_scale_word(self):
        n = tie("€4.2bn", cells(4213500000))
        self.assertEqual((n.status, n.candidates[0]["how"]), ("tied", "scaled"))
        self.assertIn("÷ 1,000,000,000 = 4.2135", n.candidates[0]["detail"])

    def test_scale_is_not_guessed_for_unlabelled_sources(self):
        self.assertEqual(tie("€4.2bn", cells(4.2135)).status, "untied")

    def test_source_unit_option(self):
        src = self.path("m.csv")
        with open(src, "w", encoding="utf-8") as f:
            f.write("Metric,Value\nRevenue,4213.5\nHeadcount,1310\n")
        plain = tieout.read_source(src, [])
        self.assertEqual(tie("€4.2bn", plain.cells).status, "untied")
        both = tieout.read_source(src, [6])
        n = tie("€4.2bn", both.cells)
        self.assertEqual(n.status, "tied")
        self.assertIn("--source-unit million", n.candidates[0]["detail"])
        self.assertEqual(tie("1,310 staff", both.cells).status, "tied")

    def test_unit_from_a_source_label(self):
        src = self.path("m.xlsx")
        xlsx(src, [("P&L", sheet_xml([
            (1, [cell("A1", t="inlineStr", inline="Metric"), cell("B1", t="inlineStr", inline="2025 (€m)")]),
            (2, [cell("A2", t="inlineStr", inline="Revenue"), cell("B2", 4213.5)]),
            (3, [cell("A3", t="inlineStr", inline="EBITDA (EUR bn)"), cell("B3", 0.5983)]),
        ]))])
        got = tieout.read_source(src, [])
        n = tie("€4.2bn", got.cells)
        self.assertEqual(n.status, "tied")
        self.assertIn("column header '2025 (€m)'", n.candidates[0]["detail"])
        n = tie("EBITDA of €598m", got.cells)
        self.assertEqual(n.status, "tied")
        self.assertIn("row label 'EBITDA (EUR bn)'", n.candidates[0]["detail"])
        self.assertEqual(tie("4,213,500,000", got.cells).status, "tied")

    def test_unit_from_a_deliverable_table_label(self):
        n = tie("4,214", cells(4213500000), table=True, labels=[("caption", "Key figures (€m)")])
        self.assertEqual((n.status, n.scale_exp, n.soft_scale), ("tied", 6, True))
        n = tie("1,310", cells(1310), table=True, labels=[("caption", "Key figures (€m)")])
        self.assertEqual(n.status, "tied")
        n = tie("14.2", cells(0.141996), table=True, labels=[("row label", "EBITDA margin (%)")])
        self.assertEqual((n.status, n.unit), ("tied", "%"))

    def test_basis_points_and_per_mille(self):
        self.assertEqual(tie("150bps", cells(0.015)).status, "tied")
        self.assertEqual(tie("2‰", cells(0.002)).status, "tied")

    def test_percent_units_in_the_source(self):
        n = tie("61%", cells(61.34))
        self.assertEqual((n.status, n.candidates[0]["how"]), ("tied", "rounded"))


class Ambiguity(IsolatedTestCase):
    def test_different_values_are_ambiguous(self):
        n = tie("around 14%", cells(0.1396, 0.1420, 0.1440))
        self.assertEqual(n.status, "ambiguous")
        self.assertEqual(n.candidate_count, 3)
        self.assertIn("3 different source values", n.notes[-1])

    def test_one_value_in_a_few_cells_is_tied(self):
        n = tie("€4.2bn", cells(4213500000, 4213500000))
        self.assertEqual((n.status, n.candidate_count), ("tied", 2))

    def test_one_value_in_many_cells_is_ambiguous(self):
        self.assertEqual(tie("7 sites", cells(*[7] * 5)).status, "tied")
        n = tie("7 sites", cells(*[7] * 6))
        self.assertEqual(n.status, "ambiguous")
        self.assertIn("6 cells hold the value", n.notes[-1])

    def test_same_value_in_different_units_is_one_value(self):
        n = tie("61%", cells(0.6134, 61.34))
        self.assertEqual((n.status, n.candidate_count), ("tied", 2))


class Signs(IsolatedTestCase):
    def test_negative_ties_to_negative(self):
        n = tie("(1,234)", cells(1234, -1234), table=True)
        self.assertEqual((n.status, n.candidate_count), ("tied", 1))
        self.assertFalse(n.candidates[0].get("sign_differs"))

    def test_sign_convention_differs(self):
        n = tie("(1,234)", cells(1234), table=True)
        self.assertEqual(n.status, "tied")
        self.assertTrue(n.candidates[0]["sign_differs"])
        self.assertIn("sign differs", n.candidates[0]["detail"])

    def test_minus_percent(self):
        self.assertEqual(tie("-5.0%", cells(-0.05)).status, "tied")


class Qualifiers(IsolatedTestCase):
    def test_approximate_round_number(self):
        self.assertEqual(tie("about 1,300 staff", cells(1310)).status, "tied")
        self.assertEqual(tie("1,300 staff", cells(1310)).status, "untied")
        self.assertEqual(tie("around 62%", cells(0.6149)).status, "untied")

    def test_bounds(self):
        self.assertEqual(tie("more than 60%", cells(0.6134)).status, "tied")
        self.assertEqual(tie("more than 60%", cells(0.5990)).status, "untied")
        self.assertEqual(tie("up to €5bn", cells(4600000000)).status, "tied")
        self.assertEqual(tie("up to €5bn", cells(5200000000)).status, "untied")


class Nearest(IsolatedTestCase):
    def test_nearest_within_ten_percent(self):
        n = tie("€612m", cells(598300000))
        self.assertEqual(n.status, "untied")
        self.assertEqual(n.nearest["difference"], -2.24)

    def test_nothing_near(self):
        n = tie("1,500 staff", cells(1310))
        self.assertEqual((n.status, n.nearest), ("untied", None))

    def test_empty_sources(self):
        n = tie("1,500 staff", [])
        self.assertEqual((n.status, n.nearest), ("untied", None))


if __name__ == "__main__":
    unittest.main()
