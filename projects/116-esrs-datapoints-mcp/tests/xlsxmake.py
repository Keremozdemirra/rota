"""Writes tiny .xlsx files from raw XML, for the edge cases a spreadsheet program would never produce."""
import zipfile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PNS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rows_xml(rows, inline=True):
    """rows: list of lists; a str cell becomes an inline string, an int a number, None nothing."""
    out = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{_col(c)}{r}"
            if v is None:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{esc(v)}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    return "".join(out)


def sheet_xml(body, merges=()):
    m = ""
    if merges:
        m = f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{x}"/>' for x in merges) + "</mergeCells>"
    return f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS}"><sheetData>{body}</sheetData>{m}</worksheet>'


def write(path, sheets, shared=None, extra=None, workbook_xml=None):
    """sheets: list of (name, sheet XML string, state or None)."""
    wb_sheets = "".join(
        f'<sheet name="{esc(n)}" sheetId="{i}" r:id="rId{i}"' + (f' state="{st}"' if st else "") + "/>"
        for i, (n, _x, st) in enumerate(sheets, 1))
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{RNS}/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1))
    if shared is not None:
        rels += f'<Relationship Id="rIdS" Type="{RNS}/sharedStrings" Target="sharedStrings.xml"/>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                                          'package/2006/content-types"/>')
        z.writestr("_rels/.rels", f'<?xml version="1.0"?><Relationships xmlns="{PNS}"><Relationship Id="r1" '
                                  f'Type="{RNS}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", workbook_xml or f'<?xml version="1.0"?><workbook xmlns="{NS}" xmlns:r="{RNS}">'
                                                      f'<sheets>{wb_sheets}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="{PNS}">{rels}'
                                                 f'</Relationships>')
        for i, (_n, xml, _st) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
        if shared is not None:
            z.writestr("xl/sharedStrings.xml", shared)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def simple(path, rows, name="Datapoints", merges=()):
    return write(path, [(name, sheet_xml(rows_xml(rows), merges), None)])
