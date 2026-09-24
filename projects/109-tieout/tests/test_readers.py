"""Readers: what each file format yields, and every way a file can fail to be read."""
import os
import unittest
import zipfile
from decimal import Decimal
from unittest import mock

from tests.support import (A, C, MC, IsolatedTestCase, cell, chart_xml, docx, para, pptx, sheet_xml, slide_xml, sp,
                           table, tieout, write_zip, xlsx, rels, CT, W, REL)


def texts(doc):
    return [(s.where, s.text) for s in doc.segments]


def numbers(path, locale="en"):
    doc = tieout.read_deliverable(path)
    out = []
    for seg in doc.segments:
        out.extend(tieout.scan_segment(seg, locale))
    return doc, out


class WordDocuments(IsolatedTestCase):
    def test_paragraphs_tables_and_footnotes(self):
        body = (para("Revenue €4.2bn in 2025")
                + '<w:p><w:r><w:t>Net debt €1.05bn.</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                  '<w:footnoteReference w:id="5"/></w:r></w:p>'
                + table([["", "2025"], ["Revenue (€m)", "4,214"]]))
        notes = (f'<w:footnotes xmlns:w="{W}"><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r>'
                 '</w:p></w:footnote><w:footnote w:id="5"><w:p><w:r><w:footnoteRef/></w:r><w:r><w:t> Unaudited, 31 '
                 'December 2025.</w:t></w:r></w:p></w:footnote></w:footnotes>')
        path = docx(self.path("r.docx"), body, {"word/footnotes.xml": notes},
                    [("rId9", "footnotes", "footnotes.xml")])
        doc, nums = numbers(path)
        self.assertEqual(texts(doc)[:2], [("paragraph 1", "Revenue €4.2bn in 2025"), ("paragraph 2", "Net debt €1.05bn.¹")])
        cell_seg = next(s for s in doc.segments if s.table and s.text == "4,214")
        self.assertEqual(cell_seg.where, "table 1, row 2, col 2")
        self.assertIn(("row label", "Revenue (€m)"), cell_seg.labels)
        self.assertIn(("column header", "2025"), cell_seg.labels)
        foot = next(s for s in doc.segments if s.where == "footnote 1")
        self.assertTrue(foot.text.startswith("¹ Unaudited"))
        reasons = {n.written: n.reason for n in nums if n.status == "excluded"}
        self.assertEqual(reasons["¹"], tieout.R_FOOTNOTE)
        self.assertEqual(doc.counts["footnotes"], 1)

    def test_tracked_changes_keep_the_new_text_only(self):
        body = ('<w:p><w:r><w:t xml:space="preserve">EBITDA €</w:t></w:r><w:del><w:r><w:delText>612</w:delText></w:r>'
                '</w:del><w:ins><w:r><w:t>598</w:t></w:r></w:ins><w:r><w:t>m</w:t></w:r></w:p>')
        doc, nums = numbers(docx(self.path("t.docx"), body))
        self.assertEqual(texts(doc), [("paragraph 1", "EBITDA €598m")])

    def test_fields(self):
        page = ('<w:p><w:r><w:t xml:space="preserve">Page </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>7</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
        seq = ('<w:p><w:r><w:t xml:space="preserve">Chart </w:t></w:r><w:fldSimple w:instr=" SEQ Chart \\* ARABIC ">'
               '<w:r><w:t>3</w:t></w:r></w:fldSimple><w:r><w:t xml:space="preserve">: revenue 4,214</w:t></w:r></w:p>')
        doc, nums = numbers(docx(self.path("f.docx"), page + seq))
        got = {n.written: n.reason for n in nums}
        self.assertEqual(got["7"], tieout.R_PAGE)
        self.assertEqual(got["3"], tieout.R_LABEL)
        self.assertIsNone(got["4,214"])

    def test_text_box_is_read_once(self):
        box = '<w:txbxContent><w:p><w:r><w:t>Boxed 1,234</w:t></w:r></w:p></w:txbxContent>'
        body = ('<w:p><w:r><w:t xml:space="preserve">Before </w:t></w:r><w:r><mc:AlternateContent><mc:Choice Requires="wps">'
                f'<w:drawing><wps:wsp xmlns:wps="x"><wps:txbx>{box}</wps:txbx></wps:wsp></w:drawing></mc:Choice>'
                f'<mc:Fallback><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>{box}</v:textbox>'
                '</v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>')
        doc, nums = numbers(docx(self.path("b.docx"), body))
        self.assertEqual([n.written for n in nums], ["1,234"])
        self.assertTrue(nums[0].seg.where.startswith("text box 1"))

    def test_hyperlinks_headers_footers_and_content_controls(self):
        body = ('<w:sdt><w:sdtContent>' + para("Controlled 12.5%") + '</w:sdtContent></w:sdt>'
                '<w:p><w:hyperlink r:id="rIdL"><w:r><w:t>source</w:t></w:r></w:hyperlink></w:p>')
        footer = f'<w:ftr xmlns:w="{W}">' + para("Confidential 2026") + "</w:ftr>"
        path = docx(self.path("h.docx"), body, {"word/footer1.xml": footer},
                    [("rIdL", "hyperlink", "https://example.org/report?x=1", "External"),
                     ("rIdF", "footer", "footer1.xml")])
        doc = tieout.read_deliverable(path)
        self.assertIn(("paragraph 1", "Controlled 12.5%"), texts(doc))
        self.assertIn(("footer", "Confidential 2026"), texts(doc))
        self.assertEqual(doc.links, [("https://example.org/report?x=1", "source")])

    def test_chart_in_a_word_document(self):
        body = (para("Figure: revenue (€m)")
                + '<w:p><w:r><w:drawing><a:graphic><a:graphicData><c:chart r:id="rIdC"/></a:graphicData></a:graphic>'
                  '</w:drawing></w:r></w:p>')
        path = docx(self.path("c.docx"), body, {"word/charts/chart1.xml": chart_xml(None, "Revenue", ["A", "B"],
                                                                                     ["2105.2", "0.61339999999999995"])},
                    [("rIdC", "chart", "charts/chart1.xml")])
        doc, nums = numbers(path)
        values = [(n.written, n.seg.raw) for n in nums if n.seg.raw]
        self.assertEqual(values, [("2,105.2", "value"), ("0.6134", "value")])
        self.assertEqual(nums[-2].scale_exp, 6)  # the caption above says €m
        self.assertEqual(doc.counts["charts"], 1)


class PowerPoint(IsolatedTestCase):
    def test_slide_order_comes_from_the_presentation(self):
        path = pptx(self.path("o.pptx"), [(slide_xml(sp("second 22%")), None), (slide_xml(sp("first 11%")), None)],
                    order=[1, 0])
        doc = tieout.read_deliverable(path)
        self.assertEqual(texts(doc), [("slide 1", "first 11%"), ("slide 2", "second 22%")])

    def test_tables_notes_charts_fields_hidden_and_groups(self):
        tbl = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="4" name="t"/><p:cNvGraphicFramePr/><p:nvPr/>'
               '</p:nvGraphicFramePr><p:xfrm/><a:graphic><a:graphicData uri="t"><a:tbl>'
               '<a:tr><a:tc><a:txBody><a:bodyPr/><a:p/></a:txBody></a:tc><a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:t>2025'
               '</a:t></a:r></a:p></a:txBody></a:tc></a:tr>'
               '<a:tr><a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:t>EBITDA</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody>'
               '<a:bodyPr/><a:p><a:r><a:t>598</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></a:graphicData>'
               '</a:graphic></p:graphicFrame>')
        chart = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="5" name="c"/><p:cNvGraphicFramePr/><p:nvPr/>'
                 '</p:nvGraphicFramePr><p:xfrm/><a:graphic><a:graphicData uri="c"><c:chart r:id="rIdC"/></a:graphicData>'
                 '</a:graphic></p:graphicFrame>')
        fields = sp("", runs='<a:r><a:t>Updated </a:t></a:r><a:fld id="{1}" type="datetime1"><a:t>24/09/2026</a:t></a:fld>'
                             '<a:r><a:t> slide </a:t></a:r><a:fld id="{2}" type="slidenum"><a:t>3</a:t></a:fld>')
        sup = sp("", runs='<a:r><a:t>€4.2bn</a:t></a:r><a:r><a:rPr baseline="30000"/><a:t>1</a:t></a:r>')
        group = f'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="9" name="g"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>{sp("grouped 7.5%")}</p:grpSp>'
        shapes = sp("Key figures (€m)", ph="title") + tbl + chart + fields + sup + group + sp("99", ph="sldNum")
        notes = (f'<?xml version="1.0"?><p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                 f'xmlns:a="{A}"><p:cSld><p:spTree>{sp("", ph="sldImg")}{sp("Say 61.5% here", ph="body")}</p:spTree>'
                 '</p:cSld></p:notes>')
        slide_rels = [("rIdC", "chart", "../charts/chart1.xml"), ("rIdN", "notesSlide", "../notesSlides/notesSlide1.xml")]
        parts = {"ppt/charts/chart1.xml": chart_xml("Revenue", "2025", ["DACH", "Nordics"], ["2105.2", "1187.4"]),
                 "ppt/notesSlides/notesSlide1.xml": notes}
        path = pptx(self.path("t.pptx"), [(slide_xml(shapes, show="0"), slide_rels)], parts=parts)
        doc, nums = numbers(path)
        by = {n.written: n for n in nums}
        self.assertEqual(by["598"].seg.where, "slide 1 (hidden), table 1, row 2, col 2")
        self.assertIn(("slide title", "Key figures (€m)"), by["598"].seg.labels)
        self.assertEqual(by["598"].scale_exp, 6)
        self.assertEqual(by["61.5%"].seg.where, "slide 1 notes")
        self.assertEqual(by["2,105.2"].seg.where, "slide 1 (hidden), chart (2025, DACH)")
        self.assertEqual(by["3"].reason, tieout.R_PAGE)
        self.assertEqual(by["99"].reason, tieout.R_PAGE)
        self.assertEqual({by[k].reason for k in ("24", "09", "2026")}, {tieout.R_DATE})
        self.assertEqual(by["¹"].reason, tieout.R_FOOTNOTE)
        self.assertEqual(by["€4.2bn"].scale_exp, 9)
        self.assertIn("grouped 7.5%", [s.text for s in doc.segments])
        self.assertEqual(doc.counts, {"slides": 1, "hidden slides": 1, "charts": 1})

    def test_chart_dates_are_not_figures(self):
        slide = slide_xml('<p:graphicFrame><a:graphic><a:graphicData><c:chart r:id="rIdC"/></a:graphicData></a:graphic>'
                          '</p:graphicFrame>')
        parts = {"ppt/charts/chart1.xml": chart_xml("", "s", ["a"], ["45930"], fmt="d-mmm-yy")}
        doc, nums = numbers(pptx(self.path("d.pptx"), [(slide, [("rIdC", "chart", "../charts/chart1.xml")])], parts=parts))
        self.assertEqual([(n.written, n.reason) for n in nums], [("45,930", tieout.R_DATE)])

    def test_missing_slide_part_is_a_warning(self):
        path = pptx(self.path("m.pptx"), [(slide_xml(sp("12.5%")), None)])
        broken = self.path("broken.pptx")
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(broken, "w") as zout:
            for item in zin.infolist():
                if item.filename != "ppt/slides/slide1.xml":
                    zout.writestr(item, zin.read(item.filename))
        doc = tieout.read_deliverable(broken)
        self.assertEqual(doc.segments, [])
        self.assertIn("slide part missing", doc.warnings[0])


