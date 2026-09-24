"""diff: what changed, which changes are risky, and what must not show up as a change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, Case, xlsx_review as xr  # noqa: E402


def run(before, after, **kw):
    return xr.diff(xr.load(before), xr.load(after), **kw)


def changes(result, sheet):
    for s in result["sheets"]:
        if s["sheet"] == sheet:
            return {(ch["cell"] or ch["before_cell"]): ch["kind"] for ch in s["changes"]}
    return {}


class AgentEdit(Case):
    """budget_before.xlsx -> budget_after.xlsx (tests/fixtures/make_fixtures.py describes the edit)."""

    def setUp(self):
        super().setUp()
        self.r = run(str(FIXTURES / "budget_before.xlsx"), str(FIXTURES / "budget_after.xlsx"))

    def test_workbook_changes(self):
        wbc = {(c["change"], c.get("name") or c.get("before") or c.get("sheet")) for c in self.r["workbook"]}
        self.assertIn(("sheet-renamed", "Summary"), wbc)
        self.assertIn(("name-changed", "TaxRate"), wbc)
        self.assertIn("link-added", {c["change"] for c in self.r["workbook"]})

    def test_inserted_row_is_found_and_shifted_cells_are_not_changes(self):
        model = [s for s in self.r["sheets"] if s["sheet"] == "Model"][0]
        self.assertEqual(model["rows_inserted"], [6])
        ch = changes(self.r, "Model")
        self.assertEqual(ch["F2"], "formula-to-value")
        self.assertEqual(ch["E3"], "formula-changed")
        self.assertEqual(ch["B7"], "formula-changed")      # EBITDA now subtracts the new row
        self.assertNotIn("B8", ch)                          # tax: references moved with the row, as Excel moves them
        self.assertNotIn("B11", ch)
        self.assertNotIn("B2", changes(self.r, "Dashboard"))

    def test_risks(self):
        risky = {(x["code"], x.get("cell")) for x in self.r["risks"]}
        self.assertIn(("formula-to-value", "F2"), risky)
        self.assertIn(("hardcoded-value", "F2"), risky)
        self.assertIn(("inconsistent-formula", "E3"), risky)
        self.assertIn(("circular-reference", "G8"), risky)
        self.assertIn(("external-link", None), risky)
        self.assertEqual(self.r["summary"]["errors"], 1)
        self.assertEqual(self.r["resolved_findings"], [])

    def test_without_alignment_every_row_below_the_insert_changes(self):
        r = run(str(FIXTURES / "budget_before.xlsx"), str(FIXTURES / "budget_after.xlsx"), align=False)
        self.assertGreater(r["summary"]["cells_changed"], self.r["summary"]["cells_changed"])


class OpenpyxlInsertRows(Case):
    def test_formulas_left_behind_by_insert_rows(self):
        r = run(str(FIXTURES / "budget_before.xlsx"), str(FIXTURES / "budget_after_insert_rows.xlsx"))
        stale = {(s["sheet"], ch["cell"]): ch for s in r["sheets"] for ch in s["changes"] if ch["kind"] == "stale-reference"}
        self.assertIn(("Summary", "B3"), stale)
        self.assertEqual(stale[("Summary", "B3")]["adjusted"], "=SUM(Model!B7:G7)")
        self.assertIn(("Model", "B9"), stale)
        self.assertNotIn(("Model", "B11"), stale)           # its references did not move


class Structural(Case):
    def test_identical_files(self):
        path = str(FIXTURES / "budget_before.xlsx")
        r = run(path, path)
        self.assertEqual((r["sheets"], r["workbook"], r["risks"]), ([], [], []))

    def test_renamed_sheet_references_follow_the_rename(self):
        b = self.book("b.xlsx", sheets=[{"name": "Data", "cells": {"A1": 5, "A2": 6}}, {"name": "Out", "cells": {"B1": "=Data!A1*2"}}])
        a = self.book("a.xlsx", sheets=[{"name": "Data 2026", "cells": {"A1": 5, "A2": 6}}, {"name": "Out", "cells": {"B1": "='Data 2026'!A1*2"}}])
        r = run(b, a)
        self.assertEqual(r["workbook"], [{"change": "sheet-renamed", "before": "Data", "after": "Data 2026"}])
        self.assertEqual(r["sheets"], [])

    def test_defined_name_added_removed_and_still_used(self):
        b = self.book("b.xlsx", sheets=[{"name": "S", "cells": {"A1": "=Rate*2", "B1": 0.1}}], names=[("Rate", "S!$B$1")])
        a = self.book("a.xlsx", sheets=[{"name": "S", "cells": {"A1": "=Rate*2", "B1": 0.1}}], names=[("Fx", "S!$B$1")])
        r = run(b, a)
        self.assertEqual({c["change"] for c in r["workbook"]}, {"name-removed", "name-added"})
        self.assertIn("name-removed-still-used", {x["code"] for x in r["risks"]})

    def test_emptied_cell_still_read_by_a_formula(self):
        b = self.book("b.xlsx", sheets=[{"name": "S", "cells": {"A1": 7, "B1": "=A1*2"}}])
        a = self.book("a.xlsx", sheets=[{"name": "S", "cells": {"B1": "=A1*2"}}])
        r = run(b, a)
        ch = r["sheets"][0]["changes"][0]
        self.assertEqual((ch["kind"], ch["risk"]), ("removed", "warning"))

    def test_deleted_column(self):
        b = self.book("b.xlsx", sheets=[{"name": "S", "cells": {"A1": "x", "B1": "old", "C1": 3, "D1": "=C1*2", "A2": 1, "B2": 2, "C2": 4, "D2": "=C2*2"}}])
        a = self.book("a.xlsx", sheets=[{"name": "S", "cells": {"A1": "x", "B1": 3, "C1": "=B1*2", "A2": 1, "B2": 4, "C2": "=B2*2"}}])
        s = run(b, a)["sheets"][0]
        self.assertEqual(s["columns_deleted"], [2])
        self.assertEqual({ch["kind"] for ch in s["changes"]}, {"removed"})

    def test_hidden_sheet_vba_and_cached_values(self):
        b = self.book("b.xlsx", sheets=[{"name": "S", "cells": {"A1": ("=2*3", 6)}}, {"name": "T"}])
        a = self.book("a.xlsm", sheets=[{"name": "S", "cells": {"A1": ("=2*3", 7)}}, {"name": "T", "state": "hidden"}], vba=b"x")
        r = run(b, a)
        self.assertIn({"change": "sheet-state", "sheet": "T", "before": "visible", "after": "hidden"}, r["workbook"])
        self.assertIn("vba-added", {x["code"] for x in r["risks"]})
        self.assertEqual(r["sheets"][0]["cached_values_changed"], 1)
