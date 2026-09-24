"""Turn the raw source files into the tables this tool answers from.

Pure functions over bytes: no network, no files. Everything that can go wrong
with a download that is not what it claims to be (an HTML error page instead
of XHTML, a truncated zip, a JSON body that is empty or not UTF-8) ends in a
ParseError with a sentence a person can act on, never in a traceback.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET

from .remote import clean

X = "{http://www.w3.org/1999/xhtml}"
SML = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# A sane upper bound for what a spreadsheet of default values unpacks to. The
# real file (2026-08-06) unpacks to about 9 MB; a zip bomb unpacks to gigabytes.
MAX_XLSX_UNPACKED = 200 * 1024 * 1024

_CODE_LINE = re.compile(r"^(?P<ex>ex\s+)?(?P<code>[0-9](?:[0-9\s]*[0-9])?)\s*[–—\-]\s*(?P<desc>.*)$", re.S)
_EXCEPT = re.compile(r"^Except\s*:\s*(?P<rest>.*)$", re.S | re.I)
_TABLE_CODE = re.compile(r"^[0-9][0-9 ]*$")
_MARKERS = str.maketrans({"►": " ", "◄": " ", "▼": " "})


class ParseError(ValueError):
    """The source file is not what this parser knows how to read."""


def _clean(text: str) -> str:
    return clean(text.translate(_MARKERS), None)


def _xml(raw: bytes, what: str):
    if not raw or not raw.strip():
        raise ParseError(f"{what}: empty document")
    # Entity declarations are how XML entity-expansion attacks start; none of the
    # sources uses them, so refuse rather than trust the parser's limits.
    if b"<!ENTITY" in raw:
        raise ParseError(f"{what}: document declares XML entities, refused")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        raise ParseError(f"{what}: not well-formed XML ({e})") from None


def _is_marker(el) -> bool:
    # The marker text sits in a nested span: <a title="32025R2083: REPLACED"><span>►M1</span></a>
    return el.tag == X + "a" and "".join(el.itertext()).strip()[:1] in ("►", "▼")


def _collect(el, parts: list, markers: list) -> None:
    if _is_marker(el):
        title = el.get("title") or ""
        m = re.match(r"(3\d{4}[A-Z]\d{4})", title)
        if m:
            markers.append(m.group(1))
        return
    if el.text:
        parts.append(el.text)
    for child in el:
        _collect(child, parts, markers)
        if child.tail:
            parts.append(child.tail)


def text_of(el, markers: list | None = None) -> str:
    """Visible text of an element without the ►M1/▼B amendment markers."""
    parts: list = []
    _collect(el, parts, markers if markers is not None else [])
    return _clean("".join(parts))


# ------------------------------------------------------ regulation (XHTML)

def _find_div(root, div_id: str):
    for div in root.iter(X + "div"):
        if div.get("id") == div_id:
            return div
    return None


def _heading(el) -> str | None:
    """A goods-category heading: a paragraph outside tables that is one bold phrase."""
    if el.tag != X + "p":
        return None
    bold = [s for s in el.iter(X + "span") if "boldface" in (s.get("class") or "")]
    if not bold:
        return None
    text = text_of(el)
    if not text or len(text) > 60 or text != text_of(bold[0]):
        return None
    return text


def _parse_code_line(text: str) -> dict | None:
    m = _CODE_LINE.match(text)
    if not m:
        return None
    code = re.sub(r"\s", "", m.group("code"))
    desc = m.group("desc").strip()
    line = {"code": code, "ex": bool(m.group("ex")), "description": desc}
    if desc.endswith(":"):
        # "7202 99 – Other:" introduces the codes listed under it; it is not an
        # exception of its own.
        line["heading_only"] = True
    return line


def _parse_row(tr, category: str) -> list[dict]:
    tds = tr.findall(X + "td")
    if len(tds) < 2:
        return []
    markers: list = []
    lines = [text_of(p, markers) for p in tds[0].iter(X + "p")]
    lines = [t for t in lines if t]
    if not lines or lines[0].lower() == "cn code":
        return []
    gas = text_of(tds[1], markers)
    entries: list[dict] = []
    in_except = False
    for text in lines:
        m = _EXCEPT.match(text)
        if m:
            in_except = True
            text = m.group("rest").strip()
            if not text:
                continue
        line = _parse_code_line(text)
        if line is None:
            continue
        if in_except:
            if not entries:
                continue
            line.pop("ex", None)
            entries[-1]["except"].append(line)
        else:
            line.update({"category": category, "greenhouse_gases": gas, "except": []})
            entries.append(line)
    amended = sorted(set(m for m in markers if m != "32023R0956"))
    for e in entries:
        e["amended_by"] = amended
    return entries


def _annex_table(div) -> list[dict]:
    entries: list[dict] = []
    category = ""

    def walk(el):
        nonlocal category
        if el.tag == X + "table":
            for tr in el.iter(X + "tr"):
                entries.extend(_parse_row(tr, category))
            return
        h = _heading(el)
        if h:
            category = h
            return
        for child in el:
            walk(child)

    walk(div)
    return entries


def _article_paragraphs(div) -> dict:
    out = {}
    for block in div:
        if block.tag != X + "div" or "norm" not in (block.get("class") or ""):
            continue
        num = None
        for span in block.iter(X + "span"):
            if "no-parag" in (span.get("class") or ""):
                num = text_of(span).rstrip(".")
                break
        if not num:
            continue
        text = text_of(block)
        out[num] = _clean(text[len(num) + 1:] if text.startswith(num + ".") else text)
    return out


def _numbered_points(div) -> dict:
    out = {}
    for p in div.iter(X + "p"):
        text = text_of(p)
        m = re.match(r"^(\d+)\.\s*(.+)$", text)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def _annex_iii_point_1(div) -> dict:
    countries, territories, current = [], [], None
    for el in div.iter():
        if el.tag == X + "p":
            text = text_of(el)
            if text.startswith("2.") or "ELECTRICITY" in text:
                break
            if "following countries" in text:
                current = countries
            elif "following territories" in text:
                current = territories
        elif el.tag == X + "div" and (el.get("class") or "") == "list" and current is not None:
            name = text_of(el)
            if name:
                current.append(name)
    return {"countries": countries, "territories": territories}


def _doc_header(root) -> dict:
    """Reference line, disclaimer and amending acts (M1 = CELEX) of a consolidated text."""
    ref = [text_of(p) for p in root.iter(X + "p") if (p.get("class") or "") == "reference"]
    disc = [text_of(p) for p in root.iter(X + "p") if (p.get("class") or "") == "disclaimer"]
    amendments = {}
    for a in root.iter(X + "a"):
        t = "".join(a.itertext()).strip()
        m = re.match(r"^►(M\d+)$", t)
        href = a.get("href") or ""
        if m and "/celex/" in href and m.group(1) not in amendments:
            amendments[m.group(1)] = href.rsplit("/", 1)[-1]
    return {"reference": ref[0] if ref else None, "disclaimer": disc[0] if disc else None, "amendments": amendments}


def parse_regulation_xhtml(raw: bytes) -> dict:
    """Annexes I, II, III (point 1) and the de minimis texts of the consolidated CBAM Regulation."""
    try:
        return _parse_regulation(raw)
    except RecursionError:
        raise ParseError("consolidated regulation: elements nested too deeply, refused") from None


def _parse_regulation(raw: bytes) -> dict:
    root = _xml(raw, "consolidated regulation")
    annex_i = _find_div(root, "anx_I")
    annex_ii = _find_div(root, "anx_II")
    if annex_i is None or annex_ii is None:
        raise ParseError("consolidated regulation: no Annex I/II division (div id='anx_I'); the layout changed")
    out = {"annex_i": _annex_table(annex_i), "annex_ii": _annex_table(annex_ii)}
    # Floor chosen by this tool: the 2025-10-20 text has 6 categories and 43 lines;
    # far fewer means the parser missed tables, not that the law shrank.
    cats = {e["category"] for e in out["annex_i"]}
    if len(out["annex_i"]) < 20 or len(cats) < 5 or "" in cats:
        raise ParseError(f"consolidated regulation: Annex I parsed into {len(out['annex_i'])} lines "
                         f"in {len(cats)} categories; the layout changed")
    intro = [text_of(p) for p in annex_i.iter(X + "p") if re.match(r"^\d\.", text_of(p))]
    out["annex_i_intro"] = intro[:2]
    header = _doc_header(root)
    out["reference"], out["disclaimer"] = header["reference"], header["disclaimer"]
    quotes = {}
    for art, key, para in (("art_2", "article_2_1", "1"), ("art_2", "article_2_4", "4"),
                           ("art_2a", "article_2a_1", "1"), ("art_2a", "article_2a_4", "4"),
                           ("art_7", "article_7_1", "1")):
        div = _find_div(root, art)
        if div is not None:
            text = _article_paragraphs(div).get(para)
            if text:
                quotes[key] = text
    annex_vii = _find_div(root, "anx_VII")
    if annex_vii is not None:
        point1 = _numbered_points(annex_vii).get("1")
        if point1:
            quotes["annex_vii_1"] = point1
    out["quotes"] = quotes
    annex_iii = _find_div(root, "anx_III")
    out["annex_iii_point_1"] = _annex_iii_point_1(annex_iii) if annex_iii is not None else None
    out["amendments"] = header["amendments"]
    return out


# ------------------------------------------------------ default values (XLSX)

def _zip_xml(zf: zipfile.ZipFile, name: str):
    try:
        raw = zf.read(name)
    except KeyError:
        raise ParseError(f"spreadsheet: part {name} is missing") from None
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as e:
        raise ParseError(f"spreadsheet: part {name} cannot be read ({e})") from None
    return _xml(raw, f"spreadsheet part {name}")


def _sheet_cells(zf, target: str, shared: list) -> dict:
    root = _zip_xml(zf, target)
    cells = {}
    for c in root.iter(SML + "c"):
        ref = c.get("r") or ""
        m = re.match(r"^([A-Z]{1,3})(\d+)$", ref)
        if not m:
            continue
        kind = c.get("t")
        v = c.find(SML + "v")
        if kind == "s" and v is not None:
            try:
                val = shared[int(v.text)]
            except (ValueError, IndexError, TypeError):
                raise ParseError(f"spreadsheet: cell {ref} points to a missing shared string") from None
        elif kind == "inlineStr":
            val = "".join(t.text or "" for t in c.iter(SML + "t"))
        else:
            val = v.text if v is not None and v.text is not None else ""
        cells[(int(m.group(2)), m.group(1))] = val.strip()
    return cells


def _excel_date(value: str) -> str | None:
    try:
        serial = float(value)
    except ValueError:
        return value or None
    # Spreadsheet serial dates count days from 1899-12-30.
    return (dt.date(1899, 12, 30) + dt.timedelta(days=int(serial))).isoformat()


def _columns(cells: dict, header_row: int) -> dict:
    cols = {}
    for (row, col), text in cells.items():
        if row != header_row:
            continue
        low = text.lower()
        if "cn code" in low:
            cols["code"] = col
        elif low.startswith("description"):
            cols["description"] = col
        elif "indirect emissions" in low:
            cols["indirect"] = col
        elif "direct emissions" in low:
            cols["direct"] = col
        elif "total emissions" in low:
            cols["total"] = col
        elif "highest default value" in low:
            cols["highest"] = col
        elif "production route" in low:
            cols["route"] = col
    return cols


def parse_default_values_xlsx(raw: bytes) -> dict:
    """Country tables, Annex IV, version and disclaimer of the Commission's default-value Excel."""
    if not raw:
        raise ParseError("spreadsheet: empty file")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise ParseError(f"spreadsheet: not an xlsx (zip) file ({e})") from None
    if sum(i.file_size for i in zf.infolist()) > MAX_XLSX_UNPACKED:
        raise ParseError("spreadsheet: unpacks to more than 200 MB, refused")
    shared: list = []
    if "xl/sharedStrings.xml" in zf.namelist():
        for si in _zip_xml(zf, "xl/sharedStrings.xml").findall(SML + "si"):
            shared.append("".join(t.text or "" for t in si.iter(SML + "t")))
    wb = _zip_xml(zf, "xl/workbook.xml")
    rels = _zip_xml(zf, "xl/_rels/workbook.xml.rels")
    targets = {r.get("Id"): r.get("Target") or "" for r in rels.findall(PKG_REL + "Relationship")}
    sheets = []
    sheets_el = wb.find(SML + "sheets")
    for s in (sheets_el if sheets_el is not None else []):
        target = targets.get(s.get(DOC_REL + "id"), "").lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((s.get("name") or "", target))
    if not sheets:
        raise ParseError("spreadsheet: workbook lists no sheets")

    out = {"disclaimer": None, "versions": [], "tables": {}, "annex_iv": {}, "lines": {}, "sheet_count": len(sheets)}
    order: list[str] = []
    for name, target in sheets:
        cells = _sheet_cells(zf, target, shared)
        if not cells:
            continue
        low = name.strip().lower()
        if low == "overview":
            texts = [t for t in cells.values() if "legally" in t.lower()]
            out["disclaimer"] = _clean(texts[0]) if texts else None
            continue
        if low == "version history":
            for (row, col), text in sorted(cells.items()):
                if col == "A" and re.fullmatch(r"\d+", text):
                    out["versions"].append({"version": text, "date": _excel_date(cells.get((row, "B"), "")),
                                            "note": _clean(cells.get((row, "C"), ""))})
            continue
        cols = _columns(cells, 2)
        is_annex_iv = "highest" in cols
        needed = ("code", "description", "highest") if is_annex_iv else ("code", "description", "direct", "indirect", "total")
        missing = [k for k in needed if k not in cols]
        if missing:
            raise ParseError(f"spreadsheet: sheet {name!r} has no column for {', '.join(missing)}")
        title = _clean(cells.get((1, "A")) or name)
        rows = {}
        category = ""
        last_row = max(r for r, _ in cells)
        for r in range(3, last_row + 1):
            code_text = cells.get((r, cols["code"]), "")
            if not code_text:
                continue
            if not _TABLE_CODE.match(code_text):
                if not any(cells.get((r, cols[k]), "") for k in cols if k != "code"):
                    category = _clean(code_text)
                continue
            code = code_text.replace(" ", "")
            if code not in out["lines"]:
                out["lines"][code] = {"display": _clean(code_text), "description": _clean(cells.get((r, cols["description"]), "")),
                                      "category": category}
                order.append(code)
            route = cells.get((r, cols["route"]), "") if "route" in cols else ""
            if is_annex_iv:
                rows[code] = [cells.get((r, cols["highest"]), ""), route]
            else:
                rows[code] = [cells.get((r, cols[k]), "") for k in ("direct", "indirect", "total")] + [route]
        if is_annex_iv:
            out["annex_iv"] = rows
        else:
            if title in out["tables"]:
                raise ParseError(f"spreadsheet: two sheets for {title!r}")
            out["tables"][title] = rows
    if not out["tables"]:
        raise ParseError("spreadsheet: no country sheets found")
    others = [t for t in out["tables"] if t.lower().startswith("other countries")]
    if len(others) != 1:
        raise ParseError("spreadsheet: no single 'Other countries and territories' sheet")
    out["other_table"] = others[0]
    # Sheets list only the lines they have values for, in one common order;
    # the fullest sheet gives that order, the rest keeps first appearance.
    fullest = max(list(out["tables"].values()) + [out["annex_iv"]], key=len)
    out["order"] = [c for c in fullest] + [c for c in order if c not in fullest]
    return out