class Workbooks(IsolatedTestCase):
    STYLES = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts><numFmt numFmtId="164" formatCode="dd.mm.yyyy"/><numFmt numFmtId="165" formatCode="0.0&quot;x&quot;"/>'
              '</numFmts><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="165"/></cellXfs>'
              '</styleSheet>')

    def test_cell_types(self):
        shared = ["Metric", "<si><r><t>Reve</t></r><r><t>nue</t></r><rPh><t>x</t></rPh></si>", "1,234.5"]
        rows = [
            (1, [cell("A1", 0, t="s"), cell("B1", 2024), cell("C1", 2025)]),
            (2, [cell("A2", 1, t="s"), cell("B2", 100), cell("C2", "0.61339999999999995", f="B2/B3")]),
            (3, [cell("A3", t="inlineStr", inline="Text number"), cell("B3", 2, t="s"), cell("C3", "12.5%", t="str", f="TEXT(1)")]),
            (4, [cell("A4", t="inlineStr", inline="Dates"), cell("B4", 45930, s=1), cell("C4", 45930, s=2), cell("D4", 1.8, s=3)]),
            (5, [cell("A5", t="inlineStr", inline="Other"), cell("B5", "#DIV/0!", t="e"), cell("C5", 1, t="b"),
                 cell("D5", f="SUM(A1:A2)")]),
            (None, [cell(None, t="inlineStr", inline="No refs"), cell(None, 42), cell(None, 43)]),
        ]
        path = xlsx(self.path("w.xlsx"), [("Model", sheet_xml(rows))], shared=shared, styles=self.STYLES)
        src = tieout.read_source(path, [])
        got = {c.cell: (c.raw, c.label, c.from_text) for c in src.cells}
        self.assertEqual(got["B2"], (Decimal("100"), "Revenue | 2024", False))
        self.assertEqual(got["C2"][0], Decimal("0.6134"))
        self.assertEqual(got["B3"], (Decimal("1234.5"), "Text number | 2024", True))
        self.assertEqual(got["C3"][0], Decimal("0.125"))
        self.assertEqual(got["D4"][0], Decimal("1.8"))
        self.assertNotIn("B4", got)
        self.assertNotIn("C4", got)
        self.assertNotIn("B1", got)
        self.assertEqual((got["B6"][0], got["C6"][0]), (Decimal("42"), Decimal("43")))
        self.assertEqual(src.meta["formula cells without a saved value"], 1)
        self.assertEqual(src.meta["date cells skipped"], 2)
        self.assertEqual(src.meta["error cells"], 1)
        self.assertIn("no saved value", src.warnings[0])

    def test_sheet_names_hidden_sheets_and_strict_namespace(self):
        strict = "http://purl.oclc.org/ooxml/spreadsheetml/main"
        rows = [(1, [cell("A1", t="inlineStr", inline="Übersicht"), cell("B1", 7.25)])]
        path = xlsx(self.path("s.xlsx"), [("Q'4 data", sheet_xml(rows, ns=strict)), ("Hidden", sheet_xml(rows, ns=strict))],
                    states={"Hidden": "hidden"}, ns=strict, rel_ns="http://purl.oclc.org/ooxml/officeDocument/relationships")
        src = tieout.read_source(path, [])
        self.assertEqual([c.ref for c in src.cells], ["'Q''4 data'!B1", "Hidden!B1"])
        self.assertEqual([c.hidden for c in src.cells], [False, True])
        self.assertEqual(src.cells[0].label, "Übersicht")

    def test_malformed_sheet(self):
        path = xlsx(self.path("bad.xlsx"), [("S", "<worksheet><sheetData><row>")])
        with self.assertRaisesRegex(tieout.InputError, "sheet 'S' is malformed XML"):
            tieout.read_source(path, [])


