"""Rebuild the test fixtures by trimming real downloads. Not run by the tests.

    python3 tests/fixtures/build_fixtures.py RAW_DIR

RAW_DIR holds the files as downloaded (2026-09-24):
  consolidated.xhtml   http://publications.europa.eu/resource/celex/02023R0956-20251020
  default_values.xlsx  https://taxation-customs.ec.europa.eu/document/download/1c05d211-80cb-4aaa-8ef0-e08005a95d7e_en
  oj_1740.xhtml        http://publications.europa.eu/resource/celex/32026R1740
  commission_page.html the CBAM legislation and guidance page
  sparql_*.json        answers to the queries in cbam_mcp/refresh.py
Every value in the fixtures is copied from these files; nothing is typed in.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
XH = "http://www.w3.org/1999/xhtml"
X = "{%s}" % XH
SML = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Lines of the default-value tables kept in the fixtures.
KEEP_LINES = {"2507008080", "2523100010", "2523100090", "25232100", "28041000", "7206", "72061000", "72069000",
              "7208", "7601", "761090", "76109010", "76109090", "26011200"}
KEEP_TABLES = {"India", "Türkiye", "Albania", "Other Countries and Territories", "Other countries and territories"}
# CN notations (prefixes) kept, with all their ancestors.
KEEP_CN = ("2507", "2523", "2716", "2804", "310510", "310560", "7202", "720410", "720851", "730820", "7317",
           "760110", "260112")


def strip_ws(el):
    for e in el.iter():
        if e.text is not None and not e.text.strip():
            e.text = None
        if e.tail is not None and not e.tail.strip():
            e.tail = None


def text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def find_div(root, div_id):
    return next((d for d in root.iter(X + "div") if d.get("id") == div_id), None)


def write_xhtml(root, path):
    strip_ws(root)
    ET.register_namespace("", XH)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(data)
    print(path.name, len(data))


def consolidated(raw: Path):
    root = ET.parse(raw).getroot()
    html = ET.Element(X + "html")
    ET.SubElement(ET.SubElement(html, X + "head"), X + "title").text = "Consolidated TEXT: 32023R0956 — EN — 20.10.2025 (trimmed)"
    body = ET.SubElement(html, X + "body")
    for p in root.iter(X + "p"):
        if p.get("class") in ("reference", "disclaimer"):
            body.append(p)
    marker = next(a for a in root.iter(X + "a") if (a.text or "").strip().startswith("►M1"))
    ET.SubElement(body, X + "p").append(marker)
    for art, keep in (("art_2", {"1", "4"}), ("art_2a", None), ("art_7", {"1"})):
        div = find_div(root, art)
        for block in list(div):
            nums = [text(s).rstrip(".") for s in block.iter(X + "span") if "no-parag" in (s.get("class") or "")]
            if keep is not None and block.tag == X + "div" and nums and nums[0] not in keep:
                div.remove(block)
            elif keep is not None and block.tag == X + "div" and not nums:
                div.remove(block)
        body.append(div)
    body.append(find_div(root, "anx_I"))
    annex_ii = find_div(root, "anx_II")
    for tbody in annex_ii.iter(X + "tbody"):
        for tr in list(tbody):
            first = text(tr)
            if not re.match(r"^(CN code|72 |7601 |2804 10 00|2716 00 00)", first):
                tbody.remove(tr)
    body.append(annex_ii)
    body.append(find_div(root, "anx_III"))
    annex_vii = find_div(root, "anx_VII")
    for child in list(annex_vii):
        if child.tag == X + "table" or (child.tag == X + "div" and not text(child).startswith("1.")):
            annex_vii.remove(child)
    body.append(annex_vii)
    write_xhtml(html, HERE / "consolidated_trimmed.xhtml")


def xlsx(raw: Path):
    z = zipfile.ZipFile(raw)
    shared = ["".join(t.text or "" for t in si.iter(SML + "t"))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(SML + "si")]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rmap = {r.get("Id"): r.get("Target") for r in rels}
    rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    out_sheets = []
    for s in wb.find(SML + "sheets"):
        name = s.get("name")
        target = "xl/" + rmap[s.get(rid)].lstrip("/").replace("xl/", "")
        sheet = ET.fromstring(z.read(target))
        rows = []
        for row in sheet.iter(SML + "row"):
            cells = []
            for c in row.findall(SML + "c"):
                v = c.find(SML + "v")
                val = shared[int(v.text)] if c.get("t") == "s" and v is not None else (v.text if v is not None else "")
                cells.append((c.get("r"), c.get("t") == "s", val))
            rows.append((int(row.get("r")), cells))
        title = next((v for _, cs in rows for r, _, v in cs if r == "A1"), name)
        if name in ("Overview", "Version History"):
            out_sheets.append((name, rows))
            continue
        if name != "Annex IV" and title not in KEEP_TABLES:
            continue
        kept, pending_cat = [], None
        for num, cells in rows:
            a = next((v for r, _, v in cells if r.startswith("A")), "")
            if num <= 2:
                kept.append((num, cells))
            elif re.fullmatch(r"[\d ]+", a or "x"):
                if a.replace(" ", "") in KEEP_LINES:
                    if pending_cat:
                        kept.append(pending_cat)
                        pending_cat = None
                    kept.append((num, cells))
            elif a:
                pending_cat = (num, cells)
        out_sheets.append((name, kept))
    strings = []
    index = {}
    for _, rows in out_sheets:
        for _, cells in rows:
            for _, is_s, val in cells:
                if is_s and val not in index:
                    index[val] = len(strings)
                    strings.append(val)
    path = HERE / "default_values_trimmed.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml",
                     '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/></Types>')
        out.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sheets_xml, rels_xml = [], []
        for i, (name, _) in enumerate(out_sheets, 1):
            sheets_xml.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
            rels_xml.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        out.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + "".join(sheets_xml) + "</sheets></workbook>")
        out.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     + "".join(rels_xml) + "</Relationships>")
        out.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                     + "".join(f"<si><t xml:space=\"preserve\">{escape(s)}</t></si>" for s in strings) + "</sst>")
        for i, (_, rows) in enumerate(out_sheets, 1):
            body = []
            for num, cells in rows:
                cs = []
                for ref, is_s, val in cells:
                    ref = re.sub(r"\d+$", str(num), ref)
                    if is_s:
                        cs.append(f'<c r="{ref}" t="s"><v>{index[val]}</v></c>')
                    elif val != "":
                        cs.append(f'<c r="{ref}"><v>{escape(val)}</v></c>')
                body.append(f'<row r="{num}">' + "".join(cs) + "</row>")
            out.writestr(f"xl/worksheets/sheet{i}.xml", '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                         + "".join(body) + "</sheetData></worksheet>")
    print(path.name, path.stat().st_size)


def oj(raw: Path):
    root = ET.parse(raw).getroot()
    html = ET.Element(X + "html")
    body = ET.SubElement(html, X + "body")
    quotes = ("Where a country or territory is not explicitly listed", "Where a country or territory is explicitly listed",
              "If no production route is indicated for a CN code", "The default values for direct emissions and indirect")
    for p in root.iter(X + "p"):
        t = text(p)
        found = [q for q in quotes if q in t]
        if found and len(t) < 1200:
            body.append(p)
            quotes = tuple(q for q in quotes if q not in found)
    current = None
    for table in root.iter(X + "table"):
        keep_rows = []
        mode_table = None
        for tr in table.iter(X + "tr"):
            tds = tr.findall(X + "td")
            vals = [text(td) for td in tds]
            if len(tds) == 1 and tds[0].get("colspan") and vals[0]:
                current = vals[0]
                keep_rows.append(tr)
                continue
            if vals and vals[0].startswith("Product CN Code"):
                if any("Highest default value" in v for v in vals):
                    current = "Annex IV"
                keep_rows.append(tr)
                continue
            if current and (current in KEEP_TABLES or current == "Annex IV"):
                code = vals[0].replace(" ", "") if vals else ""
                if code in KEEP_LINES:
                    keep_rows.append(tr)
                mode_table = current
        if mode_table and (mode_table in KEEP_TABLES or mode_table == "Annex IV"):
            new = ET.SubElement(body, X + "table")
            tb = ET.SubElement(new, X + "tbody")
            for tr in keep_rows:
                tb.append(tr)
    write_xhtml(html, HERE / "oj_1740_trimmed.xhtml")


def cn(full: Path, parents: Path, year: int):
    doc = json.loads(full.read_bytes())
    rows = doc["results"]["bindings"]
    by_id = {b["id"]["value"]: b for b in rows}
    keep = set()
    for cid, b in by_id.items():
        n = re.sub(r"\s", "", b.get("notation", {}).get("value", ""))
        if n and n.isdigit() and any(n.startswith(p) for p in KEEP_CN):
            while cid in by_id and cid not in keep:
                keep.add(cid)
                cid = by_id[cid].get("parent", {}).get("value")
    # unnumbered lines between kept codes and their parents
    for cid, b in by_id.items():
        if cid in keep:
            continue
        kids = [k for k, kb in by_id.items() if kb.get("parent", {}).get("value") == cid and k in keep]
        if kids:
            keep.add(cid)
    doc["results"]["bindings"] = [b for b in rows if b["id"]["value"] in keep]
    path = HERE / f"sparql_cn{year}_trimmed.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(path.name, path.stat().st_size, len(doc["results"]["bindings"]), "concepts")
    (HERE / f"sparql_cn{year}_parents.json").write_bytes(parents.read_bytes())


def page(raw: Path):
    t = raw.read_text(encoding="utf-8")
    i = t.find("Default values and benchmarks")
    j = t.find("Guidance documents", i)
    snippet = t[t.rfind("<", 0, i):j]
    path = HERE / "commission_page_trimmed.html"
    path.write_text("<!DOCTYPE html><html><body>" + snippet + "</body></html>\n", encoding="utf-8")
    print(path.name, path.stat().st_size)


if __name__ == "__main__":
    raw = Path(sys.argv[1])
    consolidated(raw / "consolidated.xhtml")
    xlsx(raw / "default_values.xlsx")
    oj(raw / "oj_1740.xhtml")
    for y in (2026, 2025):
        cn(raw / f"sparql_cn{y}_full.json", raw / f"sparql_cn{y}_parents.json", y)
    for name in ("sparql_consolidated.json", "sparql_later_acts.json"):
        (HERE / name).write_bytes((raw / name).read_bytes())
    page(raw / "commission_page.html")
