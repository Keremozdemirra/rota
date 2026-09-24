"""check: the patterns that usually break models, and the ones that must not be flagged."""
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import NS, R_NS, Case, xlsx_review as xr  # noqa: E402


def found(path):
    return [(f["code"], f["sheet"], f["cell"]) for f in xr.check(xr.load(path))["findings"]]


def codes(path):
    return {f["code"] for f in xr.check(xr.load(path))["findings"]}


YEARS = {"A1": "Revenue", "B1": 100, "C1": "=B1*1.1", "D1": "=C1*1.1", "E1": "=D1*1.1", "F1": "=E1*1.1"}


class Patterns(Case):
    def test_hardcoded_number_in_a_row_of_formulas(self):
        cells = dict(YEARS, D1=133.1)
        self.assertIn(("hardcoded-value", "S", "D1"), found(self.book(sheets=[{"name": "S", "cells": cells}])))

    def test_hardcoded_number_at_the_end_of_a_run_and_in_a_column(self):
        cells = dict(YEARS, G1=180)
        self.assertIn(("hardcoded-value", "S", "G1"), found(self.book(sheets=[{"name": "S", "cells": cells}])))
        col = {f"C{r}": f"=A{r}*B{r}" for r in range(1, 8)}
        col["C4"] = 12
        self.assertIn(("hardcoded-value", "S", "C4"), found(self.book(sheets=[{"name": "S", "cells": col}])))

    def test_first_value_of_a_series_is_not_a_hardcode(self):
        self.assertNotIn("hardcoded-value", codes(self.book(sheets=[{"name": "S", "cells": YEARS}])))

    def test_inconsistent_formula_in_a_row(self):
        cells = dict(YEARS, D1="=C1*1.2")
        self.assertIn(("inconsistent-formula", "S", "D1"), found(self.book(sheets=[{"name": "S", "cells": cells}])))

    def test_two_odd_cells_side_by_side_are_both_found(self):
        cells = dict(YEARS, D1="=C1*1.2", E1="=D1*1.2")
        hits = [c for code, s, c in found(self.book(sheets=[{"name": "S", "cells": cells}])) if code == "inconsistent-formula"]
        self.assertEqual(hits, ["D1", "E1"])

    def test_statement_rows_that_share_a_shape_are_not_inconsistent(self):
        # Gross profit (=B2-B3) and EBITDA (=B4-B5) have one R1C1 shape; Opex between them is not odd.
        cells = {"B2": 100, "B3": "=B2*0.4", "B4": "=B2-B3", "B5": 30, "B6": "=B4-B5", "B7": "=B6*0.25"}
        self.assertEqual(codes(self.book(sheets=[{"name": "S", "cells": cells}])) & {"inconsistent-formula", "hardcoded-value"}, set())


class Errors(Case):
    def test_ref_error_error_values_and_missing_sheets(self):
        cells = {"A1": ("=SUM(#REF!,B1)", "#REF!"), "A2": ("=1/0", "#DIV/0!"), "A3": ("error", "#N/A"), "A4": "=Gone!A1"}
        f = found(self.book(sheets=[{"name": "S", "cells": cells}], names=[("Broken", "#REF!"), ("Lost", "Old!$A$1")]))
        self.assertIn(("ref-error", "S", "A1"), f)
        self.assertNotIn(("error-value", "S", "A1"), f)  # reported once, as ref-error
        self.assertIn(("error-value", "S", "A2"), f)
        self.assertIn(("error-value", "S", "A3"), f)
        self.assertIn(("missing-sheet-reference", "S", "A4"), f)
        self.assertIn(("ref-error-in-name", None, None), f)
        self.assertIn(("missing-sheet-reference", None, None), f)


class Links(Case):
    def test_external_link_is_reported_with_secrets_masked(self):
        secret = "tok" + "3n-" + "q" * 12
        target = f"https://analyst:{secret}@files.example.com/fx.xlsx?sig={secret}"
        wb = xr.load(self.book(sheets=[{"name": "S", "cells": {"A1": "=[1]Rates!B2*2"}}], links=[target]))
        result = xr.check(wb)
        link = [f for f in result["findings"] if f["code"] == "external-link"][0]
        self.assertEqual(link["details"]["formulas"], 1)
        for text in (xr.check_text(result, 50), xr.check_markdown(result, 50), str(xr.check_json(result, 50)), xr.textconv(wb)):
            self.assertNotIn(secret, text)
            self.assertIn("files.example.com", text)

    def test_dde_link(self):
        self.assertIn("dde-link", codes(self.book(links=[("dde", "cmd", "/c calc")])))