class CsvFiles(IsolatedTestCase):
    def test_german_export(self):
        path = self.text_file("m.csv", "Land;Umsatz (Mio. €);Anteil\r\nÖsterreich;1.215,0;9,3 %\r\nSumme;-1.234,50;(2,5)\r\n",
                              encoding="cp1252")
        src = tieout.read_source(path, [])
        got = {c.cell: (c.raw, c.value, c.label) for c in src.cells}
        self.assertEqual(got["B2"], (Decimal("1215.0"), Decimal("1215000000"), "Österreich | Umsatz (Mio. €)"))
        self.assertEqual(got["C2"][0], Decimal("0.093"))
        self.assertEqual(got["B3"][0], Decimal("-1234.50"))
        self.assertEqual(got["C3"][0], Decimal("-2.5"))
        self.assertEqual(src.meta["number_format"], "de")
        self.assertIn("Windows-1252", src.warnings[0])

    def test_trailing_minus_bom_and_quotes(self):
        path = self.text_file("s.csv", "﻿Item,Amount,Note\n\"Rent, office\",\"1,234.50\",x\nFee,99.5-,y\n")
        src = tieout.read_source(path, [])
        got = {c.cell: c.raw for c in src.cells}
        self.assertEqual(got, {"B2": Decimal("1234.50"), "B3": Decimal("-99.5")})
        self.assertEqual(src.meta["delimiter"], ",")

    def test_utf16_tab_separated(self):
        path = self.text_file("u.csv", "Name\tValue\nA\t12.5\n", encoding="utf-16")
        self.assertEqual([c.raw for c in tieout.read_source(path, []).cells], [Decimal("12.5")])

    def test_tsv_and_ragged_rows(self):
        path = self.text_file("r.tsv", "a\tb\n1.5\n2\t3\t4\n")
        self.assertEqual(len(tieout.read_source(path, []).cells), 4)

    def test_binary_and_empty(self):
        with self.assertRaisesRegex(tieout.InputError, "binary"):
            tieout.read_source(self.text_file("b.csv", b"\x00\x01\x02abc"), [])
        with self.assertRaisesRegex(tieout.InputError, "empty"):
            tieout.read_source(self.text_file("e.csv", b""), [])


