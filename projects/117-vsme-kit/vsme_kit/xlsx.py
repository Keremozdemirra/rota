"""A small, read-only xlsx reader: workbook, sheets, defined names and cells, standard library only.

It reads what a spreadsheet application saved: values and the cached results of
formulas. It never evaluates a formula. Files come from users, so the reader is
defensive: size limits against zip bombs, no DTDs or entities in XML parts, and
every failure becomes a `WorkbookError` with a message a person can act on.
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# The tool's own limits, sized well above EFRAG's template (0.8 MB zipped, about 4 MB unzipped).
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 400 * 1024 * 1024
MAX_RATIO = 200

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CELL_REF = re.compile(r"^\$?([A-Z]{1,3})\$?(\d{1,7})$")


class WorkbookError(Exception):
    """The file cannot be read as an xlsx workbook; the message says why."""


class Uncached:
    """A formula cell saved without a result (the saving program did not calculate)."""

    def __repr__(self):
        return "Uncached()"


class CellError(str):
    """An Excel error value such as #DIV/0! or #REF!."""


UNCACHED = Uncached()


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def split_ref(ref: str):
    m = CELL_REF.match(ref.strip())
    if not m:
        raise ValueError(f"not a cell reference: {ref[:20]!r}")
    return col_index(m.group(1)), int(m.group(2))


def parse_range(text: str):
    """'A1' or '$A$1:$B$2' -> (col1, row1, col2, row2)."""
    parts = text.split(":")
    if len(parts) not in (1, 2):
        raise ValueError(f"not a range: {text[:40]!r}")
    c1, r1 = split_ref(parts[0])
    c2, r2 = split_ref(parts[-1])
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def parse_name_target(text: str):
    """"'Sheet A'!$A$1:$B$2" -> ('Sheet A', (c1, r1, c2, r2)); None for #REF!, constants or formulas."""
    if not text or "#REF!" in text:
        return None
    text = text.strip().split(",")[0]  # several areas: the first is enough here
    m = re.match(r"^(?:'((?:[^']|'')+)'|([^'!]+))!(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)$", text)
    if not m:
        return None
    sheet = (m.group(1) or m.group(2)).replace("''", "'")
    try:
        return sheet, parse_range(m.group(3))
    except ValueError:
        return None


def _xml(data: bytes, part: str):
    head = data[:2048]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data:
        raise WorkbookError(f"{part} declares a DTD or entities; the file was refused")
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise WorkbookError(f"{part} is not well-formed XML ({e})") from None


