"""Official Journal XHTML (as served by CELLAR) to numbered paragraphs.

The Publications Office renders an annex as a `div` whose direct children are
headings (`p.oj-ti-grseq-1`) and one `table` per numbered paragraph: an empty cell,
a cell holding "29.", and a cell holding the text. Points such as (a) or (i) are
nested tables without a class; data tables carry class `oj-table`. Formulas and
figures are images; they are replaced by a marker, never reproduced.

Words are kept as published. Only whitespace is normalised and table layout
flattened (cells joined by " | "); footnotes are left out. The snapshot says so.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

X = "{http://www.w3.org/1999/xhtml}"
IMAGE = "[image in the Official Journal, not reproduced]"
CODE = r"[BC](?:1[01]|[1-9])"
CODE_HEADING = re.compile(r"^(" + CODE + r")\s*[–-]\s*(.+)$")
CODE_MENTION = re.compile(r"\b(" + CODE + r")\b")
MODULE_HEADING = re.compile(r"^(\d+\.\d+\.\s|basic module|comprehensive module)", re.I)
PARA_NUMBER = re.compile(r"^(\d{1,3})\.$")
POINT_LABEL = re.compile(r"^(\([a-z]{1,4}\)|\([ivx]+\)|\(\d{1,3}\)|[ivx]{1,5}\.|—|-)$")
HEADER_ID = re.compile(r"(\d{4}/\d{1,5})\s+(\d{1,2})\.(\d{1,2})\.(\d{4})")


class ParseError(ValueError):
    """The document does not have the structure this parser knows."""


def _tag(el) -> str:
    return el.tag[len(X):] if isinstance(el.tag, str) and el.tag.startswith(X) else str(el.tag)


def tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace(" ", " ")).strip()
    # Inline markup around defined terms leaves spaces inside quotes and before punctuation.
    text = re.sub(r"([‘“(])\s+", r"\1", text)
    text = re.sub(r"\s+([’”),.;:?!])", r"\1", text)
    return text


def inline_text(el) -> str:
    """Text of an element; images become a marker, nested tables are skipped."""
    parts = [el.text or ""]
    for child in el:
        tag = _tag(child)
        if tag == "img":
            parts.append(" " + IMAGE + " ")
        elif tag != "table":
            parts.append(inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _rows(table):
    for child in table:
        tag = _tag(child)
        if tag == "tr":
            yield child
        elif tag in ("tbody", "thead", "tfoot"):
            for tr in child:
                if _tag(tr) == "tr":
                    yield tr


def _cells(tr):
    return [c for c in tr if _tag(c) in ("td", "th")]


def cell_lines(cell) -> list:
    """Lines of text in a table cell: paragraphs, points and flattened data tables."""
    lines, buf = [], []

    def flush():
        text = tidy("".join(buf))
        if text:
            lines.append(text)
        buf.clear()

    buf.append(cell.text or "")
    for child in cell:
        tag = _tag(child)
        if tag == "table":
            flush()
            lines.extend(table_lines(child))
        elif tag in ("p", "div"):
            flush()
            if any(_tag(g) == "table" for g in child.iter() if g is not child):
                lines.extend(cell_lines(child))
            else:
                buf.append(inline_text(child))
                flush()
        elif tag == "img":
            buf.append(" " + IMAGE + " ")
        else:
            buf.append(inline_text(child))
        buf.append(child.tail or "")
    flush()
    return lines


def table_lines(table) -> list:
    out = []
    data_table = "oj-table" in (table.get("class") or "")
    for tr in _rows(table):
        cells = _cells(tr)
        texts = [cell_lines(c) for c in cells]
        firsts = [t[0] if t else "" for t in texts]
        nonempty = [i for i, t in enumerate(firsts) if t]
        if not data_table and nonempty and POINT_LABEL.match(firsts[nonempty[0]]) and len(nonempty) > 1:
            i = nonempty[0]
            rest = [line for t in texts[i + 1:] for line in t]
            out.append(firsts[i] + " " + rest[0])
            out.extend("  " + line for line in rest[1:])
        elif data_table or len(cells) > 1:
            out.append(tidy(" | ".join(" ".join(t) for t in texts)))
        else:
            out.extend(line for t in texts for line in t)
    return [line for line in out if line.strip(" |")]


def numbered_paragraph(table):
    """(number, lines) for a paragraph table, else None."""
    for tr in _rows(table):
        cells = _cells(tr)
        texts = [tidy(inline_text(c)) for c in cells]
        for i, t in enumerate(texts):
            if not t:
                continue
            m = PARA_NUMBER.match(t)
            if not m:
                return None
            lines = [line for c in cells[i + 1:] for line in cell_lines(c)]
            return m.group(1), lines
        return None
    return None


def annex(root, number: str):
    for div in root.iter(X + "div"):
        if div.get("id") == "anx_" + number:
            return div
    return None


def paragraphs(div, stop_at_appendix: bool = True) -> list:
    """Numbered paragraphs of an annex with the heading and disclosure code they fall under."""
    out = []
    heading, code, related = None, None, []
    for child in div:
        tag = _tag(child)
        cls = child.get("class") or ""
        if tag == "p" and cls.startswith("oj-ti-grseq"):
            text = tidy(inline_text(child))
            if not text:
                continue
            if stop_at_appendix and text.lower().startswith("appendix"):
                break
            m = CODE_HEADING.match(text)
            heading = text
            if m:
                code, related = m.group(1), []
            elif CODE_MENTION.search(text):
                code, related = None, sorted(set(CODE_MENTION.findall(text)))
            elif MODULE_HEADING.match(text):
                code, related = None, []
            # any other heading is a sub-heading inside the current disclosure
        elif tag == "table":
            para = numbered_paragraph(child)
            if para:
                n, lines = para
                out.append({"n": n, "heading": heading, "code": code, "related": list(related),
                            "text": "\n".join(lines)})
    if not out:
        raise ParseError("no numbered paragraphs found in the annex")
    return out


def value_chain_cap(div) -> list:
    """Rows of the value chain cap table (Annex II to Delegated Regulation (EU) 2026/1560)."""
    rows = []
    for table in div.iter(X + "table"):
        for tr in _rows(table):
            texts = [tidy(inline_text(c)) for c in _cells(tr)]
            if len(texts) == 5 and re.fullmatch(CODE, texts[0]):
                rows.append({"code": texts[0], "reference": texts[1], "datapoint": texts[2],
                             "cap_10_or_fewer_employees": texts[3].upper() == "X",
                             "cap_more_than_10_employees": texts[4].upper() == "X"})
    if not rows:
        raise ParseError("no value chain cap rows found")
    return rows


def header(root) -> dict:
    """OJ number and publication date from the page header, title from the act."""
    head = tidy(" ".join(tidy(inline_text(t)) for t in list(root.iter(X + "table"))[:3]))
    m = HEADER_ID.search(head)
    if not m:
        raise ParseError("no OJ number and date in the page header")
    number, d, mo, y = m.groups()
    title = None
    for div in root.iter(X + "div"):
        if div.get("id") == "tit_1":
            title = tidy(" ".join(tidy(inline_text(p)) for p in div))
            break
    if not title:
        raise ParseError("no title (div#tit_1)")
    return {"oj_number": number, "published": f"{y}-{int(mo):02d}-{int(d):02d}", "title": title}


def subdivision(root, ident: str) -> str:
    """Text of a recital (rct_N) or an article (art_N), lines joined."""
    for div in root.iter(X + "div"):
        if div.get("id") == ident:
            lines = []
            for child in div:
                if _tag(child) == "table":
                    lines.extend(table_lines(child))
                else:
                    t = tidy(inline_text(child))
                    if t:
                        lines.append(t)
            return "\n".join(lines)
    raise ParseError(f"no {ident} in the act")


def parse(xhtml: bytes):
    if b"<!ENTITY" in xhtml[:4096]:
        raise ParseError("document declares entities; refused")
    try:
        return ET.fromstring(xhtml)
    except ET.ParseError as e:
        raise ParseError(f"not well-formed XHTML ({e})") from None
