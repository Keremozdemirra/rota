"""Build the example files in this folder: a model, a German CSV export, an English
deck and a German report that ties out against them, with deliberate errors.

Run once, in a scratch virtual environment:

    python3 -m venv /tmp/fixtures && /tmp/fixtures/bin/pip install python-docx python-pptx openpyxl XlsxWriter
    /tmp/fixtures/bin/python examples/make_examples.py

tieout itself imports none of these libraries. They are used here because
files written by the real libraries look like the files people send.

Planted in the deck and the report (see the README for the tie-out):
  - a wrong number: EBITDA "€612m" (model: 598.3m), market share "15,3 %" (CSV: 14,8 %)
  - a stale number: net debt 2025 "1,080" in the key-figures table (model: 1,050)
  - a rounding edge case: renewal rate 0.6149 written "62%" (61% is right; 61.5% ties at one decimal)
  - an ambiguous number: "around 14%" margin fits 2024, 2025 and 2026F
  - German number format: "4,2 Mrd. €", "1.310 Mitarbeiter", "14,2 %"
  - numbers in a table, in speaker notes, in a chart cache, in footnotes, on a hidden slide
  - a fabricated DOI in the report's references
"""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------- model.xlsx
def make_model(path):
    from openpyxl import Workbook

    wb = Workbook()
    pl = wb.active
    pl.title = "P&L"
    rows = [
        ["P&L (€)", 2024, 2025, "2026F"],
        ["Revenue", 3874200000, 4213500000, 4590000000],
        ["EBITDA", 541000000, 598300000, 661000000],
        ["EBITDA margin", "=B3/B2", "=C3/C2", "=D3/D2"],
        ["Net debt", 1120000000, 1050000000, 980000000],
        ["Net debt / EBITDA", "=B5/B3", "=C5/C3", "=D5/D3"],
        ["Revenue growth", None, "=C2/B2-1", "=D2/C2-1"],
    ]
    for r in rows:
        pl.append(r)
    for col in "BCD":
        pl[f"{col}4"].number_format = "0.0%"
        pl[f"{col}7"].number_format = "0.0%"
        pl[f"{col}6"].number_format = '0.0"x"'
    kpi = wb.create_sheet("KPIs")
    for r in [
        ["KPI", 2024, 2025],
        ["Customers", 18420, 21050],
        ["Renewal rate", 0.5931, 0.6149],
        ["Recurring revenue share", 0.6008, 0.6312],
        ["Headcount (FTE)", 1240, 1310],
        ["Net promoter score", 38, 42],
        ["Model date", date(2025, 12, 31), None],
    ]:
        kpi.append(r)
    kpi["B7"].number_format = "yyyy-mm-dd"
    seg = wb.create_sheet("Segments")
    for r in [
        ["Segment", "Revenue 2025 (€m)", "EBITDA 2025 (€m)", "Share of revenue"],
        ["DACH", 2105.2, 312.4, "=B2/B$5"],
        ["Nordics", 1187.4, 170.1, "=B3/B$5"],
        ["Benelux", 920.9, 115.8, "=B4/B$5"],
        ["Total", "=SUM(B2:B4)", "=SUM(C2:C4)", "=SUM(D2:D4)"],
    ]:
        seg.append(r)
    wb.save(path)
    # openpyxl stores formulas without results; Excel stores both. Add the results
    # the way Excel would, so the model reads like one saved from Excel.
    results = {
        "xl/worksheets/sheet1.xml": {
            "B4": 541000000 / 3874200000, "C4": 598300000 / 4213500000, "D4": 661000000 / 4590000000,
            "B6": 1120000000 / 541000000, "C6": 1050000000 / 598300000, "D6": 980000000 / 661000000,
            "C7": 4213500000 / 3874200000 - 1, "D7": 4590000000 / 4213500000 - 1,
        },
        "xl/worksheets/sheet3.xml": {
            "D2": 2105.2 / 4213.5, "D3": 1187.4 / 4213.5, "D4": 920.9 / 4213.5,
            "B5": 2105.2 + 1187.4 + 920.9, "C5": 312.4 + 170.1 + 115.8, "D5": 1.0,
        },
    }
    _inject_results(path, results)


def _inject_results(path, results):
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in results:
                xml = data.decode("utf-8")
                for ref, value in results[item.filename].items():
                    pat = re.compile(r'(<c r="%s"[^>]*>)(<f>[^<]*</f>)(<v\s*/>|<v></v>)?(</c>)' % ref)
                    xml, n = pat.subn(lambda m: m.group(1) + m.group(2) + "<v>%r</v>" % value + m.group(4), xml)
                    assert n == 1, (item.filename, ref)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    os.replace(tmp, path)


