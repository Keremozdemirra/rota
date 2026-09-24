"""Shared test helpers: small Office files built in code, and a test case that never sees the real $HOME."""
import html
import io
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tieout  # noqa: E402

EXAMPLES = ROOT / "examples"
FIXTURES = ROOT / "tests" / "fixtures"

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"

CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/></Types>')


def rels(items) -> str:
    """items: (id, type, target) or (id, type, target, 'External')."""
    out = [f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG_REL}">']
    for it in items:
        mode = f' TargetMode="{it[3]}"' if len(it) > 3 else ""
        out.append(f'<Relationship Id="{it[0]}" Type="{REL}/{it[1]}" Target="{it[2]}"{mode}/>')
    out.append("</Relationships>")
    return "".join(out)


def write_zip(path, parts: dict) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return str(path)


# ---------------------------------------------------------------- Word
def para(text, **kw) -> str:
    props = ""
    if kw.get("sup"):
        props = '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
    return f'<w:p><w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def docx(path, body: str, parts=None, doc_rels=()) -> str:
    items = {
        "[Content_Types].xml": CT,
        "_rels/.rels": rels([("rId1", "officeDocument", "word/document.xml")]),
        "word/document.xml": (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}" xmlns:r="{REL}" '
                              f'xmlns:mc="{MC}" xmlns:a="{A}" xmlns:c="{C}"><w:body>{body}</w:body></w:document>'),
    }
    if doc_rels:
        items["word/_rels/document.xml.rels"] = rels(doc_rels)
    items.update(parts or {})
    return write_zip(path, items)


def table(rows) -> str:
    out = ["<w:tbl>"]
    for row in rows:
        out.append("<w:tr>" + "".join(f"<w:tc>{para(c)}</w:tc>" for c in row) + "</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


# ---------------------------------------------------------- PowerPoint
def sp(text, ph=None, runs=None) -> str:
    nv = f'<p:nvPr><p:ph type="{ph}"/></p:nvPr>' if ph else "<p:nvPr/>"
    body = runs if runs is not None else f"<a:r><a:t>{text}</a:t></a:r>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/>{nv}</p:nvSpPr><p:spPr/>'
            f"<p:txBody><a:bodyPr/><a:p>{body}</a:p></p:txBody></p:sp>")


def slide_xml(shapes: str, show=None) -> str:
    attr = f' show="{show}"' if show is not None else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{REL}" '
            f'xmlns:c="{C}"{attr}><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            f"</p:nvGrpSpPr><p:grpSpPr/>{shapes}</p:spTree></p:cSld></p:sld>")


def pptx(path, slides, order=None, parts=None) -> str:
    """slides: list of (slide_xml, slide_rels or None). `order` lists slide indexes in presentation order."""
    order = order if order is not None else list(range(len(slides)))
    ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{10 + i}"/>' for i in order)
    items = {
        "[Content_Types].xml": CT,
        "_rels/.rels": rels([("rId1", "officeDocument", "ppt/presentation.xml")]),
        "ppt/presentation.xml": (f'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="{P}" '
                                 f'xmlns:r="{REL}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>'),
        "ppt/_rels/presentation.xml.rels": rels([(f"rId{10 + i}", "slide", f"slides/slide{i + 1}.xml")
                                                  for i in range(len(slides))]),
    }
    for i, (xml, srels) in enumerate(slides):
        items[f"ppt/slides/slide{i + 1}.xml"] = xml
        if srels:
            items[f"ppt/slides/_rels/slide{i + 1}.xml.rels"] = rels(srels)
    items.update(parts or {})
    return write_zip(path, items)