class TextFiles(IsolatedTestCase):
    def test_markdown(self):
        md = ("# 1. Results\n\nRevenue €4.2bn [source](https://example.com/2025/a.pdf) and `code 12` <!-- 99 -->\n\n"
              "```\nprint(42)\n```\n\nKey figures (€m)\n\n| Metric | 2025 |\n|---|---:|\n| EBITDA | 598 |\n\n"
              "Grew 12%[^1]\n\n[^1]: Unaudited.\n")
        doc, nums = numbers(self.text_file("r.md", md))
        got = {n.written: (n.status, n.reason) for n in nums}
        self.assertEqual((nums[0].written, nums[0].reason), ("1", tieout.R_LIST))
        self.assertEqual({n.reason for n in nums if n.written == "1"}, {tieout.R_LIST, tieout.R_FOOTNOTE})
        self.assertEqual(got["€4.2bn"][0], None)
        self.assertEqual({n.reason for n in nums if n.written == "2025"}, {tieout.R_LINK, tieout.R_YEAR})
        self.assertEqual(next(n.reason for n in nums if n.written == "2025"), tieout.R_LINK)
        self.assertEqual(got["12"][1], tieout.R_CODEBLOCK)
        self.assertEqual(got["99"][1], tieout.R_COMMENT)
        self.assertEqual(got["(42)"][1], tieout.R_CODEBLOCK)
        cell_598 = next(n for n in nums if n.written == "598")
        self.assertEqual(cell_598.seg.where, "line 13, table 1, row 2, col 2")
        self.assertEqual(cell_598.scale_exp, 6)
        self.assertEqual(doc.links, [("https://example.com/2025/a.pdf", doc.segments[1].text)])
        self.assertEqual(got["12%"][0], None)

    def test_text_with_form_feeds(self):
        doc, nums = numbers(self.text_file("r.txt", "Revenue 4,213.5\n\f3\nEBITDA 598.3\n"))
        self.assertEqual([(n.written, n.seg.where, n.reason) for n in nums],
                         [("4,213.5", "line 1 (page 1)", None), ("3", "line 2 (page 2)", tieout.R_PAGE),
                          ("598.3", "line 3 (page 2)", None)])
        self.assertEqual(doc.counts["pages"], 2)

    def test_invalid_utf8_and_binary(self):
        doc = tieout.read_deliverable(self.text_file("l.txt", "Umsatz 4,2 Mrd. €".encode("cp1252")))
        self.assertIn("Windows-1252", doc.warnings[0])
        with self.assertRaisesRegex(tieout.InputError, "binary"):
            tieout.read_deliverable(self.text_file("b.txt", b"ab\x00cd"))


