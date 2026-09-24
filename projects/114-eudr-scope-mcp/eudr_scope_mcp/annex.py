"""Annex I of Regulation (EU) 2023/1115: parse the table, apply amending acts.

Two inputs, both XHTML from CELLAR:

* the consolidated text, whose Annex I is a two-column table (relevant
  commodity, relevant products) with one product entry per line;
* amending acts not yet in any consolidated version, whose annex says in words
  what changes ("the entry '...' is replaced by the following: ...").

Entries are never edited in place. A replaced or deleted entry gets a
`valid_to` date and the new text becomes a new entry with `valid_from`, so a
lookup can answer for any date from the consolidated version onwards, and the
provenance of every line stays visible.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re

from .xhtml import Node, clean, skipped, tidy

LQ, RQ = chr(0x2018), chr(0x2019)  # the OJ quotes amended text in these
# Consolidated texts mark amended passages with these arrows (M = amending act,
# C = corrigendum, B = basic act); they are navigation, not text.
_MARKERS = re.compile("[" + chr(0x25BA) + chr(0x25BC) + chr(0x25C4) + r"](?:\s*[A-Z]\d*)?")

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
DATE_RE = r"(\d{1,2}) (" + "|".join(MONTHS) + r"),? (\d{4})"

# A CN code as the Annex writes it: "0102 21", "0206 21 00", "4401", or a
# two-digit chapter ("ex 47") when followed by text.
_CODE = r"(?:\d{4}(?: \d{2}){0,2}(?![\d])|\d{2}(?= [^\d]|$))"
_ITEM = re.compile(r"\s*(ex\s+)?(" + _CODE + r")")
_SEP = re.compile(r"\s*(?:,|and)\s*(?=(?:ex\s+)?\d)")
_CHAPTERS = re.compile(r"\bChapters? (\d{2})(?: and (\d{2}))? of the Combined Nomenclature")
_LEAK = re.compile(r"https?://|\bOJ [LC] \d|\bELI:")
_APPLY_FROM = re.compile(r"^\(\s*This provision shall apply from " + DATE_RE + r"\s*\)$")

COMMODITIES = ("Cattle", "Cocoa", "Coffee", "Oil palm", "Rubber", "Soya", "Wood")


class AnnexError(ValueError):
    """The document does not have the structure this parser relies on."""


def strip_markers(text: str) -> str:
    """Remove the consolidation arrows (e.g. 'M2' with its arrow) from a line of text."""
    return tidy(_MARKERS.sub(" ", text))


def iso_date(day: str, month: str, year: str) -> str:
    return dt.date(int(year), MONTHS[month], int(day)).isoformat()


def find_date(text: str, after: str) -> str | None:
    """First date that follows the phrase `after` in `text`, as YYYY-MM-DD."""
    m = re.search(re.escape(after) + r"\s+" + DATE_RE, text)
    return iso_date(*m.groups()) if m else None


def day_before(iso: str) -> str:
    return (dt.date.fromisoformat(iso) - dt.timedelta(days=1)).isoformat()


def strip_quotes(line: str) -> str:
    line = line.strip()
    if line.startswith(LQ):
        line = line[1:].lstrip()
    line = re.sub(RQ + r"\s*[;.,]?\s*$", "", line).rstrip()
    return line


def split_codes(line: str):
    """('ex 0102 21, 0102 29 Live cattle') -> ([('010221', True), ...], 'Live cattle', prefix)."""
    items, pos = [], 0
    while True:
        m = _ITEM.match(line, pos)
        if not m:
            break
        items.append((m.group(2).replace(" ", ""), bool(m.group(1))))
        pos = m.end()
        sep = _SEP.match(line, pos)
        if not sep:
            break
        pos = sep.end()
    if not items:
        return None
    rest = line[pos:].strip()
    if rest and rest[0].isdigit():
        return None  # "95 % or more" style text, not a code list
    return items, rest, tidy(line[:pos])


def parse_entry_lines(lines, commodity: str | None) -> list:
    """Group Annex lines into entries: a code line starts one, '(...)' lines are
    its notes, anything else continues its description."""
    entries: list = []
    for raw in lines:
        line = tidy(_MARKERS.sub(" ", strip_quotes(raw)))
        if not line:
            continue
        applies = _APPLY_FROM.match(line)
        if applies:
            if not entries:
                raise AnnexError(f"date line before any entry: {line[:80]!r}")
            entries[-1]["applies_from"] = iso_date(*applies.groups())
            continue
        if line.startswith("("):
            if not entries:
                raise AnnexError(f"note before any entry: {line[:80]!r}")
            entries[-1]["notes"].append(line)
            continue
        split = split_codes(line)
        if split:
            items, rest, label = split
            entries.append({"commodity": commodity, "codes": [{"code": c, "ex": ex} for c, ex in items],
                            "label": label, "description": rest, "notes": []})
            continue
        chapters = _CHAPTERS.search(line)
        if chapters and line[:1].isupper():
            codes = [c for c in chapters.groups() if c]
            entries.append({"commodity": commodity, "codes": [{"code": c, "ex": False} for c in codes],
                            "label": "Chapters " + " and ".join(codes), "description": line, "notes": []})
            continue
        if not entries:
            raise AnnexError(f"text before any entry: {line[:80]!r}")
        entries[-1]["description"] = clean(entries[-1]["description"] + " " + line)
    for e in entries:
        # A footnote body that slipped past the markup filter reads like this.
        if _LEAK.search(" ".join([e["description"]] + e["notes"])):
            raise AnnexError(f"entry {e['label']!r} carries footnote or reference text: {e['description'][:120]!r}")
    return entries


# ------------------------------------------------------------ consolidated

def parse_consolidated_annex(root: Node) -> dict:
    """Annex I of a consolidated text: intro paragraphs and the entry table."""
    annex = root.find_id("anx_I")
    if annex is None:
        raise AnnexError("no element with id 'anx_I' (Annex I) in the consolidated text")
    title = " ".join(annex.lines()[:3])
    if "ANNEX I" not in title or "Relevant commodities and relevant products" not in title:
        raise AnnexError("element 'anx_I' is not headed 'ANNEX I / Relevant commodities and relevant products'")
    intro = [p.text() for p in annex.element_children("p") if "norm" in p.cls() and p.text()]
    tables = list(annex.iter("table"))
    if not tables:
        raise AnnexError("Annex I has no table")
    entries, seen = [], []
    for tr in _rows(tables[0]):
        cells = tr.element_children("td") or tr.element_children("th")
        if len(cells) != 2:
            continue
        commodity = _MARKERS.sub(" ", cells[0].text()).strip()
        if commodity == "Relevant commodity":
            continue
        if commodity not in COMMODITIES:
            raise AnnexError(f"unexpected commodity cell {commodity[:60]!r}")
        seen.append(commodity)
        found = parse_entry_lines(cells[1].lines(), commodity)
        if not found:
            raise AnnexError(f"no product entries for {commodity}")
        entries.extend(found)
    missing = [c for c in COMMODITIES if c not in seen]
    if missing:
        raise AnnexError(f"Annex I table lacks rows for: {', '.join(missing)}")
    return {"intro": intro, "entries": entries}


def _rows(table: Node) -> list:
    rows = []
    for child in table.element_children():
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in ("tbody", "thead", "tfoot"):
            rows.extend(child.element_children("tr"))
    return rows


def amended_by(root: Node) -> list:
    """CELEX numbers in the 'Amended by' list at the top of a consolidated text."""
    out = []
    for a in root.iter("a"):
        text = a.text()
        if re.fullmatch("[" + chr(0x25BA) + r"]\s*M\d+", text or ""):
            celex = (a.attrs.get("title") or "").split(":")[0].strip()
            if re.fullmatch(r"3\d{4}[A-Z]\d{4}", celex) and celex not in out:
                out.append(celex)
    return out


# ------------------------------------------------------ amending act annex

class Point:
    __slots__ = ("label", "paras", "children")

    def __init__(self, label, paras, children):
        self.label, self.paras, self.children = label, paras, children


def _points(table: Node) -> list:
    out = []
    for tr in _rows(table):
        cells = tr.element_children("td")
        if len(cells) != 2:
            continue
        label = cells[0].text()
        paras, kids = [], []
        for child in cells[1].children:
            if isinstance(child, Node):
                if skipped(child):
                    continue
                if child.tag == "table":
                    kids.extend(_points(child))
                else:
                    paras.extend(child.lines())
            else:
                text = tidy(child)
                if text:
                    paras.append(text)
        out.append(Point(label, paras, kids))
    return out


INTRO = "The table in Annex I to Regulation (EU) 2023/1115 is amended as follows"
_Q = LQ + r"(.+)" + RQ
_INSTR = [
    ("replace", re.compile(r"^the entry " + _Q + r",? is (?:deleted and )?replaced by the following:$", re.S)),
    ("replace", re.compile(r"^the entries " + _Q + r",? are (?:deleted and )?replaced by the following:$", re.S)),
    ("delete", re.compile(r"^the entr(?:y|ies) " + _Q + r",? (?:is|are) deleted\s*[;.]?$", re.S)),
    ("insert_after", re.compile(r"^after the entry " + _Q + r",? the following entr(?:y is|ies are) inserted:$", re.S)),
    ("text_after", re.compile(r"^after the entry " + _Q + r",? the following text is added:$", re.S)),
    ("note_commodity", re.compile(r"^in the column " + LQ + "Relevant commodity" + RQ
                                  + r", the following table note \((\d+)\) is added after the entry " + _Q + r":$", re.S)),
    ("note_products", re.compile(r"^in the column " + LQ + "Relevant products" + RQ
                                 + r", the following table note \((\d+)\) is added to the heading " + LQ
                                 + "Relevant products" + RQ + ":$", re.S)),
    ("container", re.compile(r"^the column " + LQ + "Relevant products" + RQ + r" is amended as follows:$", re.S)),
]


def amendment_points(root: Node) -> list:
    """The numbered points of the annex that amends Annex I, or [] if none does."""
    for p in root.iter("p"):
        if p.text().startswith(INTRO):
            container = p.parent
            points = []
            for child in container.element_children():
                if child.tag == "table":
                    points.extend(_points(child))
            if not points:
                raise AnnexError("amending annex found but it has no numbered points")
            return points
    return []


def parse_instructions(points: list) -> list:
    """Flatten the annex points into a list of operations in document order."""
    ops: list = []

    def walk(point_list, prefix):
        for pt in point_list:
            ref = prefix + pt.label
            kind, match, k = _classify(pt.paras)
            if kind is None:
                raise AnnexError(f"point {ref}: instruction not understood: {' '.join(pt.paras)[:160]!r}")
            content = pt.paras[k + 1:]
            if kind == "container":
                walk(pt.children, ref)
                continue
            op = {"point": ref, "action": kind}
            if kind in ("note_commodity", "note_products"):
                op["number"] = match.group(1)
                if kind == "note_commodity":
                    op["attached_to"] = match.group(2)
                op["text"] = _note_text(pt.children, match.group(1), ref)
            else:
                op["targets"] = _split_targets(match.group(1))
                op["content"] = content
            ops.append(op)

    walk(points, "")
    return ops


def _classify(paras):
    for k in range(len(paras)):
        joined = "\n".join(paras[: k + 1])
        for kind, rx in _INSTR:
            m = rx.match(joined)
            if m:
                return kind, m, k
    return None, None, -1


def _split_targets(quoted: str) -> list:
    parts = re.split(RQ + r",?\s+(?:and\s+)?" + LQ, quoted)
    return [p.strip() for p in parts if p.strip()]


def _note_text(children, number, ref) -> str:
    for child in children:
        if child.label.strip(LQ + " ") == f"({number})":
            parts = list(child.paras)
            for sub in child.children:
                parts.append(sub.label + " " + " ".join(sub.paras))
            return strip_quotes(" ".join(parts))
    raise AnnexError(f"point {ref}: table note ({number}) text not found")


def apply_instructions(entries: list, ops: list, source: dict, in_force: str) -> tuple:
    """Apply operations to entries; returns (entries, table_notes, log).

    `source` is {"celex": ..., "title": ...}; `in_force` the act's entry into
    force (YYYY-MM-DD), which is when an amendment without its own
    'shall apply from' date takes effect.
    """
    entries = [dict(e) for e in entries]
    notes, log = [], []
    counter = [0]

    def new_entry(proto, commodity, ref):
        counter[0] += 1
        e = {"id": f"{source['celex']}-{counter[0]:02d}", "commodity": commodity,
             "codes": proto["codes"], "label": proto["label"], "description": proto["description"],
             "notes": proto["notes"], "valid_from": proto.get("applies_from") or in_force, "valid_to": None,
             "source": {"celex": source["celex"], "provision": f"Annex, point {ref}"}}
        return e

    for op in ops:
        ref = _fmt_ref(op["point"])
        action = op["action"]
        if action == "note_commodity":
            if op["attached_to"] not in COMMODITIES:
                raise AnnexError(f"point {ref}: note attached to unknown commodity {op['attached_to']!r}")
            notes.append({"number": op["number"], "column": "Relevant commodity", "attached_to": op["attached_to"],
                          "text": op["text"], "valid_from": in_force,
                          "source": {"celex": source["celex"], "provision": f"Annex, point {ref}"}})
            log.append({"point": ref, "action": "table note", "detail": f"note ({op['number']}) on {op['attached_to']}"})
            continue
        if action == "note_products":
            notes.append({"number": op["number"], "column": "Relevant products", "attached_to": None,
                          "text": op["text"], "valid_from": in_force,
                          "source": {"celex": source["celex"], "provision": f"Annex, point {ref}"}})
            log.append({"point": ref, "action": "table note", "detail": f"note ({op['number']}) on all relevant products"})
            continue

        targets = [_find(entries, t, ref) for t in op["targets"]]
        if action in ("insert_after", "text_after") and len(targets) != 1:
            raise AnnexError(f"point {ref}: expected one anchor entry, got {len(targets)}")
        commodity = entries[targets[0]]["commodity"]
        if action == "delete":
            if op["content"]:
                raise AnnexError(f"point {ref}: deletion with replacement text")
            for i in targets:
                entries[i]["valid_to"] = day_before(in_force)
                entries[i]["removed_by"] = {"celex": source["celex"], "provision": f"Annex, point {ref}"}
            log.append({"point": ref, "action": "delete", "removed": [entries[i]["id"] for i in targets]})
            continue
        if action == "text_after":
            old = entries[targets[0]]
            added = [tidy(strip_quotes(line)) for line in op["content"] if tidy(strip_quotes(line))]
            if not added or not all(a.startswith("(") for a in added):
                raise AnnexError(f"point {ref}: added text is not a parenthesised note: {added[:1]!r}")
            proto = {"codes": old["codes"], "label": old["label"], "description": old["description"],
                     "notes": list(old["notes"]) + added}
            fresh = new_entry(proto, old["commodity"], ref)
            old["valid_to"] = day_before(fresh["valid_from"])
            old["removed_by"] = {"celex": source["celex"], "provision": f"Annex, point {ref}"}
            fresh["replaces"] = [old["id"]]
            entries.insert(targets[0] + 1, fresh)
            log.append({"point": ref, "action": "add note", "removed": [old["id"]], "added": [fresh["id"]]})
            continue
        protos = parse_entry_lines(op["content"], commodity)
        if not protos:
            raise AnnexError(f"point {ref}: no entries in the replacement text")
        fresh = [new_entry(p, commodity, ref) for p in protos]
        if action == "replace":
            start = min(e["valid_from"] for e in fresh)
            for i in targets:
                entries[i]["valid_to"] = day_before(start)
                entries[i]["removed_by"] = {"celex": source["celex"], "provision": f"Annex, point {ref}"}
            for e in fresh:
                e["replaces"] = [entries[i]["id"] for i in targets]
            at = max(targets) + 1
            log.append({"point": ref, "action": "replace", "removed": [entries[i]["id"] for i in targets],
                        "added": [e["id"] for e in fresh]})
        else:  # insert_after
            at = targets[0] + 1
            log.append({"point": ref, "action": "insert", "after": entries[targets[0]]["id"],
                        "added": [e["id"] for e in fresh]})
        entries[at:at] = fresh
    return entries, notes, log


def _fmt_ref(point: str) -> str:
    return point.replace(LQ, "")


def _signature(codes) -> tuple:
    return tuple(sorted((c["code"], c["ex"]) for c in codes))


def _find(entries: list, target: str, ref: str) -> int:
    """Index of the one current entry the quoted target text designates."""
    protos = parse_entry_lines(target.split("\n"), None)
    if len(protos) != 1:
        raise AnnexError(f"point {ref}: cannot read the quoted entry {target[:80]!r}")
    want = protos[0]
    live = [i for i, e in enumerate(entries) if e.get("valid_to") is None]
    exact = [i for i in live if _signature(entries[i]["codes"]) == _signature(want["codes"])]
    loose = [i for i in live if sorted(c["code"] for c in entries[i]["codes"]) == sorted(c["code"] for c in want["codes"])]
    hits = exact or loose
    if len(hits) != 1:
        raise AnnexError(f"point {ref}: quoted entry {want['label']!r} matches {len(hits)} current entries")
    found = entries[hits[0]]
    # The quote must also read like the entry, or a code typo could hit the wrong line.
    ratio = difflib.SequenceMatcher(None, found["description"].lower(), want["description"].lower()).ratio()
    if ratio < 0.8:
        raise AnnexError(f"point {ref}: quoted text differs from entry {found['label']!r} (similarity {ratio:.2f})")
    return hits[0]
