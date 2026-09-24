#!/usr/bin/env python3
"""Rebuild the trimmed test fixtures from files downloaded from EIOPA.

The tests run offline on small copies of real EIOPA files. This script is how
those copies were made, so anyone can check that nothing in them was invented:
every cell value, link and title is copied verbatim; only rows, columns,
sheets and page sections are left out. See tests/fixtures/SOURCES.md.

Usage (paths to the raw files as downloaded from EIOPA):

  python3 tests/build_fixtures.py \\
      --release-2026-08 EIOPA_RFR_20260831.zip \\
      --release-2026-07 EIOPA_RFR_20260731.zip \\
      --release-2022-12 "December 2022.zip" \\
      --page rfr_page.html --archive-page previous_releases.html \\
      --rss rss_en.xml --throttled throttled_429.html \\
      --out tests/fixtures

Standard library only. Output is byte-for-byte reproducible (fixed zip
timestamps), so re-running it on the same inputs yields the same SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"
FIXED_TIME = (2026, 9, 24, 0, 0, 0)
KEEP_SHEETS = ("Main_Menu", "RFR_spot_no_VA", "RFR_spot_with_VA")
CURVE_ID = re.compile(r"^([A-Z]{2,3})_\d{1,2}_\d{1,2}_\d{4}_")


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _shared_strings(x: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(x.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")))
    return out


def _sheets(x: zipfile.ZipFile) -> dict[str, dict]:
    wb = ET.fromstring(x.read("xl/workbook.xml"))
    rels = ET.fromstring(x.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for s in wb.find(f"{{{NS_MAIN}}}sheets"):
        rid = s.get(f"{{{NS_R}}}id")
        t = target[rid]
        path = t.lstrip("/") if t.startswith("/") else "xl/" + t
        out[s.get("name")] = {"sheetId": s.get("sheetId"), "rid": rid, "state": s.get("state"),
                              "target": t, "path": path}
    return out


def trim_xlsx(data: bytes, keep_codes: set[str]) -> bytes:
    """Keep three sheets; in the spot sheets keep column B and the named curves."""
    x = zipfile.ZipFile(io.BytesIO(data))
    sst = _shared_strings(x)
    sheets = _sheets(x)
    new_sst: list[str] = []
    index: dict[str, int] = {}

    def remap(i: str) -> str:
        s = sst[int(i)]
        if s not in index:
            index[s] = len(new_sst)
            new_sst.append(s)
        return str(index[s])

    parts = []
    for name in KEEP_SHEETS:
        meta = sheets[name]
        root = ET.fromstring(x.read(meta["path"]))
        cells = []
        for c in root.iter(f"{{{NS_MAIN}}}c"):
            v = c.find(f"{{{NS_MAIN}}}v")
            if v is None or v.text is None:
                continue
            m = re.match(r"([A-Z]+)(\d+)$", c.get("r"))
            cells.append((int(m.group(2)), m.group(1), c.get("t"), v.text))
        if name == "Main_Menu":
            keep_cols = {col for _, col, _, _ in cells}
        else:
            keep_cols = {"B"}
            for row, col, t, v in cells:
                text = sst[int(v)] if t == "s" else v
                m = CURVE_ID.match(text or "")
                if row == 3 and m and m.group(1) in keep_codes:
                    keep_cols.add(col)
        rows: dict[int, list] = {}
        for row, col, t, v in cells:
            if col in keep_cols:
                rows.setdefault(row, []).append((col, t, remap(v) if t == "s" else v))
        xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
               f'<worksheet xmlns="{NS_MAIN}"><sheetData>']
        for row in sorted(rows):
            xml.append(f'<row r="{row}">')
            for col, t, v in sorted(rows[row], key=lambda e: _col_index(e[0])):
                t_attr = f' t="{t}"' if t else ""
                xml.append(f'<c r="{col}{row}"{t_attr}><v>{escape(v)}</v></c>')
            xml.append("</row>")
        xml.append("</sheetData></worksheet>")
        parts.append((name, meta, "".join(xml).encode("utf-8")))

    sheet_entries = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{meta["sheetId"]}"'
        + (f' state="{meta["state"]}"' if meta["state"] else "")
        + f' r:id="{meta["rid"]}"/>'
        for name, meta, _ in parts)
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_R}"><sheets>{sheet_entries}</sheets></workbook>')
    ws_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    sst_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    rels = "".join(f'<Relationship Id="{meta["rid"]}" Type="{ws_type}" Target="{meta["target"]}"/>'
                   for _, meta, _ in parts)
    rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{NS_PR}">{rels}'
            f'<Relationship Id="rId900" Type="{sst_type}" Target="sharedStrings.xml"/></Relationships>')
    sst_xml = "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in new_sst)
    sst_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="{NS_MAIN}" '
               f'count="{len(new_sst)}" uniqueCount="{len(new_sst)}">{sst_xml}</sst>')
    ct_ws = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    overrides = "".join(f'<Override PartName="/{meta["path"]}" ContentType="{ct_ws}"/>' for _, meta, _ in parts)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'{overrides}<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
    root_rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{NS_PR}">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                 'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    members = [("[Content_Types].xml", content_types.encode()), ("_rels/.rels", root_rels.encode()),
               ("xl/workbook.xml", workbook.encode()), ("xl/_rels/workbook.xml.rels", rels.encode()),
               ("xl/sharedStrings.xml", sst_xml.encode())]
    members += [(meta["path"], xml) for _, meta, xml in parts]
    return _zip(members)


def trim_release(raw: bytes, keep_codes: set[str]) -> bytes:
    """The release zip reduced to its Term_Structures workbook, itself trimmed."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in z.namelist() if re.search(r"_Term_Structures\.xlsx$", n, re.I))
    return _zip([(name, trim_xlsx(z.read(name), keep_codes))])


