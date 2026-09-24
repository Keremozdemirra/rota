"""The formula tokenizer: references (ECMA-376 §18.17.2.3), shifting copies, R1C1 patterns."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Case, xlsx_review as xr  # noqa: E402


def refs(formula):
    return [(r.kind, r.book, r.sheet, r.sheet2, xr.ref_body_a1(r)) for k, t, r in xr.tokenize(formula) if k == "ref"]


def kinds(formula):
    return [(k, t) for k, t, r in xr.tokenize(formula) if k != "ws"]


class Tokens(Case):
    def test_round_trip_is_exact(self):
        for f in ("SUM( A1:B2 )*$C$3", "'My Sheet'!A1&\"x\"\"y\"", "IF(A1>0,1:3,A:A)", "{1,2;3,4}", "Table1[[#This Row],[Amt]]",
                  "_xlfn.XLOOKUP(A1,B:B,C:C)", "A1 B2", "unterminated \"text", "=weird ¤ chars"):
            self.assertEqual(xr.render(xr.tokenize(f)), f)

    def test_cells_ranges_whole_rows_and_columns(self):
        self.assertEqual(refs("A1+$B$2+C$3+$D4"), [("cell", None, None, None, "A1"), ("cell", None, None, None, "$B$2"),
                                                  ("cell", None, None, None, "C$3"), ("cell", None, None, None, "$D4")])
        self.assertEqual(refs("SUM(A1:B2,C:C,$3:$5)"), [("area", None, None, None, "A1:B2"), ("cols", None, None, None, "C:C"),
                                                      ("rows", None, None, None, "$3:$5")])

    def test_sheet_prefixes(self):
        self.assertEqual(refs("'My Sheet'!A1+'Bob''s'!B2+Übersicht!C3+売上!D4"),
                         [("cell", None, "My Sheet", None, "A1"), ("cell", None, "Bob's", None, "B2"),
                          ("cell", None, "Übersicht", None, "C3"), ("cell", None, "売上", None, "D4")])
        self.assertEqual(refs("SUM(Jan:Mar!B5)"), [("cell", None, "Jan", "Mar", "B5")])

    def test_external_references(self):
        self.assertEqual(refs("[1]Sheet1!$A$1:$A$3"), [("area", "1", "Sheet1", None, "$A$1:$A$3")])
        self.assertEqual(refs("'[2]Rates 2026'!B2"), [("cell", "2", "Rates 2026", None, "B2")])
        self.assertEqual(refs("[1]!Name"), [("name", "1", None, None, "Name")])

    def test_names_functions_and_lookalikes(self):
        k = kinds("LOG10(A1)+TAX2023+ABC123XYZ+XFE1+Growth+TRUE")
        self.assertIn(("func", "LOG10"), k)
        self.assertIn(("ref", "TAX2023"), k)          # column TAX exists, so this is a cell (Excel forbids such names)
        self.assertIn(("name", "ABC123XYZ"), k)
        self.assertIn(("name", "XFE1"), k)            # column XFE is past XFD: not a cell
        self.assertIn(("name", "Growth"), k)
        self.assertIn(("bool", "TRUE"), k)

    def test_errors_and_structured_references(self):
        self.assertEqual(kinds("SUM(#REF!)")[2], ("err", "#REF!"))
        self.assertEqual(refs("Sheet1!#REF!"), [("error", None, "Sheet1", None, "#REF!")])
        self.assertEqual([k for k, t in kinds("Sales[Amount]*[@Price]")], ["struct", "op", "struct"])


class Shift(Case):
    def shifted(self, formula, dr, dc):
        return xr.shifted_formula(xr.tokenize(formula), dr, dc)

    def test_relative_parts_move_absolute_parts_stay(self):
        self.assertEqual(self.shifted("A2*B2+$C$1+D$1+$E2", 3, 1), "B5*C5+$C$1+E$1+$E5")

    def test_ranges_columns_rows_and_other_sheets(self):
        self.assertEqual(self.shifted("SUM($C$2:C2)+SUM(A:B)+SUM(2:3)+'My Sheet'!A1", 2, 1),
                         "SUM($C$2:C4)+SUM(B:C)+SUM(4:5)+'My Sheet'!B3")

    def test_strings_names_and_functions_do_not_move(self):
        self.assertEqual(self.shifted('IF(A1="A1",Growth,LOG10(A1))', 1, 0), 'IF(A2="A1",Growth,LOG10(A2))')

    def test_falling_off_the_grid_is_ref_error(self):
        self.assertEqual(self.shifted("A1+B2", -1, 0), "#REF!+B1")


class R1C1(Case):
    def r1c1(self, formula, r, c):
        return xr.canonical(xr.tokenize(formula), lambda ref: xr.ref_r1c1(ref, r, c))

    def test_copies_of_one_formula_are_equal(self):
        self.assertEqual(self.r1c1("B2*(1+Growth)", 2, 3), self.r1c1("C2*(1+growth)", 2, 4))
        self.assertEqual(self.r1c1("SUM($C$2:C2)", 2, 4), self.r1c1("SUM($C$2:C9)", 9, 4))

    def test_different_formulas_differ(self):
        self.assertNotEqual(self.r1c1("B2*1.1", 2, 3), self.r1c1("B2*1.2", 2, 3))
        self.assertNotEqual(self.r1c1("B2", 2, 3), self.r1c1("B1", 2, 3))

    def test_spaces_that_separate_tokens_are_ignored_but_intersection_is_kept(self):
        self.assertEqual(self.r1c1("SUM( A1 , B1 )", 5, 5), self.r1c1("SUM(A1,B1)", 5, 5))
        self.assertNotEqual(self.r1c1("SUM(A1:A5 B1:B5)", 5, 5), self.r1c1("SUM(A1:A5B1:B5)", 5, 5))