class Workbook:
    """Sheets, defined names and cell values of one xlsx file."""

    def __init__(self, path):
        self.path = str(path)
        if not os.path.exists(self.path):
            raise WorkbookError(f"no such file: {self.path}")
        if os.path.isdir(self.path):
            raise WorkbookError(f"is a directory, not a file: {self.path}")
        size = os.path.getsize(self.path)
        if size == 0:
            raise WorkbookError("the file is empty")
        if size > MAX_FILE_BYTES:
            raise WorkbookError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        with open(self.path, "rb") as fh:
            magic = fh.read(8)
        if magic == OLE_MAGIC:
            raise WorkbookError("this is an OLE2 file: a password-protected workbook or an old .xls file. "
                                "Save it as an unprotected .xlsx workbook and try again")
        if not magic.startswith(b"PK"):
            raise WorkbookError("not an xlsx file (no zip signature)")
        try:
            self._zip = zipfile.ZipFile(self.path)
            infos = self._zip.infolist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError) as e:
            raise WorkbookError(f"the zip container is damaged ({e})") from None
        total = 0
        for info in infos:
            if info.file_size > MAX_PART_BYTES:
                raise WorkbookError(f"part {info.filename[:60]} unpacks to more than "
                                    f"{MAX_PART_BYTES // (1024 * 1024)} MB; refused")
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1024 * 1024:
                raise WorkbookError(f"part {info.filename[:60]} has a compression ratio above {MAX_RATIO}; refused")
            total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise WorkbookError("the workbook unpacks to more than "
                                f"{MAX_TOTAL_BYTES // (1024 * 1024)} MB; refused")
        self._names = {i.filename for i in infos}
        if "xl/workbook.xml" not in self._names:
            raise WorkbookError("not an Excel workbook: xl/workbook.xml is missing")
        self._cells = {}
        self._load_workbook()
        self.shared_strings = self._load_shared_strings()

    # ------------------------------------------------------------ parts

    def _read(self, part: str) -> bytes:
        try:
            return self._zip.read(part)
        except KeyError:
            raise WorkbookError(f"{part} is missing from the workbook") from None
        except (zipfile.BadZipFile, OSError, ValueError, EOFError) as e:
            raise WorkbookError(f"{part} cannot be unpacked ({type(e).__name__}: {e})") from None
        except Exception as e:  # zlib.error and friends from a truncated archive
            raise WorkbookError(f"{part} cannot be unpacked ({type(e).__name__})") from None

    def _load_workbook(self):
        root = _xml(self._read("xl/workbook.xml"), "xl/workbook.xml")
        rels = {}
        if "xl/_rels/workbook.xml.rels" in self._names:
            for rel in _xml(self._read("xl/_rels/workbook.xml.rels"), "workbook relationships"):
                target = rel.get("Target") or ""
                target = target.lstrip("/") if target.startswith("/") else "xl/" + target
                rels[rel.get("Id")] = os.path.normpath(target).replace(os.sep, "/")
        self.sheets = []  # (name, part, state)
        sheets = root.find(M + "sheets")
        for s in (sheets if sheets is not None else []):
            part = rels.get(s.get(R + "id"))
            self.sheets.append((s.get("name") or "", part, s.get("state") or "visible"))
        if not self.sheets:
            raise WorkbookError("the workbook lists no sheets")
        self.defined_names = {}
        names = root.find(M + "definedNames")
        for d in (names if names is not None else []):
            name = d.get("name") or ""
            local = d.get("localSheetId")
            key = name if local is None else f"{name}@{local}"
            self.defined_names[key] = (d.text or "").strip()

    def _load_shared_strings(self) -> list:
        if "xl/sharedStrings.xml" not in self._names:
            return []
        root = _xml(self._read("xl/sharedStrings.xml"), "xl/sharedStrings.xml")
        out = []
        for si in root.findall(M + "si"):
            # rich text runs are joined; phonetic runs (rPh) are not part of the text
            parts = [t.text or "" for t in si.findall(M + "t")]
            for r in si.findall(M + "r"):
                parts.extend(t.text or "" for t in r.findall(M + "t"))
            out.append("".join(parts))
        return out

    # ------------------------------------------------------------ lookups

    @property
    def sheet_names(self) -> list:
        return [s[0] for s in self.sheets]

    def has_sheet(self, name: str) -> bool:
        return any(s[0] == name for s in self.sheets)

    def name(self, name: str):
        """(sheet, (c1, r1, c2, r2)) of a workbook-level defined name, else None."""
        text = self.defined_names.get(name)
        if text is None:
            # a sheet-scoped name with the same spelling is accepted as well
            for key, value in self.defined_names.items():
                if key.split("@")[0] == name:
                    text = value
                    break
        return parse_name_target(text) if text else None

    def cells(self, sheet: str) -> dict:
        """{(col, row): (value, formula)} for one sheet, parsed on first use."""
        if sheet in self._cells:
            return self._cells[sheet]
        part = next((p for n, p, _ in self.sheets if n == sheet), None)
        if part is None:
            raise WorkbookError(f"no sheet named {sheet!r}")
        root = _xml(self._read(part), f"sheet {sheet!r}")
        out = {}
        for c in root.iter(M + "c"):
            ref = c.get("r")
            if not ref:
                continue
            try:
                pos = split_ref(ref)
            except ValueError:
                continue
            f = c.find(M + "f")
            formula = f.text if f is not None and f.text else ("" if f is not None else None)
            out[pos] = (self._value(c, formula), formula)
        self._cells[sheet] = out
        return out

    def _value(self, c, formula):
        t = c.get("t") or "n"
        v = c.find(M + "v")
        text = v.text if v is not None else None
        if t == "inlineStr":
            node = c.find(M + "is")
            return "".join(x.text or "" for x in node.iter(M + "t")) if node is not None else ""
        if v is None:
            return UNCACHED if formula is not None else None
        if text is None:  # <v></v>: a formula whose result is an empty string
            return ""
        if t == "s":
            try:
                return self.shared_strings[int(text)]
            except (ValueError, IndexError):
                return CellError("#BADSTRING")
        if t == "b":
            return text.strip() in ("1", "true", "TRUE")
        if t == "e":
            return CellError(text)
        if t in ("str", "d"):
            return text
        try:
            number = float(text)
        except ValueError:
            return text
        return int(number) if number.is_integer() and abs(number) < 1e15 else number

    def value(self, sheet: str, col: int, row: int):
        return self.cells(sheet).get((col, row), (None, None))[0]

    def formula(self, sheet: str, col: int, row: int):
        return self.cells(sheet).get((col, row), (None, None))[1]

    def row(self, sheet: str, row: int) -> list:
        """[(col, value, formula)] of one row, left to right."""
        return sorted((c, v, f) for (c, r), (v, f) in self.cells(sheet).items() if r == row)

    def close(self):
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
