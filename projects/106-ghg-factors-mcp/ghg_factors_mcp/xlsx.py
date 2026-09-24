"""A small, strict XLSX reader: zipfile plus xml.etree, nothing else.

It reads cell values (shared strings, inline strings, numbers as text) from
the worksheets of an Office Open XML workbook. Formatting, formulas and
dates are not interpreted; DESNZ publishes its flat file as plain values, so
none is needed. Anything unexpected raises XlsxError with a readable message
instead of a traceback, because the input is downloaded from the internet.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

# Generous next to the real file (largest part 3.9 MB, 36 parts), small
# enough that a hostile archive cannot exhaust memory.
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_PARTS = 2000
_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")
_REF = re.compile(r"^([A-Z]{1,3})(\d+)$")


class XlsxError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _unescape(text: str) -> str:
    # OOXML writes control characters as _xHHHH_ (ECMA-376 Part 1, 22.9.2.19).
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)


def _column_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


class Workbook:
    def __init__(self, data: bytes):
        if not data:
            raise XlsxError("empty file, not an xlsx workbook")
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise XlsxError("not an xlsx workbook (not a zip archive)") from None
        infos = self._zip.infolist()
        if len(infos) > MAX_PARTS:
            raise XlsxError(f"archive has {len(infos)} parts, more than an xlsx workbook would")
        self._names = {i.filename: i for i in infos}
        book = self._office_document()
        self._book_dir = posixpath.dirname(book)
        root = self._xml(book)
        rels = self._relationships(posixpath.join(self._book_dir, "_rels", posixpath.basename(book) + ".rels"))
        self.sheets: list[tuple[str, str]] = []
        for el in root.iter():
            if _local(el.tag) != "sheet":
                continue
            rid = next((v for k, v in el.attrib.items() if _local(k) == "id" and k.startswith("{")), None)
            target = rels.get(rid, (None, None))[1] if rid else None
            if target is None:
                raise XlsxError(f"sheet {el.get('name')!r} has no worksheet part")
            self.sheets.append((el.get("name") or "", target))
        if not self.sheets:
            raise XlsxError("workbook lists no sheets")
        shared = next((t for (typ, t) in rels.values() if typ.endswith("/sharedStrings")), None)
        self._shared = self._shared_strings(shared) if shared else []

    @property
    def sheet_names(self) -> list[str]:
        return [n for n, _ in self.sheets]

    def _read(self, name: str) -> bytes:
        info = self._names.get(name)
        if info is None:
            raise XlsxError(f"part {name} is missing from the workbook")
        if info.file_size > MAX_PART_BYTES:
            raise XlsxError(f"part {name} is {info.file_size} bytes uncompressed, over the limit")
        try:
            return self._zip.read(info)
        except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, NotImplementedError) as e:
            raise XlsxError(f"part {name} cannot be read: {e}") from None

    def _xml(self, name: str) -> ET.Element:
        raw = self._read(name)
        # No legitimate workbook part declares a DTD; refusing one closes the
        # entity-expansion route without a third-party parser.
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise XlsxError(f"part {name} declares a DTD, refused")
        try:
            return ET.fromstring(raw)
        except ET.ParseError as e:
            raise XlsxError(f"part {name} is not well-formed XML: {e}") from None

    def _office_document(self) -> str:
        if "_rels/.rels" in self._names:
            for typ, target in self._relationships("_rels/.rels", base="").values():
                if typ.endswith("/officeDocument"):
                    return target
        if "xl/workbook.xml" in self._names:
            return "xl/workbook.xml"
        raise XlsxError("no workbook part found")

    def _relationships(self, name: str, base: str | None = None) -> dict[str, tuple[str, str]]:
        if name not in self._names:
            return {}
        base = self._book_dir if base is None else base
        out = {}
        for el in self._xml(name).iter():
            if _local(el.tag) != "Relationship" or el.get("TargetMode") == "External":
                continue
            target = el.get("Target") or ""
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
            out[el.get("Id") or ""] = (el.get("Type") or "", path)
        return out

    def _shared_strings(self, name: str) -> list[str]:
        if name not in self._names:
            return []
        out = []
        for si in self._xml(name):
            if _local(si.tag) != "si":
                continue
            parts = []
            for child in si:
                tag = _local(child.tag)
                if tag == "t":
                    parts.append(child.text or "")
                elif tag == "r":  # rich-text run; phonetic runs (rPh) are skipped on purpose
                    parts.extend(g.text or "" for g in child if _local(g.tag) == "t")
            out.append(_unescape("".join(parts)))
        return out

    def rows(self, sheet: str) -> list[list[str | None]]:
        """Every row of one sheet as a list of cell texts, None for empty cells."""
        target = next((t for n, t in self.sheets if n == sheet), None)
        if target is None:
            raise XlsxError(f"no sheet named {sheet!r}; sheets are {self.sheet_names}")
        out: list[list[str | None]] = []
        for row in self._xml(target).iter():
            if _local(row.tag) != "row":
                continue
            values: list[str | None] = []
            for c in row:
                if _local(c.tag) != "c":
                    continue
                ref = c.get("r")
                if ref:
                    m = _REF.match(ref)
                    if not m:
                        raise XlsxError(f"cell reference {ref!r} is not valid")
                    col = _column_index(m.group(1))
                else:
                    col = len(values)
                if col > 16383:
                    raise XlsxError(f"cell reference {ref!r} is beyond the last Excel column")
                while len(values) <= col:
                    values.append(None)
                values[col] = self._cell(c)
            while values and values[-1] in (None, ""):
                values.pop()
            out.append(values)
        return out

    def _cell(self, c: ET.Element) -> str | None:
        kind = c.get("t")
        if kind == "inlineStr":
            for child in c:
                if _local(child.tag) == "is":
                    return _unescape("".join(t.text or "" for t in child.iter() if _local(t.tag) == "t"))
            return None
        v = next((child.text for child in c if _local(child.tag) == "v"), None)
        if v is None:
            return None
        if kind == "s":
            try:
                return self._shared[int(v)]
            except (ValueError, IndexError):
                raise XlsxError(f"cell {c.get('r')} points at shared string {v!r}, which does not exist") from None
        if kind == "b":
            return "TRUE" if v.strip() == "1" else "FALSE"
        return _unescape(v) if kind == "str" else v