FILE_MARK = '<div class="ecl-file" data-ecl-file=""'
CONTENT_OPEN = '<div class="ecl-accordion__content"><div class="ecl">'
CONTENT_CLOSE = "</div></div></details>"


def trim_page(html: str, plan: list[tuple[str, slice]], extra_marker: str | None) -> str:
    """Keep, from the accordion sections named in `plan`, the file entries in the slice."""
    title = re.search(r"<title>.*?</title>", html, re.S).group(0)
    out = ['<!DOCTYPE html>\n<html lang="en" dir="ltr">\n<head>\n<meta charset="utf-8" />\n', title,
           "\n</head>\n<body>\n<!-- Trimmed copy of the EIOPA page named in the title; see SOURCES.md. -->\n"]
    if extra_marker:
        # the paragraph that links to the previous releases page, verbatim
        i = html.index(extra_marker)
        start = html.rindex("<h2>", 0, i)
        end = html.index("</p>", i) + len("</p>")
        out.append(html[start:end] + "\n")
    out.append('<div class="ecl-accordion" data-ecl-auto-init="Accordion">\n')
    for block in re.findall(r"<details\b.*?</details>", html, re.S):
        heading = re.search(r'<summary class="ecl-accordion__toggle">(.*?)<span', block, re.S).group(1).strip()
        for pattern, keep in plan:
            if re.fullmatch(pattern, heading):
                break
        else:
            continue
        head, rest = block.split(CONTENT_OPEN, 1)
        body = rest[: -len(CONTENT_CLOSE)]
        entries = [FILE_MARK + e for e in body.split(FILE_MARK)[1:]]
        out.append(head + CONTENT_OPEN + "".join(entries[keep]) + CONTENT_CLOSE + "\n")
    out.append("</div>\n</body>\n</html>\n")
    return "".join(out)