def chart_xml(title, series, cats, values, fmt="General") -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values))
    cpts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(cats))
    t = f"<c:title><c:tx><c:rich><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>" if title else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><c:chartSpace xmlns:c="{C}" xmlns:a="{A}"><c:chart>{t}<c:plotArea>'
            f"<c:barChart><c:ser><c:tx><c:strRef><c:strCache><c:pt idx=\"0\"><c:v>{series}</c:v></c:pt></c:strCache>"
            f"</c:strRef></c:tx><c:cat><c:strRef><c:strCache>{cpts}</c:strCache></c:strRef></c:cat>"
            f"<c:val><c:numRef><c:numCache><c:formatCode>{fmt}</c:formatCode>{pts}</c:numCache></c:numRef></c:val>"
            "</c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>")


# ---------------------------------------------------------------- Excel
def cell(ref, value=None, t=None, f=None, s=None, inline=None) -> str:
    attrs = f' r="{ref}"' if ref else ""
    if t:
        attrs += f' t="{t}"'
    if s is not None:
        attrs += f' s="{s}"'
    inner = ""
    if f is not None:
        inner += f"<f>{f}</f>"
    if inline is not None:
        inner += f"<is><t>{inline}</t></is>"
    if value is not None:
        inner += f"<v>{value}</v>"
    return f"<c{attrs}>{inner}</c>"


def sheet_xml(rows, ns=S) -> str:
    """rows: list of (row_number or None, [cell xml])."""
    body = "".join((f'<row r="{r}">' if r else "<row>") + "".join(cells) + "</row>" for r, cells in rows)
    return f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>'


def xlsx(path, sheets, shared=None, styles=None, states=None, ns=S, rel_ns=REL) -> str:
    """sheets: list of (name, sheet_xml)."""
    states = states or {}
    sheet_tags = "".join(
        f'<sheet name="{html.escape(name, quote=True)}" sheetId="{i + 1}" r:id="rId{i + 1}"'
        + (f' state="{states[name]}"' if name in states else "") + "/>"
        for i, (name, _) in enumerate(sheets))
    wb_rels = [(f"rId{i + 1}", "worksheet", f"worksheets/sheet{i + 1}.xml") for i in range(len(sheets))]
    items = {
        "[Content_Types].xml": CT,
        "_rels/.rels": rels([("rId1", "officeDocument", "xl/workbook.xml")]),
        "xl/workbook.xml": (f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{ns}" xmlns:r="{rel_ns}">'
                            f"<sheets>{sheet_tags}</sheets></workbook>"),
    }
    for i, (_, xml) in enumerate(sheets):
        items[f"xl/worksheets/sheet{i + 1}.xml"] = xml
    if shared is not None:
        wb_rels.append(("rIdS", "sharedStrings", "sharedStrings.xml"))
        items["xl/sharedStrings.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{ns}">'
                                         + "".join(s if s.startswith("<si>") else f"<si><t>{s}</t></si>" for s in shared)
                                         + "</sst>")
    if styles is not None:
        wb_rels.append(("rIdT", "styles", "styles.xml"))
        items["xl/styles.xml"] = styles
    items["xl/_rels/workbook.xml.rels"] = rels(wb_rels).replace(REL, rel_ns) if rel_ns != REL else rels(wb_rels)
    return write_zip(path, items)


class IsolatedTestCase(unittest.TestCase):
    """Every test runs with HOME pointed at a scratch directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        home = mock.patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def path(self, name) -> str:
        return str(self.tmp / name)

    def text_file(self, name, text, encoding="utf-8") -> str:
        p = self.tmp / name
        p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        return str(p)


def scan(text, locale="en", min_digits=1, **seg_kw):
    """Numbers found in one piece of text: list of Num."""
    return tieout.scan_segment(tieout.Segment(text, "test", **seg_kw), locale, min_digits)


def kept(text, locale="en", **kw):
    return [n for n in scan(text, locale, **kw) if n.status != "excluded"]


def excluded(text, locale="en", **kw):
    return {n.written: n.reason for n in scan(text, locale, **kw) if n.status == "excluded"}


def run_cli(args):
    """Run tieout.main in-process; returns (exit code, stdout text)."""
    out = io.StringIO()
    err = io.StringIO()
    with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
        code = tieout.main(list(args))
    return code, out.getvalue(), err.getvalue()
