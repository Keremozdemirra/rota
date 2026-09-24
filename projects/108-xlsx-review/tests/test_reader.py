"""Reading packages: shared formulas as Excel writes them, and the ways real files go wrong."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import FIXTURES, NS, R_NS, Case, sheet_xml, workbook, xlsx_review as xr  # noqa: E402


def formula(wb, sheet, addr):
    cell = wb.sheet(sheet).cells.get(xr.parse_cell(addr))
    return None if cell is None else cell.formula


class SharedFormulas(Case):
    """tests/fixtures/excel_shared_formulas.xlsx, written by make_handmade.py after ECMA-376 §18.3.1.40."""

    def setUp(self):
        super().setUp()
        self.wb = xr.load(str(FIXTURES / "excel_shared_formulas.xlsx"))

    def test_followers_take_the_master_formula_shifted(self):
        self.assertEqual(formula(self.wb, "Calc", "C3"), "A3*B3")
        self.assertEqual(formula(self.wb, "Calc", "C6"), "A6*B6")
        self.assertEqual(formula(self.wb, "Calc", "D6"), "SUM($C$2:C6)")
        self.assertEqual(formula(self.wb, "Calc", "E4"), "C4/$D$6")
        self.assertEqual(formula(self.wb, "Calc", "G5"), "C5*F$1")

    def test_horizontal_and_two_dimensional_groups(self):
        self.assertEqual(formula(self.wb, "Calc", "E8"), "SUM(E2:E6)")
        self.assertEqual(formula(self.wb, "Calc", "I4"), "B4+$B4+Other!B3")

    def test_group_index_is_per_sheet(self):
        self.assertEqual(formula(self.wb, "Other", "D5"), "Calc!C6*2")

    def test_cell_with_its_own_formula_inside_the_range_keeps_it(self):
        self.assertEqual(formula(self.wb, "Calc", "C5"), "A5*B5+1")
        codes = [(f["code"], f["cell"]) for f in xr.check(self.wb)["findings"]]
        self.assertIn(("inconsistent-formula", "C5"), codes)

    def test_array_members_are_results_not_constants(self):
        cell = self.wb.sheet("Calc").cells[xr.parse_cell("J3")]
        self.assertEqual((cell.formula, cell.member, cell.value), (None, (2, 10), 20.0))
        self.assertNotIn("hardcoded-value", [f["code"] for f in xr.check(self.wb)["findings"]])

    def test_follower_before_its_master_and_group_without_master(self):
        xml = (f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="B1"><f t="shared" si="7"/><v>1</v></c>'
               '<c r="C1"><f t="shared" ref="C1:C1" si="9"/></c></row>'
               '<row r="2"><c r="B2"><f t="shared" ref="B1:B2" si="7">A2*2</f><v>2</v></c></row></sheetData></worksheet>')
        wb = xr.load(self.book(sheets=[{"name": "S", "xml": xml}]))
        self.assertEqual(formula(wb, "S", "B1"), "A1*2")
        self.assertTrue(wb.sheet("S").cells[(1, 3)].orphan)
        self.assertTrue(any("no master" in m for _, m in wb.problems))


class Values(Case):
    def test_shared_inline_rich_and_phonetic_strings(self):
        xml = (f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
               '<c r="B1" t="inlineStr"><is><r><t>Net </t></r><r><t>income</t></r></is></c>'
               '<c r="C1" t="s"><v>1</v></c><c r="D1" t="b"><v>1</v></c><c r="E1" t="e"><v>#N/A</v></c></row></sheetData></worksheet>')
        sst = (f'<sst xmlns="{NS}"><si><t>Line_x000D_feed</t></si><si><r><t>東京</t></r><rPh sb="0" eb="2"><t>トウキョウ</t></rPh></si></sst>').encode()
        wb = xr.load(self.book(sheets=[{"name": "S", "xml": xml}], replace={"xl/sharedStrings.xml": sst}))
        cells = wb.sheet("S").cells
        self.assertEqual([cells[(1, c)].value for c in range(1, 6)], ["Line\rfeed", "Net income", "東京", True, "#N/A"])

    def test_cells_without_r_attributes_follow_each_other(self):
        xml = f'<worksheet xmlns="{NS}"><sheetData><row><c><v>1</v></c><c><v>2</v></c></row><row><c><f>A1+B1</f></c></row></sheetData></worksheet>'
        wb = xr.load(self.book(sheets=[{"name": "S", "xml": xml}]))
        self.assertEqual(sorted(wb.sheet("S").cells), [(1, 1), (1, 2), (2, 1)])

    def test_missing_shared_strings_part(self):
        path = self.book(sheets=[{"name": "S", "cells": {"A1": "label", "B1": 3}}], drop=("xl/sharedStrings.xml",))
        wb = xr.load(path)
        self.assertIsNone(wb.sheet("S").cells[(1, 1)].value)
        self.assertEqual(wb.missing_strings, 1)
        self.assertIn("missing-shared-strings", [f["code"] for f in xr.check(wb)["findings"]])
        self.assertIn("(missing shared string)", xr.textconv(wb))


class SheetNames(Case):
    """Sheet names beyond ASCII, in parts that are not UTF-8 encoded."""

    def names_xml(self, encoding, names):
        tags = "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
        return (f'<?xml version="1.0" encoding="{encoding}"?>\n<workbook xmlns="{NS}" xmlns:r="{R_NS}"><sheets>{tags}</sheets>'
                "</workbook>").encode(encoding)

    def test_utf16_workbook_part(self):
        names = ["Übersicht 2026", "売上"]
        path = self.book(sheets=[{"name": "a", "cells": {"A1": 1}}, {"name": "b", "cells": {"A1": "=Übersicht!A1*2"}}],
                         workbook_xml=self.names_xml("UTF-16", names))
        wb = xr.load(path)
        self.assertEqual([s.name for s in wb.sheets], names)
        self.assertEqual(xr.check(wb)["findings"][0]["code"], "missing-sheet-reference")  # the formula names the old sheet

    def test_latin1_declared_workbook_part(self):
        path = self.book(sheets=[{"name": "a", "cells": {"A1": 1}}], workbook_xml=self.names_xml("ISO-8859-1", ["Bilanz März"]))
        self.assertEqual(xr.load(path).sheets[0].name, "Bilanz März")

    def test_bytes_that_are_not_utf8_are_an_error_not_a_traceback(self):
        bad = self.names_xml("UTF-8", ["Bilanz"]).replace(b"Bilanz", b"Bilanz M\xe4rz")
        with self.assertRaises(xr.WorkbookError) as ctx:
            xr.load(self.book(workbook_xml=bad))
        self.assertIn("not well-formed", str(ctx.exception))

    def test_percent_encoded_and_differently_cased_part_names(self):
        rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                'Target="Worksheets/%C3%9Cbersicht.XML"/></Relationships>').encode()
        path = self.book(sheets=[{"name": "Übersicht", "cells": {"A1": 7}}], replace={"xl/_rels/workbook.xml.rels": rels},
                         extra_parts={"xl/worksheets/Übersicht.xml": sheet_xml({"A1": 7}).encode()})
        self.assertEqual(xr.load(path).sheets[0].cells[(1, 1)].value, 7.0)


class Broken(Case):
    def test_not_a_zip(self):
        with self.assertRaisesRegex(xr.WorkbookError, "not a zip"):
            xr.load(self.write("x.xlsx", b"PK\x03\x04 but not really a zip"))

    def test_truncated_zip(self):
        data = workbook()
        with self.assertRaises(xr.WorkbookError):
            xr.load(self.write("t.xlsx", data[: len(data) // 2]))

    def test_legacy_or_encrypted_ole_file(self):
        with self.assertRaisesRegex(xr.WorkbookError, "OLE compound file"):
            xr.load(self.write("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504))

    def test_missing_file_and_directory(self):
        with self.assertRaisesRegex(xr.WorkbookError, "file not found"):
            xr.load(str(self.tmp / "nope.xlsx"))
        with self.assertRaisesRegex(xr.WorkbookError, "not a regular file"):
            xr.load(str(self.tmp))

    def test_zip_without_workbook_and_xlsb(self):
        with self.assertRaisesRegex(xr.WorkbookError, "no workbook part"):
            xr.load(self.write("e.xlsx", workbook(drop=("xl/workbook.xml",))))
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.bin"/>'
                "</Relationships>").encode()
        with self.assertRaisesRegex(xr.WorkbookError, "xlsb"):
            xr.load(self.write("b.xlsb", workbook(replace={"_rels/.rels": rels})))

    def test_corrupt_sheet_part_is_reported_and_the_rest_is_read(self):
        data = bytearray(workbook(sheets=[{"name": "Good", "cells": {"A1": 1}}, {"name": "Bad", "cells": {"A1": 2}}]))
        path = self.write("c.xlsx", bytes(data))
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("xl/worksheets/sheet2.xml")
        start = info.header_offset + 30 + len(info.filename) + len(info.extra)
        data[start + 5] ^= 0xFF  # damage the compressed bytes of one part: a CRC or inflate error
        path = self.write("c.xlsx", bytes(data))
        wb = xr.load(path)
        self.assertEqual(wb.sheet("Good").cells[(1, 1)].value, 1.0)
        self.assertTrue(wb.sheet("Bad").problem)
        self.assertTrue(wb.problems)

    def test_dtd_is_refused_before_parsing(self):
        bomb = (f'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is></c></row>'
                "</sheetData></worksheet>")
        wb = xr.load(self.book(sheets=[{"name": "S", "xml": bomb}]))
        self.assertIn("DTD", wb.sheet("S").problem)
        self.assertEqual(wb.sheet("S").cells, {})

    def test_macro_enabled_workbook_notes_vba(self):
        wb = xr.load(self.book("m.xlsm", vba=b"\x01\x02 not real VBA"))
        self.assertEqual(len(wb.vba), 64)
        self.assertIn("vba-project", [f["code"] for f in xr.check(wb)["findings"]])