# --------------------------------------------------------------- marktdaten.csv
def make_csv(path):
    # A German Excel export: semicolons, decimal commas, Windows-1252.
    text = ("Land;Marktvolumen 2025 (Mio. €);Wachstum 2025;Marktanteil Atlas 2025\r\n"
            "Deutschland;9.842,5;3,1 %;14,8 %\r\n"
            "Österreich;1.215,0;2,4 %;9,3 %\r\n"
            "Schweiz;2.310,8;1,9 %;6,1 %\r\n"
            "Summe DACH;13.368,3;2,8 %;13,2 %\r\n")
    with open(path, "wb") as f:
        f.write(text.encode("cp1252"))


# ------------------------------------------------------------------- deck.pptx
SLIDENUM = ('<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<p:nvSpPr><p:cNvPr id="%d" name="Slide Number %d"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="8229600" y="6356350"/><a:ext cx="609600" cy="365125"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:fld id="{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}" '
            'type="slidenum"><a:rPr lang="en-GB" sz="1000"/><a:t>%d</a:t></a:fld></a:p></p:txBody></p:sp>')


def make_deck(path):
    from lxml import etree
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    title_layout, bullet_layout, only_title = prs.slide_layouts[0], prs.slide_layouts[1], prs.slide_layouts[5]

    s1 = prs.slides.add_slide(title_layout)
    s1.shapes.title.text = "Project Atlas"
    s1.placeholders[1].text = "Board update · 24 September 2026"

    s2 = prs.slides.add_slide(bullet_layout)
    s2.shapes.title.text = "2025 at a glance"
    body = s2.placeholders[1].text_frame
    lines = [
        ["Revenue reached €4.2bn", ("1", True), " in 2025, up 8.8% on 2024"],
        ["EBITDA of €612m at a margin of 14.2%"],
        ["Net debt fell to €1.05bn, 1.8x EBITDA"],
        ["62% of customers renewed their contracts"],
        ["63% of revenue is recurring"],
        ["Margin held at around 14% for three years"],
    ]
    for i, parts in enumerate(lines):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        for part in parts:
            run = p.add_run()
            if isinstance(part, tuple):
                run.text = part[0]
                run.font._element.set("baseline", "30000")
            else:
                run.text = part
    box = s2.shapes.add_textbox(Inches(0.5), Inches(6.6), Inches(8), Inches(0.4))
    fp = box.text_frame.paragraphs[0]
    r = fp.add_run()
    r.text = "1"
    r.font._element.set("baseline", "30000")
    r.font.size = Pt(10)
    r = fp.add_run()
    r.text = " Unaudited. Source: Project Atlas model, version 7."
    r.font.size = Pt(10)
    s2.notes_slide.notes_text_frame.text = ("Renewal was 61.5% before rounding. "
                                            "Target: 1,500 employees by 2027.")

    s3 = prs.slides.add_slide(only_title)
    s3.shapes.title.text = "Key figures (€m)"
    data = [
        ["", "2024", "2025", "2026F"],
        ["Revenue", "3,874", "4,214", "4,590"],
        ["EBITDA", "541", "598", "661"],
        ["EBITDA margin (%)", "14.0", "14.2", "14.4"],
        ["Net debt", "1,120", "1,080", "980"],
        ["Customers ('000)", "18.4", "21.1", ""],
    ]
    shape = s3.shapes.add_table(len(data), 4, Inches(0.5), Inches(1.6), Inches(9), Inches(3))
    for ri, row in enumerate(data):
        for ci, val in enumerate(row):
            shape.table.cell(ri, ci).text = val

    s4 = prs.slides.add_slide(only_title)
    s4.shapes.title.text = "Revenue by segment, 2025 (€m)"
    cd = CategoryChartData(number_format="#,##0.0")
    cd.categories = ["DACH", "Nordics", "Benelux"]
    cd.add_series("Revenue", (2105.2, 1187.4, 920.9))
    s4.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(1.5), Inches(6), Inches(4.5), cd)
    tb = s4.shapes.add_textbox(Inches(6.8), Inches(2), Inches(3), Inches(2)).text_frame
    tb.text = "DACH is 50.0% of revenue"

    s5 = prs.slides.add_slide(bullet_layout)
    s5.shapes.title.text = "Market"
    b5 = s5.placeholders[1].text_frame
    b5.text = "DACH market: €13.4bn in 2025, growing 2.8% a year"
    b5.add_paragraph().text = "Our share of the DACH market is 13.2%"

    s6 = prs.slides.add_slide(bullet_layout)
    s6.shapes.title.text = "Backup"
    s6.placeholders[1].text_frame.text = "EBITDA 2024: €541m"
    s6._element.set("show", "0")

    for n, slide in enumerate(prs.slides, 1):
        slide.shapes._spTree.append(etree.fromstring(SLIDENUM % (900 + n, n, n)))
    prs.save(path)