def parse_value(text: str):
    """(number or None, kind) for a cell of the default-value tables.

    The tables write decimals with a comma ("1,870" is 1.87 tCO2e per tonne).
    """
    t = (text or "").strip()
    if re.fullmatch(r"\d+,\d+", t):
        return float(t.replace(",", ".")), "value"
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return float(t), "value"
    if t in ("-", "–", "—"):
        return None, "dash"
    if t.upper() == "N/A":
        return None, "not_applicable"
    if t.lower() == "see below":
        return None, "see_below"
    if not t:
        return None, "empty"
    return None, "unrecognised"


# ------------------------------------------------------ CN (SPARQL JSON)

def sparql_rows(raw: bytes, what: str) -> list[dict]:
    if not raw or not raw.strip():
        raise ParseError(f"{what}: empty response")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ParseError(f"{what}: response is not UTF-8") from None
    except json.JSONDecodeError as e:
        raise ParseError(f"{what}: response is not JSON ({e.msg})") from None
    try:
        bindings = doc["results"]["bindings"]
    except (TypeError, KeyError):
        raise ParseError(f"{what}: not a SPARQL JSON result") from None
    if not isinstance(bindings, list):
        raise ParseError(f"{what}: not a SPARQL JSON result")
    rows = []
    for b in bindings:
        if isinstance(b, dict):
            rows.append({k: v.get("value") for k, v in b.items() if isinstance(v, dict)})
    return rows


