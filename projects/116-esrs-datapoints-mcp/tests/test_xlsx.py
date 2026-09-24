"""The stdlib reader against damaged, hostile and unusual workbooks."""
import zipfile
from unittest import mock

from support import Isolated
import xlsxmake as xm

from esrs_datapoints_mcp import xlsx
from esrs_datapoints_mcp.parse import NotADatapointList, parse_workbook
from esrs_datapoints_mcp.xlsx import XlsxError, read_workbook


class CellTypes(Isolated):
    def test_shared_rich_text_skips_phonetic_runs_and_decodes_escapes(self):
        shared = (f'<?xml version="1.0"?><sst xmlns="{xm.NS}"><si><t>ID</t></si><si><t>Name</t></si>'
                  '<si><r><t>Placeholder </t></r><r><t>rich</t></r><rPh><t>PHONETIC</t></rPh></si>'
                  '<si><t>line_x000D_break</t></si></sst>')
        body = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                '<row r="2"><c r="A2" t="str"><v>X-1_01</v></c><c r="B2" t="s"><v>2</v></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>X-1_02</t></is></c><c r="B3" t="s"><v>3</v></c>'
                '<c r="C3" t="b"><v>1</v></c><c r="D3" t="e"><v>#VALUE!</v></c><c r="E3"><v>13.0</v></c>'
                '<c r="F3" t="s"><v>99</v></c></row>')
        path = xm.write(self.tmp / "t.xlsx", [("S", xm.sheet_xml(body), None)], shared=shared)
        rows = read_workbook(path)[0].rows
        self.assertEqual(rows[2], {0: "X-1_01", 1: "Placeholder rich"})
        self.assertEqual(rows[3][2], "TRUE")
        self.assertNotIn(3, rows[3])  # error values carry nothing
        self.assertEqual(rows[3][4], "13")
        self.assertNotIn(5, rows[3])  # a shared-string index out of range is empty, not a crash
        ix = parse_workbook(path)
        self.assertEqual(ix["datapoints"][1]["name"], "line break")

    def test_cells_without_references_are_placed_in_order(self):
        body = ('<row><c t="inlineStr"><is><t>ID</t></is></c><c t="inlineStr"><is><t>Name</t></is></c></row>'
                '<row><c t="inlineStr"><is><t>X-1_01</t></is></c><c t="inlineStr"><is><t>Placeholder</t></is>'
                '</c></row>')
        rows = read_workbook(xm.write(self.tmp / "t.xlsx", [("S", xm.sheet_xml(body), None)]))[0].rows
        self.assertEqual(rows, {1: {0: "ID", 1: "Name"}, 2: {0: "X-1_01", 1: "Placeholder"}})

    def test_vertical_merge_fills_down_horizontal_merge_does_not_spread(self):
        path = xm.simple(self.tmp / "m.xlsx", [["Placeholder title"], ["ID", "DR", "Name"],
                                               ["X-1_01", "X-1", "Placeholder 1"], ["X-1_02", None, "Placeholder 2"]],
                         merges=["A1:C1", "B3:B4"])
        rows = read_workbook(path)[0].rows
        self.assertEqual(rows[1], {0: "Placeholder title"})
        self.assertEqual(rows[4][1], "X-1")

    def test_huge_merged_range_is_bounded(self):
        path = xm.simple(self.tmp / "m.xlsx", [["ID", "Name"], ["X-1_01", "Placeholder"]], merges=["A2:A1048576"])
        with mock.patch.object(xlsx, "MAX_ROWS", 1000):
            rows = read_workbook(path)[0].rows
        self.assertLessEqual(max(rows), 1000)


class Damaged(Isolated):
    def assertRefused(self, path, *words):
        with self.assertRaises(XlsxError) as cm:
            parse_workbook(path)
        for w in words:
            self.assertIn(w, str(cm.exception))

    def test_missing_file_says_where_to_download(self):
        self.assertRefused(self.tmp / "nope.xlsx", "No file at", "efrag.org", "ESRS_DATAPOINTS_XLSX")

    def test_directory(self):
        self.assertRefused(self.tmp, "directory")

    def test_not_a_zip(self):
        p = self.tmp / "x.xlsx"
        p.write_text("Placeholder,csv,text\n")
        self.assertRefused(p, "no zip signature")

    def test_empty_file(self):
        p = self.tmp / "x.xlsx"
        p.write_bytes(b"")
        self.assertRefused(p, "no zip signature")

    def test_legacy_xls_or_encrypted(self):
        p = self.tmp / "x.xlsx"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512)
        self.assertRefused(p, "legacy .xls", "save it as")

    def test_truncated_zip(self):
        good = xm.simple(self.tmp / "g.xlsx", [["ID", "Name"], ["X-1_01", "Placeholder"]])
        p = self.tmp / "t.xlsx"
        p.write_bytes(good.read_bytes()[:200])
        self.assertRefused(p, "damaged")

    def test_corrupted_member(self):
        good = xm.simple(self.tmp / "g.xlsx", [["ID", "Name"], ["X-1_01", "Placeholder"]])
        data = bytearray(good.read_bytes())
        with zipfile.ZipFile(good) as z:
            info = z.getinfo("xl/worksheets/sheet1.xml")
        start = info.header_offset + 30 + len(info.filename) + len(info.extra)
        for i in range(start, start + 20):
            data[i] ^= 0xFF
        p = self.tmp / "c.xlsx"
        p.write_bytes(bytes(data))
        self.assertRefused(p, "damaged")

    def test_malformed_xml(self):
        p = xm.write(self.tmp / "b.xlsx", [("S", "<worksheet><sheetData><row>", None)])
        self.assertRefused(p, "not well-formed")

    def test_dtd_is_refused(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
                f'<worksheet xmlns="{xm.NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol2;</t></is>'
                '</c></row></sheetData></worksheet>')
        self.assertRefused(xm.write(self.tmp / "d.xlsx", [("S", bomb, None)]), "DTD")

    def test_utf16_part_is_refused(self):
        xml = xm.sheet_xml(xm.rows_xml([["ID", "Name"]])).replace('encoding="UTF-8"', 'encoding="UTF-16"')
        self.assertRefused(xm.write(self.tmp / "u.xlsx", [("S", xml.encode("utf-16"), None)]), "UTF-8")

    def test_oversized_part_is_refused(self):
        p = xm.simple(self.tmp / "big.xlsx", [["ID", "Name"]] + [["X-1_%02d" % i, "Placeholder " * 20]
                                                                 for i in range(50)])
        with mock.patch.object(xlsx, "MAX_PART_BYTES", 1000):
            self.assertRefused(p, "larger than")

    def test_no_workbook_part(self):
        p = self.tmp / "n.xlsx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("placeholder.txt", "placeholder")
        self.assertRefused(p, "no workbook part")

    def test_workbook_without_sheets(self):
        wb = f'<?xml version="1.0"?><workbook xmlns="{xm.NS}"><sheets/></workbook>'
        self.assertRefused(xm.write(self.tmp / "e.xlsx", [], workbook_xml=wb), "no worksheet")

    def test_workbook_without_a_datapoint_table(self):
        p = xm.simple(self.tmp / "x.xlsx", [["Placeholder", "numbers"], [1, 2]])
        with self.assertRaises(NotADatapointList) as cm:
            parse_workbook(p)
        self.assertIn("'ID' and a 'Name'", str(cm.exception))
