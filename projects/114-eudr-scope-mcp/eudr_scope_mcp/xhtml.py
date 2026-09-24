"""A small, tolerant XHTML tree for the documents CELLAR serves.

EUR-Lex/CELLAR XHTML is mostly well formed, but not always, and the standard
library's XML parser rejects a whole document over one stray entity. The
HTMLParser-based builder below never raises on markup; the parsers that use
it fail on missing content instead, which is the failure that matters.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {"br", "hr", "col", "img", "meta", "link", "input", "area", "base", "wbr", "source", "param"}
BLOCK = {"p", "div", "td", "th", "tr", "table", "tbody", "thead", "li", "ul", "ol", "h1", "h2", "h3",
         "h4", "h5", "h6", "body", "html", "dt", "dd", "section", "article", "hr"}
# Every Unicode space the OJ uses (no-break, narrow no-break, thin, figure) counts
# as one ordinary space, or "30<NBSP>December 2026" would not match a date pattern.
_SPACE_CHARS = "".join(map(chr, (0x00A0, 0x2007, 0x2009, 0x202F, 0x200B, 0xFEFF)))
_SPACES = re.compile(r"[\s" + _SPACE_CHARS + r"]+")
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]")


# A footnote marker removed from "Council (<a>1</a>)" leaves "Council ( )".
_EMPTY_PARENS = re.compile(r"\(\s*\)")
_SPACE_BEFORE_PUNCT = re.compile(r" +([,;.:)])")
_SPACE_AFTER_OPEN = re.compile(r"\( +")


def clean(text: str) -> str:
    """Collapse whitespace and drop control characters."""
    return _SPACES.sub(" ", _CONTROL.sub("", text)).strip()


def tidy(text: str) -> str:
    """clean(), then remove what a dropped footnote marker leaves behind."""
    text = _EMPTY_PARENS.sub("", clean(text))
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", clean(text))
    return _SPACE_AFTER_OPEN.sub("(", text)


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []  # Node or str
        self.parent = parent

    def cls(self) -> set:
        return set((self.attrs.get("class") or "").split())

    def iter(self, tag: str | None = None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.iter(tag)

    def find_id(self, id_: str) -> "Node | None":
        for node in self.iter():
            if node.attrs.get("id") == id_:
                return node
        return None

    def element_children(self, tag: str | None = None) -> list:
        return [c for c in self.children if isinstance(c, Node) and (tag is None or c.tag == tag)]

    def text(self) -> str:
        return tidy("".join(self._raw()))

    def _raw(self):
        for child in self.children:
            if isinstance(child, str):
                yield child
            elif not skipped(child):
                yield from child._raw()

    def lines(self) -> list:
        """Text split at block boundaries and <br>, with footnotes left out."""
        out: list = []
        buf: list = []

        def flush():
            line = tidy("".join(buf))
            if line:
                out.append(line)
            buf.clear()

        def walk(node: Node):
            for child in node.children:
                if isinstance(child, str):
                    buf.append(child)
                    continue
                if skipped(child):
                    continue
                if child.tag == "br":
                    flush()
                    continue
                block = child.tag in BLOCK
                if block:
                    flush()
                walk(child)
                if block:
                    flush()

        walk(self)
        flush()
        return out


def skipped(node: Node) -> bool:
    if node.tag in ("script", "style", "head"):
        return True
    classes = node.cls()
    # Footnote bodies and the in-text markers that point at them.
    if "oj-note" in classes or "note" in classes:
        return True
    if node.tag == "a":
        for span in node.iter("span"):
            if "oj-note-tag" in span.cls():
                return True
        href = node.attrs.get("href") or ""
        # "#ntc..." in the Official Journal, "#E0001" in consolidated texts.
        if href.startswith(("#ntr", "#ntc", "#footnote")) or re.match(r"#E\d+$", href):
            return True
    return False


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(markup: str) -> Node:
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    return builder.root
