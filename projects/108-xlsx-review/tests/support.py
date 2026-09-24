"""Test helpers: a scratch $HOME for every test, and a small standard-library writer for .xlsx
packages, so each test builds exactly the XML it is about (shared formulas as Excel writes them,
a missing sharedStrings part, UTF-16 parts, broken zips). No network, no openpyxl."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import xlsx_review  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


class Case(unittest.TestCase):
    """Every test runs with $HOME and Path.home() on an empty scratch directory: nothing under the
    real home directory is ever read."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("XLSX_REVIEW_DEBUG", None)
        home = mock.patch("pathlib.Path.home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def write(self, name: str, data: bytes) -> str:
        path = self.tmp / name
        path.write_bytes(data)
        return str(path)

    def book(self, name: str = "book.xlsx", **kw) -> str:
        return self.write(name, workbook(**kw))


def _cell_xml(addr: str, spec, strings: list) -> str:
    """One <c> element from a short spec:
    3.5 / True             a number / a boolean
    "text"                 a shared string (or inline string when strings is None)
    "=A1*2"                a formula without a cached value
    ("=A1*2", 20)          a formula with a cached number
    ("=A1&\"x\"", "ax")    a formula with a cached text result
    ("=1/0", "#DIV/0!")    a formula with a cached error
    ("error", "#N/A")      an error typed as a constant
    ("raw", "<c .../>")    XML written as given
    """
    if isinstance(spec, tuple) and spec and spec[0] == "raw":
        return spec[1]
    if isinstance(spec, tuple) and spec and spec[0] == "error":
        return f'<c r="{addr}" t="e"><v>{escape(spec[1])}</v></c>'
    if isinstance(spec, tuple):
        formula, cached = spec
        f = f"<f>{escape(formula[1:])}</f>"
        if isinstance(cached, bool):
            return f'<c r="{addr}" t="b">{f}<v>{int(cached)}</v></c>'
        if isinstance(cached, (int, float)):
            return f'<c r="{addr}">{f}<v>{cached!r}</v></c>'
        if isinstance(cached, str) and cached.startswith("#"):
            return f'<c r="{addr}" t="e">{f}<v>{escape(cached)}</v></c>'
        return f'<c r="{addr}" t="str">{f}<v>{escape(cached)}</v></c>'
    if isinstance(spec, bool):
        return f'<c r="{addr}" t="b"><v>{int(spec)}</v></c>'
    if isinstance(spec, (int, float)):
        return f'<c r="{addr}"><v>{spec!r}</v></c>'
    if isinstance(spec, str) and spec.startswith("="):
        return f'<c r="{addr}"><f>{escape(spec[1:])}</f></c>'
    if strings is None:
        return f'<c r="{addr}" t="inlineStr"><is><t>{escape(spec)}</t></is></c>'
    if spec not in strings:
        strings.append(spec)
    return f'<c r="{addr}" t="s"><v>{strings.index(spec)}</v></c>'


def sheet_xml(cells: dict, strings: list = None, extra: str = "") -> str:
    rows: dict = {}
    for addr, spec in cells.items():
        r, c = xlsx_review.parse_cell(addr)
        rows.setdefault(r, []).append((c, addr, spec))
    body = []
    for r in sorted(rows):
        inner = "".join(_cell_xml(addr, spec, strings) for c, addr, spec in sorted(rows[r], key=lambda x: x[0]))
        body.append(f'<row r="{r}">{inner}</row>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{NS}" xmlns:r="{R_NS}"><sheetData>{"".join(body)}</sheetData>{extra}</worksheet>')


def workbook(sheets=None, names=(), links=(), vba: bytes = None, calc: str = "", app: str = "xlsx-review test fixture",
             shared_strings: bool = True, workbook_xml: bytes = None, drop=(), replace=None, extra_parts=None) -> bytes:
    """A complete .xlsx package as bytes.

    sheets: [{"name": ..., "state": "hidden", "cells": {"A1": spec}, "xml": "<worksheet>...", "extra": "<mergeCells/>"}]
    names:  [("Growth", "Inputs!$B$2"), ("Local", "Model!$A$1", 1)]   (third item: localSheetId)
    links:  ["file:///C:/data/fx.xlsx", ("dde", "cmd", "/c calc")]
    drop:   part names left out of the zip; replace: {part: bytes} written instead of the generated part.
    """
    sheets = sheets if sheets is not None else [{"name": "Sheet1", "cells": {"A1": 1}}]
    strings: list = [] if shared_strings else None
    parts: dict = {}
    wb_rels = []
    sheet_tags = []
    for i, s in enumerate(sheets, 1):
        xml = s.get("xml") or sheet_xml(s.get("cells", {}), strings, s.get("extra", ""))
        parts[f"xl/worksheets/sheet{i}.xml"] = xml.encode("utf-8") if isinstance(xml, str) else xml
        wb_rels.append((f"rId{i}", f"{REL}/worksheet", f"worksheets/sheet{i}.xml", None))
        state = f' state="{s["state"]}"' if s.get("state") else ""
        sid = s.get("sheet_id", i)
        sheet_tags.append(f'<sheet name={quoteattr(s["name"])} sheetId="{sid}"{state} r:id="rId{i}"/>')
    n = len(sheets)
    ext_refs = []
    for j, link in enumerate(links, 1):
        rid = f"rId{n + 10 + j}"
        wb_rels.append((rid, f"{REL}/externalLink", f"externalLinks/externalLink{j}.xml", None))
        ext_refs.append(f'<externalReference r:id="{rid}"/>')
        if isinstance(link, tuple) and link[0] == "dde":
            body = f'<ddeLink ddeService={quoteattr(link[1])} ddeTopic={quoteattr(link[2])}/>'
            parts[f"xl/externalLinks/externalLink{j}.xml"] = (
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<externalLink xmlns="{NS}">{body}</externalLink>').encode()
            continue
        parts[f"xl/externalLinks/externalLink{j}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<externalLink xmlns="{NS}" xmlns:r="{R_NS}">'
            f'<externalBook r:id="rId1"><sheetNames><sheetName val="Rates"/></sheetNames></externalBook></externalLink>').encode()
        parts[f"xl/externalLinks/_rels/externalLink{j}.xml.rels"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">'
            f'<Relationship Id="rId1" Type="{REL}/externalLinkPath" Target={quoteattr(link)} TargetMode="External"/>'
            f'</Relationships>').encode()
    if strings is not None:
        sst = "".join(f"<si><t xml:space=\"preserve\">{escape(s)}</t></si>" for s in strings)
        parts["xl/sharedStrings.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="{NS}" count="{len(strings)}" '
            f'uniqueCount="{len(strings)}">{sst}</sst>').encode()
        wb_rels.append((f"rId{n + 1}", f"{REL}/sharedStrings", "sharedStrings.xml", None))
    parts["xl/styles.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{NS}">'
                              '<fonts count="1"><font/></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders>'
                              '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf/></cellXfs></styleSheet>').encode()
    wb_rels.append((f"rId{n + 2}", f"{REL}/styles", "styles.xml", None))
    if vba is not None:
        parts["xl/vbaProject.bin"] = vba
        wb_rels.append((f"rId{n + 3}", "http://schemas.microsoft.com/office/2006/relationships/vbaProject", "vbaProject.bin", None))
    name_tags = []
    for item in names:
        name, formula = item[0], item[1]
        local = f' localSheetId="{item[2]}"' if len(item) > 2 and item[2] is not None else ""
        name_tags.append(f"<definedName name={quoteattr(name)}{local}>{escape(formula)}</definedName>")
    if workbook_xml is None:
        workbook_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{NS}" xmlns:r="{R_NS}">'
                        f'<sheets>{"".join(sheet_tags)}</sheets>'
                        + (f'<definedNames>{"".join(name_tags)}</definedNames>' if name_tags else "")
                        + (calc or '<calcPr calcId="191029"/>')
                        + (f'<externalReferences>{"".join(ext_refs)}</externalReferences>' if ext_refs else "")
                        + "</workbook>").encode()
    parts["xl/workbook.xml"] = workbook_xml
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">'
        + "".join(f'<Relationship Id="{i}" Type="{t}" Target="{tg}"/>' for i, t, tg, _ in wb_rels)
        + "</Relationships>").encode()
    parts["docProps/app.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns='
        '"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f"<Application>{escape(app)}</Application></Properties>").encode()
    parts["_rels/.rels"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PKG_REL}">'
        f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>'
        f'<Relationship Id="rId2" Type="{REL}/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>").encode()
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, n + 1))
    main_type = ("application/vnd.ms-excel.sheet.macroEnabled.main+xml" if vba is not None
                 else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{main_type}"/>{overrides}</Types>').encode()
    for k, v in (replace or {}).items():
        parts[k] = v
    for k, v in (extra_parts or {}).items():
        parts[k] = v
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["[Content_Types].xml", "_rels/.rels"] + sorted(p for p in parts if p not in ("[Content_Types].xml", "_rels/.rels")):
            if name in parts and name not in drop:
                z.writestr(name, parts[name])
    return buf.getvalue()