class Cycles(Case):
    def cycles(self, **kw):
        return [f for f in xr.check(xr.load(self.book(**kw)))["findings"] if f["code"] == "circular-reference"]

    def test_self_reference_through_a_range(self):
        c = self.cycles(sheets=[{"name": "S", "cells": {"A1": 1, "A2": 2, "A3": "=SUM(A1:A3)"}}])
        self.assertEqual([x["cell"] for x in c], ["A3"])

    def test_cycle_across_sheets_and_through_a_defined_name(self):
        c = self.cycles(sheets=[{"name": "Model", "cells": {"B2": "=Tax*2"}}, {"name": "Tax sheet", "cells": {"C3": "=Model!B2/2"}}],
                        names=[("Tax", "'Tax sheet'!$C$3")])
        self.assertEqual(len(c), 1)
        self.assertEqual(sorted(c[0]["details"]["cells"]), ["'Tax sheet'!C3", "Model!B2"])

    def test_cycle_through_a_3d_reference_and_whole_column(self):
        c = self.cycles(sheets=[{"name": "Jan", "cells": {"A1": "=SUM(C:C)"}}, {"name": "Feb", "cells": {"A1": 1}},
                                {"name": "Sum", "cells": {"C5": "=SUM(Jan:Feb!A1)"}}])
        self.assertEqual(len(c), 0)  # Sum!C5 reads Jan!A1, which reads Jan!C:C, not Sum!C:C
        c = self.cycles(sheets=[{"name": "Jan", "cells": {"A1": "=SUM(Sum!C:C)"}}, {"name": "Feb", "cells": {"A1": 1}},
                                {"name": "Sum", "cells": {"C5": "=SUM(Jan:Feb!A1)"}}])
        self.assertEqual(len(c), 1)

    def test_long_chains_and_running_totals_are_not_cycles(self):
        cells = {f"A{r}": f"=A{r - 1}+1" for r in range(2, 3000)}
        cells.update({f"B{r}": f"=SUM($A$2:A{r})" for r in range(2, 3000)})
        cells["A1"] = 1
        self.assertEqual(self.cycles(sheets=[{"name": "S", "cells": cells}]), [])

    def test_position_only_functions_do_not_make_cycles(self):
        self.assertEqual(self.cycles(sheets=[{"name": "S", "cells": {"A1": "=ROW(A1)+COLUMNS(A1:C1)"}}]), [])

    def test_iterative_calculation_is_noted(self):
        c = self.cycles(sheets=[{"name": "S", "cells": {"A1": "=A2", "A2": "=A1"}}], calc='<calcPr calcId="1" iterate="1"/>')
        self.assertTrue(c[0]["details"]["iterative_calculation"])


class Informational(Case):
    def test_volatile_hidden_structured_and_no_cache(self):
        cells = {"A1": '=INDIRECT("B1")+OFFSET(A2,1,0)+NOW()', "A2": "=Sales[Amount]*2"}
        result = xr.check(xr.load(self.book(sheets=[{"name": "S", "cells": cells}, {"name": "H", "state": "veryHidden"}])))
        info = {f["code"] for f in result["findings"] if f["severity"] == "info"}
        self.assertEqual(info, {"volatile-function", "very-hidden-sheet", "structured-reference", "no-cached-values"})
        vol = sorted(f["details"]["function"] for f in result["findings"] if f["code"] == "volatile-function")
        self.assertEqual(vol, ["INDIRECT", "NOW", "OFFSET"])


class LargeSheet(Case):
    """100,000 cells: 20,000 rows of a label, a number, two shared formulas and a running total over a
    growing range, plus a whole-column sum. Bounds are this tool's choice, generous for slow CI runners."""

    def build(self):
        rows = []
        n = 20000
        for r in range(2, n + 2):
            c = f'<c r="A{r}" t="inlineStr"><is><t>item {r}</t></is></c><c r="B{r}"><v>{r % 97}</v></c>'
            if r == 2:
                c += (f'<c r="C2"><f t="shared" ref="C2:C{n + 1}" si="0">B2*1.1</f><v>1</v></c>'
                      f'<c r="D2"><f t="shared" ref="D2:D{n + 1}" si="1">C2+B2</f><v>1</v></c>')
            else:
                c += f'<c r="C{r}"><f t="shared" si="0"/><v>1</v></c><c r="D{r}"><f t="shared" si="1"/><v>1</v></c>'
            c += f'<c r="E{r}"><f>SUM($D$2:D{r})</f><v>1</v></c>'
            rows.append(f'<row r="{r}">{c}</row>')
        rows.append(f'<row r="{n + 2}"><c r="F{n + 2}"><f>SUM(E:E)</f><v>1</v></c></row>')
        xml = f'<worksheet xmlns="{NS}" xmlns:r="{R_NS}"><sheetData>{"".join(rows)}</sheetData></worksheet>'
        return self.book("big.xlsx", sheets=[{"name": "Data", "xml": xml}])

    def test_time_and_memory(self):
        path = self.build()
        start = time.perf_counter()
        wb = xr.load(path)
        result = xr.check(wb)
        elapsed = time.perf_counter() - start
        self.assertEqual(sum(len(s.cells) for s in wb.sheets), 100001)
        self.assertEqual(xr.counts(result["findings"]), {"error": 0, "warning": 0, "info": 0})
        self.assertLess(elapsed, 30)
        tracemalloc.start()
        try:
            xr.check(xr.load(path))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 300 * 1024 * 1024)
