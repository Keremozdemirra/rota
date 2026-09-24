"""Articles of Regulation (EU) 2023/1115 that carry dates, read from the text.

Nothing here knows a date in advance. Each date is read from the article's own
words ("shall apply from 30 December 2026"), and `refresh` cross-checks the
result against CELLAR's metadata before calling it verified.
"""
from __future__ import annotations

import datetime as dt
import re

from .annex import DATE_RE, LQ, RQ, find_date, iso_date
from .xhtml import Node, tidy

_PARA = re.compile(r"^(\d+)\.\s*(.*)$")
_POINT = re.compile(r"^\((\d+[a-z]?)\)\s*(.*)$")
_LABEL = re.compile(r"^\((\d+[a-z]?)\)$")
_ORDINALS = {"day": 1, "third day": 3, "twentieth day": 20}


class LegalTextError(ValueError):
    """An article is missing or does not read as expected."""


def article_lines(root: Node, number: str) -> list:
    node = root.find_id(f"art_{number}")
    if node is None:
        raise LegalTextError(f"Article {number} (id art_{number}) not found")
    lines = [tidy(line) for line in node.lines()]
    if not lines or lines[0] != f"Article {number}":
        raise LegalTextError(f"element art_{number} is not headed 'Article {number}'")
    return lines


def paragraphs(lines: list) -> dict:
    """{'1': text, ...} from article lines; accepts '1.' on its own line or '1. text'."""
    out, current = {}, None
    for line in lines:
        line = line.lstrip(LQ).strip()
        m = _PARA.match(line)
        if m:
            current = m.group(1)
            out[current] = m.group(2)
        elif current is not None:
            out[current] = tidy(out[current] + " " + line)
    return {k: _unquote(v) for k, v in out.items()}


def definitions(lines: list) -> dict:
    """{'15': text, '15a': text, ...} from the lines of Article 2.

    A definition starts at a '(15)' label; lettered sub-points '(a)' stay inside it.
    """
    out, current = {}, None
    for line in lines:
        m = _POINT.match(line)
        if m and (not m.group(2) or m.group(2).startswith(LQ)):
            current = m.group(1)
            out[current] = m.group(2)
        elif current is not None:
            out[current] = tidy(out[current] + " " + line)
    return out


def _unquote(text: str) -> str:
    text = text.strip()
    if text.startswith(LQ):
        text = text[1:]
    return re.sub(RQ + r"\s*[;.]?$", "", text).strip()


# ---------------------------------------------------------------- Article 38

def read_article_38(paras: dict) -> dict:
    """Dates and conditions from the three paragraphs of Article 38."""
    for k in ("1", "2", "3"):
        if k not in paras:
            raise LegalTextError(f"Article 38 has no paragraph {k}")
    p1, p2, p3 = paras["1"], paras["2"], paras["3"]
    rule = re.search(r"enter into force on the (?:(\w+) )?day following that of its publication", p1)
    if not rule:
        raise LegalTextError("Article 38(1) does not state the entry-into-force rule")
    articles = re.match(r"^Subject to paragraph 3 of this Article, (.+?) shall apply from", p2)
    established = (find_date(p3, "established as such by") or find_date(p3, "that by")
                   or find_date(p3, "established by"))
    out = {
        "entry_into_force_rule": rule.group(0),
        "p2_date": find_date(p2, "shall apply from"),
        "p2_articles": articles.group(1) if articles else None,
        "p3_date": find_date(p3, "shall apply from"),
        "p3_established_by": established,
        "p3_excludes_eutr_products": "products covered by the Annex to Regulation (EU) No 995/2010" in p3
                                      or "products covered in the Annex to Regulation (EU) No 995/2010" in p3,
    }
    for key in ("p2_date", "p3_date", "p3_established_by", "p2_articles"):
        if not out[key]:
            raise LegalTextError(f"Article 38: could not read {key}")
    return out


def read_article_37(paras: dict) -> dict:
    for k in ("1", "2", "3"):
        if k not in paras:
            raise LegalTextError(f"Article 37 has no paragraph {k}")
    out = {
        "p1_repeal_from": find_date(paras["1"], "with effect from"),
        "p2_until": find_date(paras["2"], "shall continue to apply until"),
        "p2_produced_before": find_date(paras["2"], "produced before"),
        "p2_placed_from": find_date(paras["2"], "placed on the market from"),
        "p3_produced_before": find_date(paras["3"], "produced before"),
        "p3_placed_from": find_date(paras["3"], "placed on the market from"),
    }
    missing = [k for k, v in out.items() if not v]
    if missing:
        raise LegalTextError(f"Article 37: could not read {', '.join(missing)}")
    return out