def trim_rss(xml: str, keep: list[str]) -> str:
    """Keep the channel header and the items whose link ends with one of `keep`."""
    head = xml[: xml.index("<item>")]
    items = re.findall(r"<item>.*?</item>", xml, re.S)
    chosen = [i for i in items if any(re.search(r"<link>[^<]*" + re.escape(k) + "</link>", i) for k in keep)]
    return head + "    " + "\n    ".join(chosen) + "\n  </channel>\n</rss>\n"


def trim_throttled(html: str) -> str:
    """The 429 page EIOPA's CDN served, reduced to its title, heading and message."""
    keep = [re.search(r"<title>.*?</title>", html, re.S).group(0),
            re.search(r"<h1 class=\"ecl-page-header-core__title\">.*?</h1>", html, re.S).group(0),
            re.search(r"<p class=\"ecl-page-header-core__description\">.*?</p>", html, re.S).group(0)]
    return ('<html lang="en" class="no-js">\n  <head>\n    <meta charset="utf-8" />\n    ' + keep[0]
            + "\n  </head>\n  <body>\n    <!-- Trimmed copy of the page served with HTTP 429; see SOURCES.md. -->\n    "
            + keep[1] + "\n    " + keep[2] + "\n  </body>\n</html>\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("release-2026-08", "release-2026-07", "release-2022-12", "page", "archive-page", "rss",
                 "throttled"):
        ap.add_argument("--" + flag, required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "fixtures")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    recent = {"EUR", "DE", "CZ", "CH", "UK", "CO", "US"}
    outputs = {
        "EIOPA_RFR_20260831.zip": trim_release(a.release_2026_08.read_bytes(), recent),
        "EIOPA_RFR_20260731.zip": trim_release(a.release_2026_07.read_bytes(), recent),
        "december_2022.zip": trim_release(a.release_2022_12.read_bytes(), {"EUR", "GB", "US", "RU"}),
        "rfr_page.html": trim_page(a.page.read_text(encoding="utf-8"), [
            (r"Monthly technical information 2026", slice(0, 2)),
            (r"Monthly Technical information 2023", slice(-2, None)),
            (r"IBOR transition implementation: Parallel calculations", slice(0, 1)),
            (r"Background material", slice(0, 2)),
            (r"RFR for the purposes of Financial Stability reporting.*", slice(None, None, 7)),
            (r"New market data provider: Parallel calculations", slice(0, 1)),
            (r"Extraordinary RFR updates", slice(0, 1)),
        ], "Go to the previous RFR releases").encode("utf-8"),
        "rfr_previous_releases.html": trim_page(a.archive_page.read_text(encoding="utf-8"), [
            (r"Monthly technical information - 2022", slice(0, 3)),
            (r"Monthly technical information - 2016", slice(0, 2)),
            (r"Background material - Previous releases", slice(0, 1)),
        ], None).encode("utf-8"),
        "rss.xml": trim_rss(a.rss.read_text(encoding="utf-8"), [
            "EIOPA_RFR_20260831.zip", "EIOPA_RFR_20260731.zip", "eiopa_rfr_20221231.zip",
            "EIOPA_FSR_RFR_20260630.zip", "eiopa_rfr_20200915.zip", "dual_run_eiopa_rfr_20211231.zip",
            "EIOPA-BoS-25-599%20-%20RFR%20Technical%20Documentation.pdf",
        ]).encode("utf-8"),
        "throttled_429.html": trim_throttled(a.throttled.read_text(encoding="utf-8", errors="replace"))
        .encode("utf-8"),
    }
    for name, data in outputs.items():
        (a.out / name).write_bytes(data)
        print(f"{name:32} {len(data):>8} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
    for flag in ("release_2026_08", "release_2026_07", "release_2022_12", "page", "archive_page", "rss",
                 "throttled"):
        p = getattr(a, flag)
        print(f"raw {p.name:40} {p.stat().st_size:>8} bytes  sha256 {hashlib.sha256(p.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