class Unreadable(IsolatedTestCase):
    def check(self, path, pattern, reader=tieout.read_deliverable):
        with self.assertRaisesRegex(tieout.InputError, pattern):
            reader(path)

    def test_missing_empty_directory(self):
        self.check(self.path("none.docx"), "file not found")
        self.check(self.text_file("e.docx", b""), "file is empty")
        os.mkdir(self.path("d.pptx"))
        self.check(self.path("d.pptx"), "is a directory")

    def test_wrong_types(self):
        self.check(self.text_file("r.pdf", b"%PDF-1.7"), "pdftotext -layout")
        self.check(self.text_file("r.doc", b"x"), "save it as .docx")
        self.check(self.text_file("r.odt", b"x"), "save it as .docx")
        self.check(self.text_file("r.rtf", b"x"), "save it as .docx")
        self.check(self.text_file("m.xlsx", b"x"), "source format")
        self.check(self.text_file("r.html", b"x"), "unsupported file type")
        self.check(self.text_file("d.docx", b"x"), "unsupported source type", lambda p: tieout.read_source(p, []))

    def test_not_a_zip(self):
        self.check(self.text_file("t.docx", "just text"), "not a valid .docx")
        self.check(self.text_file("p.docx", b"%PDF-1.4 ..."), "this is a PDF")
        self.check(self.text_file("o.pptx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"), "password-protected")

    def test_truncated_zip(self):
        path = docx(self.path("full.docx"), para("Revenue 12.5%") * 200)
        with open(path, "rb") as f:
            data = f.read()
        self.check(self.text_file("cut.docx", data[: len(data) // 2]), "not a valid .docx|damaged|missing")

    def test_missing_main_part(self):
        path = write_zip(self.path("x.docx"), {"[Content_Types].xml": CT})
        self.check(path, "not a Word document")
        path = write_zip(self.path("x.pptx"), {"[Content_Types].xml": CT})
        self.check(path, "not a PowerPoint file")
        path = write_zip(self.path("x.xlsx"), {"[Content_Types].xml": CT})
        self.check(path, "not an Excel workbook", lambda p: tieout.read_source(p, []))

    def test_malformed_and_dtd(self):
        self.check(docx(self.path("m.docx"), "<w:p><w:r>"), "malformed XML")
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
                f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>')
        path = write_zip(self.path("dtd.docx"), {"_rels/.rels": rels([("rId1", "officeDocument", "word/document.xml")]),
                                                 "word/document.xml": bomb})
        self.check(path, "document type declaration")

    def test_damaged_compressed_data(self):
        path = docx(self.path("z.docx"), para("Revenue 12.5% " * 50))
        with open(path, "rb") as f:
            data = bytearray(f.read())
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("word/document.xml")
        start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        for i in range(start + 5, start + 25):
            data[i] ^= 0xFF
        self.check(self.text_file("z2.docx", bytes(data)), "damaged|malformed")

    def test_oversized_part(self):
        path = docx(self.path("big.docx"), para("Revenue 12.5% " * 100))
        with mock.patch.object(tieout, "MAX_FILE_BYTES", 1000):
            self.check(path, "unpacks to more than|larger than")


if __name__ == "__main__":
    unittest.main()