def parse_cn_rows(rows: list[dict]) -> dict:
    """id -> [notation digits, label, indent, self-explanatory text, parent id, depth]."""
    out = {}
    for r in rows:
        cid = (r.get("id") or "").strip()
        if not re.fullmatch(r"\d{12}", cid):
            continue
        label = _clean(r.get("label") or "")
        m = re.match(r"^(-+)\s*", label)
        indent = len(m.group(1)) if m else 0
        label = label[m.end():] if m else label
        notation = re.sub(r"\s", "", r.get("notation") or "")
        try:
            depth = int(r.get("depth") or 0)
        except ValueError:
            depth = 0
        out[cid] = [notation, label, indent, _clean(r.get("note") or ""), (r.get("parent") or "").strip(), depth]
    return out


# ------------------------------------------------------ Official Journal tables

def parse_oj_default_values(raw: bytes) -> dict:
    """Country tables, Annex IV and paragraphs of the default-value act (OJ or consolidated XHTML)."""
    try:
        return _parse_oj(raw)
    except RecursionError:
        raise ParseError("Official Journal text: elements nested too deeply, refused") from None


def _parse_oj(raw: bytes) -> dict:
    root = _xml(raw, "Official Journal text")
    tables: dict = {}
    annex_iv: dict = {}
    current = None
    mode = None
    for table in root.iter(X + "table"):
        for tr in table.iter(X + "tr"):
            tds = tr.findall(X + "td")
            vals = [text_of(td) for td in tds]
            if len(tds) == 1 and tds[0].get("colspan"):
                if vals[0]:
                    current = vals[0].replace("’", "'")
                    mode = "country"
                    tables.setdefault(current, {})
                continue
            if vals and vals[0].startswith("Product CN Code"):
                if any("Highest default value" in v for v in vals):
                    mode, current = "annex_iv", None
                continue
            if not vals or not _TABLE_CODE.match(vals[0] or "x"):
                continue
            code = vals[0].replace(" ", "")
            cells = [v.replace("–", "-") for v in vals[2:]]
            if mode == "country" and current and len(cells) >= 4:
                tables[current][code] = cells[:4]
            elif mode == "annex_iv" and len(cells) >= 2:
                annex_iv[code] = cells[:2]
    if not tables:
        raise ParseError("Official Journal text: no default-value tables found")
    # Long paragraphs only: the rules sit in the annexes' introductory paragraphs, and
    # skipping short table cells keeps the list small.
    paragraphs = [t for t in (text_of(p) for p in root.iter(X + "p")) if len(t) >= 40]
    return {"tables": tables, "annex_iv": annex_iv, "text": _clean("".join(root.itertext())),
            "paragraphs": paragraphs, **_doc_header(root)}
