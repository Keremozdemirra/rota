"""A small, defensive .xlsx reader: zipfile plus xml.etree, standard library only.

It reads cell text and nothing else: no styles, no formulas (only their cached
results), no drawings, and no document properties, which can carry the names of
the people who last edited a file. Every part is size-capped while it is read,
and a part that declares a DTD is refused: a workbook never needs one, and
entity expansion is how an XML file becomes a memory bomb.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET

MAX_PART_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLS = 512

_REF = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d{1,7})$")


class XlsxError(Exception):
    """The file cannot be read as a workbook. The message says why and what to do."""


class Sheet:
    """One worksheet: its name, visibility and a sparse grid of cell text."""

    def __init__(self, name: str, state: str, rows: dict, merges: list):
        self.name = name
        self.state = state
        self.rows = rows          # {row number: {column index (0-based): text}}
        self.merges = merges      # [(first row, first col, last row, last col)]

    @property
    def hidden(self) -> bool:
        return self.state in ("hidden", "veryHidden")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def split_ref(ref: str):
    """'F3' -> (3, 5); None when the reference is not a plain cell reference."""
    m = _REF.match(ref or "")
    if not m:
        return None
    return int(m.group(2)), col_index(m.group(1))


def _read_part(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        with zf.open(name) as fh:
            # Read one byte past the cap instead of trusting the size the zip
            # directory declares, which a crafted file can understate.
            data = fh.read(MAX_PART_BYTES + 1)
    except KeyError:
        raise XlsxError(f"the workbook has no part {name!r}; it is incomplete or not an Excel workbook")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError, RuntimeError) as e:
        raise XlsxError(f"part {name!r} cannot be decompressed ({type(e).__name__}); the file is damaged, download it again")
    if len(data) > MAX_PART_BYTES:
        raise XlsxError(f"part {name!r} is larger than {MAX_PART_BYTES // (1024 * 1024)} MB; not a datapoint list")
    return data


def _parse_xml(data: bytes, name: str):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or data[:4] in (b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00"):
        raise XlsxError(f"part {name!r} is not UTF-8 encoded; this reader only handles UTF-8 parts")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise XlsxError(f"part {name!r} declares a DTD; refusing to parse it")
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise XlsxError(f"part {name!r} is not well-formed XML ({e}); the file is damaged, download it again")


def _rels(zf: zipfile.ZipFile, names: set, part: str) -> dict:
    """Relationship Id -> (Type, resolved target path) for one part."""
    rels_name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rels_name not in names:
        return {}
    root = _parse_xml(_read_part(zf, rels_name), rels_name)
    out = {}
    base = posixpath.dirname(part)
    for rel in root:
        if _local(rel.tag) != "Relationship" or rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target") or ""
        if target.startswith("/"):
            path = target[1:]
        else:
            path = posixpath.normpath(posixpath.join(base, target))
        out[rel.get("Id")] = (rel.get("Type") or "", path)
    return out


def _rich_text(el) -> str:
    """Text of a shared-string item or inline string: plain runs, rich-text runs, never phonetic runs."""
    parts = []
    for c in el:
        tag = _local(c.tag)
        if tag == "t":
            parts.append(c.text or "")
        elif tag == "r":
            t = _child(c, "t")
            if t is not None:
                parts.append(t.text or "")
    return "".join(parts)


def _number(v: str) -> str:
    v = (v or "").strip()
    try:
        f = float(v)
    except ValueError:
        return v
    if f.is_integer() and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


def _cell_text(c, shared: list) -> str:
    t = c.get("t") or "n"
    if t == "inlineStr":
        is_el = _child(c, "is")
        return _rich_text(is_el) if is_el is not None else ""
    v_el = _child(c, "v")
    v = v_el.text if v_el is not None and v_el.text is not None else ""
    if t == "s":
        try:
            i = int(v)
        except ValueError:
            return ""
        return shared[i] if 0 <= i < len(shared) else ""
    if t in ("str", "d"):
        return v
    if t == "b":
        return "TRUE" if v.strip() == "1" else "FALSE"
    if t == "e":
        return ""  # #VALUE!, #REF! and the like carry no content
    return _number(v) if v else ""


def _read_sheet(root, shared: list):
    rows: dict = {}
    merges: list = []
    sheet_data = _child(root, "sheetData")
    next_row = 1
    if sheet_data is not None:
        for row_el in _children(sheet_data, "row"):
            r_attr = row_el.get("r")
            rn = int(r_attr) if r_attr and r_attr.isdigit() else next_row
            next_row = rn + 1
            if rn > MAX_ROWS:
                break
            cells = {}
            next_col = 0
            for c in _children(row_el, "c"):
                ref = split_ref(c.get("r") or "")
                col = ref[1] if ref else next_col
                next_col = col + 1
                if col >= MAX_COLS:
                    continue
                text = _cell_text(c, shared)
                if text != "":
                    cells[col] = text
            if cells:
                rows[rn] = cells
    merge_el = _child(root, "mergeCells")
    if merge_el is not None:
        for m in _children(merge_el, "mergeCell"):
            ref = (m.get("ref") or "").split(":")
            if len(ref) != 2:
                continue
            a, b = split_ref(ref[0]), split_ref(ref[1])
            if not a or not b:
                continue
            r1, c1 = min(a[0], b[0]), min(a[1], b[1])
            r2, c2 = max(a[0], b[0]), max(a[1], b[1])
            merges.append((r1, c1, min(r2, MAX_ROWS), c2))
    _fill_merges(rows, merges)
    return rows, merges


def _fill_merges(rows: dict, merges: list, budget: int = 1_000_000) -> None:
    """Copy a merged value down the first column of its range, never across.

    A disclosure requirement code merged over several datapoint rows belongs to
    each of them. A title merged across a row belongs to no column but the
    first; spreading it sideways would turn a title into a fake datapoint.
    The budget bounds the work a file full of huge merged ranges can cause.
    """
    for r1, c1, r2, _c2 in merges:
        top = rows.get(r1, {}).get(c1)
        if top is None:
            continue
        for r in range(r1 + 1, r2 + 1):
            budget -= 1
            if budget < 0:
                return
            cells = rows.setdefault(r, {})
            if not cells.get(c1):
                cells[c1] = top


def read_workbook(path) -> list:
    """The visible and hidden worksheets of an .xlsx file, in workbook order."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except IsADirectoryError:
        raise XlsxError(f"{path} is a directory, not a workbook")
    except PermissionError:
        raise XlsxError(f"{path} cannot be read (permission denied)")
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise XlsxError(f"{path} is a legacy .xls workbook or a password-protected .xlsx; "
                        "open it in a spreadsheet program and save it as an unprotected .xlsx")
    if not head.startswith(b"PK"):
        raise XlsxError(f"{path} is not an .xlsx workbook (no zip signature); download the Excel file again")
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as e:
        raise XlsxError(f"{path} is a damaged or truncated .xlsx ({e}); download it again")
    with zf:
        names = set(zf.namelist())
        wb_part = "xl/workbook.xml"
        for _rid, (typ, target) in _rels(zf, names, "").items():
            if typ.endswith("/officeDocument"):
                wb_part = target
        if wb_part not in names:
            raise XlsxError(f"{path} has no workbook part; it is not an Excel workbook or it is damaged")
        wb = _parse_xml(_read_part(zf, wb_part), wb_part)
        rels = _rels(zf, names, wb_part)
        shared: list = []
        ss_part = next((t for typ, t in rels.values() if typ.endswith("/sharedStrings")), None)
        if ss_part is None and "xl/sharedStrings.xml" in names:
            ss_part = "xl/sharedStrings.xml"
        if ss_part and ss_part in names:
            ss = _parse_xml(_read_part(zf, ss_part), ss_part)
            shared = [_rich_text(si) for si in ss if _local(si.tag) == "si"]
        sheets_el = _child(wb, "sheets")
        out = []
        for s in (_children(sheets_el, "sheet") if sheets_el is not None else []):
            rid = next((v for k, v in s.attrib.items() if k.endswith("}id")), None)
            typ_target = rels.get(rid)
            if not typ_target or typ_target[1] not in names:
                continue  # a chart sheet or a dangling reference: nothing to read
            part = typ_target[1]
            if not typ_target[0].endswith("/worksheet") and not part.startswith("xl/worksheets/"):
                continue
            root = _parse_xml(_read_part(zf, part), part)
            rows, merges = _read_sheet(root, shared)
            out.append(Sheet(s.get("name") or "", s.get("state") or "visible", rows, merges))
        if not out:
            raise XlsxError(f"{path} contains no worksheet")
        return out