# ------------------------------------------------------------------ bericht.docx
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_report(path):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    d = Document()
    d.add_heading("Projekt Atlas – Bericht an den Aufsichtsrat", 0)
    d.add_paragraph("Stand: 24. September 2026")
    d.add_heading("1. Überblick", 1)
    d.add_paragraph("Der Umsatz stieg 2025 auf 4,2 Mrd. € und lag damit 8,8 % über dem Vorjahr. "
                    "Das EBITDA betrug 598 Mio. € (Marge 14,2 %).")
    p = d.add_paragraph("Die Nettoverschuldung sank auf 1.050 Mio. €, das 1,8-fache des EBITDA.")
    p.add_run("FNREF1")
    d.add_paragraph("Ende 2025 beschäftigte Atlas 1.310 Mitarbeiter (Vollzeitäquivalente). "
                    "Die Verlängerungsquote lag bei 61 %.")
    d.add_heading("2. Markt", 1)
    p = d.add_paragraph("Das Marktvolumen in der DACH-Region betrug 2025 rund 13,4 Mrd. € (Wachstum 2,8 %). "
                        "Der Marktanteil in Deutschland beträgt 15,3 %.")
    p.add_run("FNREF2")
    d.add_paragraph("Tabelle 1: Kennzahlen (Mio. €)")
    rows = [
        ["Kennzahl", "2024", "2025"],
        ["Umsatz", "3.874,2", "4.213,5"],
        ["EBITDA", "541,0", "598,3"],
        ["EBITDA-Marge (%)", "14,0", "14,2"],
        ["Nettoverschuldung", "1.120,0", "1.050,0"],
        ["Mitarbeiter (FTE)", "1.240", "1.310"],
    ]
    t = d.add_table(rows=len(rows), cols=3)
    t.style = "Table Grid"
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            t.cell(ri, ci).text = val
    d.add_heading("Quellen", 1)
    d.add_paragraph("Statistisches Bundesamt: https://www.destatis.de/EN/Home/_node.html")
    q = d.add_paragraph("Eurostat, Datenbank: ")
    _hyperlink(q, "https://ec.europa.eu/eurostat/web/main/home", "Eurostat-Startseite")
    d.add_paragraph("Müller, K. (2025): Marktstudie DACH 2025, doi:10.5555/atlas.2025.017")
    footer = d.sections[0].footer.paragraphs[0]
    footer.text = "Projekt Atlas · Seite "
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    r = OxmlElement("w:r")
    tt = OxmlElement("w:t")
    tt.text = "1"
    r.append(tt)
    fld.append(r)
    footer._p.append(fld)
    d.save(path)
    _add_footnotes(path, {
        "FNREF1": "Nettoverschuldung zum 31.12.2025; Quelle: Konzernabschluss 2025, S. 45.",
        "FNREF2": "Marktdaten: Atlas-Schätzung auf Basis von Eurostat; Anteil gemessen am Umsatz.",
    })


def _hyperlink(paragraph, url, text):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rid = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    h.append(r)
    paragraph._p.append(h)


def _add_footnotes(path, notes):
    """python-docx has no footnote API; add the part the way Word writes it."""
    ids = {}
    body = []
    for i, (marker, text) in enumerate(notes.items(), 1):
        ids[marker] = i
        body.append(
            f'<w:footnote w:id="{i}"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>'
            f'<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteRef/></w:r>'
            f'<w:r><w:t xml:space="preserve"> {text}</w:t></w:r></w:p></w:footnote>')
    footnotes = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:footnotes xmlns:w="{W}">'
                 '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
                 '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r>'
                 '</w:p></w:footnote>' + "".join(body) + "</w:footnotes>")
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                for marker, i in ids.items():
                    xml = xml.replace(f"<w:r><w:t>{marker}</w:t></w:r>",
                                      f'<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                                      f'<w:footnoteReference w:id="{i}"/></w:r>')
                    assert marker not in xml, marker
                data = xml.encode("utf-8")
            elif item.filename == "word/_rels/document.xml.rels":
                xml = data.decode("utf-8").replace(
                    "</Relationships>",
                    '<Relationship Id="rIdFn1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/footnotes" Target="footnotes.xml"/></Relationships>')
                data = xml.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                xml = data.decode("utf-8").replace(
                    "</Types>",
                    '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-'
                    'officedocument.wordprocessingml.footnotes+xml"/></Types>')
                data = xml.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr("word/footnotes.xml", footnotes)
    os.replace(tmp, path)


if __name__ == "__main__":
    make_model(os.path.join(HERE, "model.xlsx"))
    make_csv(os.path.join(HERE, "marktdaten.csv"))
    make_deck(os.path.join(HERE, "deck.pptx"))
    make_report(os.path.join(HERE, "bericht.docx"))
    print("wrote model.xlsx, marktdaten.csv, deck.pptx, bericht.docx")
