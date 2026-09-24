"""The XLSX reader on the trimmed DESNZ file and on broken workbooks."""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import IsolatedTestCase, fixture  # noqa: E402

from ghg_factors_mcp.xlsx import Workbook, XlsxError  # noqa: E402

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def workbook(sheet_xml: str, shared: str | None = None, extra: dict | None = None, drop: tuple = ()) -> bytes:
    parts = {
        "_rels/.rels": ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
                        '</Relationships>'),
        "xl/workbook.xml": f'<workbook {NS} {RNS}><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                       f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="/xl/worksheets/sheet1.xml"/>'
                                       f'<Relationship Id="rId2" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>'
                                       '</Relationships>'),
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/sharedStrings.xml": shared or f'<sst {NS}><si><t>ID</t></si></sst>',
    }
    parts.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in parts.items():
            if name not in drop:
                z.writestr(name, text)
    return buf.getvalue()


def sheet(rows: str) -> str:
    return f"<worksheet {NS}><sheetData>{rows}</sheetData></worksheet>"


class RealFile(IsolatedTestCase):
    def test_trimmed_desnz_flat_file(self):
        wb = Workbook(fixture("desnz_flat_2026_trimmed.xlsx"))
        self.assertEqual(wb.sheet_names, ["Front page", "Factors by Category"])
        rows = wb.rows("Factors by Category")
        header = next(r for r in rows if r[:1] == ["ID"])
        self.assertEqual(header[-1], "GHG Conversion Factor 2026")
        diesel = next(r for r in rows if r[:1] == ["1_101_1011_8_1"])
        self.assertEqual(diesel[4], "Diesel (average biofuel blend)")
        self.assertEqual(float(diesel[9]), 2.58354)
        dash = next(r for r in rows if r[:1] == ["27_319_3192_14_1"])
        self.assertEqual(dash[5], "120,000–199,999 dwt")  # en dash, as published

    def test_missing_sheet_is_named(self):
        with self.assertRaisesRegex(XlsxError, "no sheet named 'Nope'"):
            Workbook(fixture("desnz_flat_2026_trimmed.xlsx")).rows("Nope")


class Values(IsolatedTestCase):
    def test_inline_rich_escaped_and_gaps(self):
        shared = (f'<sst {NS}><si><t>plain</t></si><si><r><t>rich </t></r><r><t>text</t></r>'
                  '<rPh><t>PHONETIC</t></rPh></si><si><t>line_x000D_break _x005F_x0041_</t></si></sst>')
        rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>inline</t></is></c><c r="B2"><v>1.5E-3</v></c>'
                '<c r="D2" t="b"><v>1</v></c><c r="E2" t="s"><v>2</v></c></row>'
                '<row r="4"><c t="str"><v>no ref</v></c></row>')
        got = Workbook(workbook(sheet(rows), shared)).rows("Data")
        self.assertEqual(got[0], ["plain", None, "rich text"])
        self.assertEqual(got[1], ["inline", "1.5E-3", None, "TRUE", "line\rbreak _x0041_"])
        self.assertEqual(got[2], ["no ref"])


class Malformed(IsolatedTestCase):
    def assertRejected(self, data: bytes, pattern: str):
        with self.assertRaisesRegex(XlsxError, pattern):
            wb = Workbook(data)
            wb.rows(wb.sheet_names[0])

    def test_empty_body(self):
        self.assertRejected(b"", "empty file")

    def test_html_error_page_instead_of_xlsx(self):
        self.assertRejected(b"<!DOCTYPE html><html><body>Service unavailable</body></html>", "not a zip")

    def test_truncated_download(self):
        data = fixture("desnz_flat_2026_trimmed.xlsx")
        self.assertRejected(data[: len(data) // 2], "not a zip|cannot be read")

    def test_zip_without_workbook(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("hello.txt", "not a workbook")
        self.assertRejected(buf.getvalue(), "no workbook part")

    def test_sheet_part_missing(self):
        self.assertRejected(workbook(sheet(""), drop=("xl/worksheets/sheet1.xml",)), "missing")

    def test_not_well_formed(self):
        self.assertRejected(workbook(sheet('<row r="1"><c r="A1"><v>1</v></row>')), "not well-formed")

    def test_dtd_refused(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is></c>'
                '</row></sheetData></worksheet>')
        self.assertRejected(workbook(bomb), "DTD")

    def test_shared_string_out_of_range(self):
        self.assertRejected(workbook(sheet('<row r="1"><c r="A1" t="s"><v>7</v></c></row>')), "shared string")

    def test_bad_cell_reference(self):
        self.assertRejected(workbook(sheet('<row r="1"><c r="1A"><v>1</v></c></row>')), "not valid")

    def test_no_sheets(self):
        data = workbook(sheet(""), extra={"xl/workbook.xml": f"<workbook {NS} {RNS}><sheets/></workbook>"})
        with self.assertRaisesRegex(XlsxError, "no sheets"):
            Workbook(data)


if __name__ == "__main__":
    import unittest
    unittest.main()