def entry_into_force(rule_text: str, published: str) -> str:
    """'...on the twentieth day following that of its publication' + publication date."""
    m = re.search(r"on the (?:(\w+) )?day following", rule_text)
    words = ((m.group(1) + " ") if m and m.group(1) else "") + "day"
    if words not in _ORDINALS:
        raise LegalTextError(f"unknown entry-into-force rule {rule_text[:80]!r}")
    return (dt.date.fromisoformat(published) + dt.timedelta(days=_ORDINALS[words])).isoformat()


_OJ_REF = re.compile(r"\(OJ L (\d+),? (\d{1,2})\.(\d{1,2})\.(\d{4}), p\. \d+\)")


def oj_publication(text: str) -> str | None:
    """Publication date from a reference such as '(OJ L 150 9.6.2023, p. 206)'."""
    m = _OJ_REF.search(text)
    if not m:
        return None
    return dt.date(int(m.group(4)), int(m.group(3)), int(m.group(2))).isoformat()


# ------------------------------------------------------ amending act points

_REPLACES_38 = re.compile(r"^(?:in )?Article 38(?:, paragraphs? ([\d, and]+))? (?:is|are) replaced by the following:$")


def replacement_of_article_38(root: Node) -> dict | None:
    """In an amending act: which point of Article 1 replaced Article 38, and with what."""
    node = root.find_id("art_1")
    if node is None:
        return None
    lines = [tidy(x) for x in node.lines()]
    for i, line in enumerate(lines):
        if not _REPLACES_38.match(line):
            continue
        label = next((lines[j] for j in range(i - 1, -1, -1) if _LABEL.match(lines[j])), None)
        body = []
        for nxt in lines[i + 1:]:
            if _LABEL.match(nxt):
                break
            body.append(nxt)
        paras = paragraphs([b for b in body if b not in (";", ".")])
        return {"point": label, "paragraphs": paras}
    return None


_TOUCH = [
    (re.compile(r"Annex I to Regulation \(EU\) 2023/1115 is amended"), lambda m: "Annex I"),
    (re.compile(r"^in Annex I\b"), lambda m: "Annex I"),
    (re.compile(r"^(?:in )?Article (\d+[a-z]?)\b[^:;]*?(?:is|are) (?:replaced|amended|deleted|added|inserted)"),
     lambda m: f"Article {m.group(1)}"),
    (re.compile(r"^the following Article (\d+[a-z]?) is inserted"), lambda m: f"Article {m.group(1)}"),
    (re.compile(r"^Annex (I{1,3}|IV|V)\b[^:;]*?is (?:replaced|amended|deleted|added)"), lambda m: f"Annex {m.group(1)}"),
    (re.compile(r"^the text set out in Annex [IVX]+ to this Regulation is added as Annex (I{1,3}|IV|V)"),
     lambda m: f"Annex {m.group(1)}"),
]


def touched_provisions(root: Node) -> list:
    """Which provisions of 2023/1115 an amending act changes, from Article 1's wording."""
    node = root.find_id("art_1")
    if node is None:
        return []
    found = []
    for line in (tidy(x) for x in node.lines()):
        for rx, name in _TOUCH:
            m = rx.search(line)
            if m:
                label = name(m)
                if label not in found:
                    found.append(label)
    return found


def oj_header_date(root: Node) -> str | None:
    """Publication date in the header of an OJ L-series act ('17.9.2026')."""
    for p in root.iter("p"):
        if "oj-hd-date" in p.cls():
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", p.text())
            if m:
                return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    return None


def act_entry_into_force_rule(root: Node) -> str | None:
    """'shall enter into force on the ... day following ...' of the act itself.

    Amending acts quote the amended act's own clause (2025/2650 quotes the new
    Article 38), so the act's clause is the last one in the document.
    """
    found = None
    for p in root.iter("p"):
        m = re.search(r"shall enter into force on the (?:\w+ )?day following that of its publication", p.text())
        if m:
            found = m.group(0)
    return found


def dates_in(text: str) -> list:
    return [iso_date(*m) for m in re.findall(DATE_RE, text)]
