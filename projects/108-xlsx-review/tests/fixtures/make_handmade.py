"""Regenerate excel_shared_formulas.xlsx: worksheet XML written by hand in the layout Excel uses for
shared formulas, standard library only.

    python3 tests/fixtures/make_handmade.py

Source for the markup: ECMA-376 Part 1, 5th edition (December 2016), §18.3.1.40 "f (Formula)",
pages 1630-1633: the first cell of a shared group carries t="shared", ref (the range) and si (the
group index) and the formula text; the other cells carry only t="shared" and si, and their formula
is "based on the cell's relative location to the master formula cell". A cell inside the range
without si and t keeps its own formula ("the particular cell's formula shall override").
Array formulas carry t="array" and ref on their first cell; the other cells of the array hold only
cached values.

The cached values are what the formulas compute, worked out by hand; nothing here calculates.
The app.xml says this file was written by hand, not by Excel.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from support import workbook  # noqa: E402

HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="x14ac xr xr2 xr3" '
        'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" '
        'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
        'xmlns:xr2="http://schemas.microsoft.com/office/spreadsheetml/2015/revision2" '
        'xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3" '
        'xr:uid="{00000000-0001-0000-0000-000000000000}">')
TAIL = '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>'

# Shared strings, in order of first use: 0 Qty, 1 Price, 2 Amount, 3 Running, 4 Share, 5 Rate, 6 Total
CALC = HEAD + '''<dimension ref="A1:J8"/><sheetViews><sheetView tabSelected="1" workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15" x14ac:dyDescent="0.25"/><sheetData>
<row r="1" spans="1:10" x14ac:dyDescent="0.25"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c><c r="F1"><v>0.2</v></c></row>
<row r="2" spans="1:10" x14ac:dyDescent="0.25"><c r="A2"><v>1</v></c><c r="B2"><v>10</v></c><c r="C2"><f t="shared" ref="C2:C6" si="0">A2*B2</f><v>10</v></c><c r="D2"><f t="shared" ref="D2:D6" si="1">SUM($C$2:C2)</f><v>10</v></c><c r="E2"><f t="shared" ref="E2:E6" si="2">C2/$D$6</f><v>1.8148820326678767E-2</v></c><c r="G2"><f t="shared" ref="G2:G6" si="3">C2*F$1</f><v>2</v></c><c r="H2"><f t="shared" ref="H2:I4" si="5">A2+$B2+Other!A1</f><v>111</v></c><c r="I2"><f t="shared" si="5"/><v>220</v></c><c r="J2"><f t="array" ref="J2:J4">A2:A4*10</f><v>10</v></c></row>
<row r="3" spans="1:10" x14ac:dyDescent="0.25"><c r="A3"><v>2</v></c><c r="B3"><v>20</v></c><c r="C3"><f t="shared" si="0"/><v>40</v></c><c r="D3"><f t="shared" si="1"/><v>50</v></c><c r="E3"><f t="shared" si="2"/><v>7.2595281306715071E-2</v></c><c r="G3"><f t="shared" si="3"/><v>8</v></c><c r="H3"><f t="shared" si="5"/><v>322</v></c><c r="I3"><f t="shared" si="5"/><v>440</v></c><c r="J3"><v>20</v></c></row>
<row r="4" spans="1:10" x14ac:dyDescent="0.25"><c r="A4"><v>3</v></c><c r="B4"><v>30</v></c><c r="C4"><f t="shared" si="0"/><v>90</v></c><c r="D4"><f t="shared" si="1"/><v>140</v></c><c r="E4"><f t="shared" si="2"/><v>0.16333938294010888</v></c><c r="G4"><f t="shared" si="3"/><v>18</v></c><c r="H4"><f t="shared" si="5"/><v>33</v></c><c r="I4"><f t="shared" si="5"/><v>60</v></c><c r="J4"><v>30</v></c></row>
<row r="5" spans="1:10" x14ac:dyDescent="0.25"><c r="A5"><v>4</v></c><c r="B5"><v>40</v></c><c r="C5"><f>A5*B5+1</f><v>161</v></c><c r="D5"><f t="shared" si="1"/><v>301</v></c><c r="E5"><f t="shared" si="2"/><v>0.29219600725952816</v></c><c r="G5"><f t="shared" si="3"/><v>32.200000000000003</v></c></row>
<row r="6" spans="1:10" x14ac:dyDescent="0.25"><c r="A6"><v>5</v></c><c r="B6"><v>50</v></c><c r="C6"><f t="shared" si="0"/><v>250</v></c><c r="D6"><f t="shared" si="1"/><v>551</v></c><c r="E6"><f t="shared" si="2"/><v>0.45372050816696918</v></c><c r="G6"><f t="shared" si="3"/><v>50</v></c></row>
<row r="8" spans="1:10" x14ac:dyDescent="0.25"><c r="A8" t="s"><v>6</v></c><c r="C8"><f t="shared" ref="C8:E8" si="4">SUM(C2:C6)</f><v>551</v></c><c r="D8"><f t="shared" si="4"/><v>1052</v></c><c r="E8"><f t="shared" si="4"/><v>1</v></c></row>
</sheetData>''' + TAIL

OTHER = HEAD.replace("{00000000-0001-0000-0000-000000000000}", "{00000000-0001-0000-0100-000000000000}") + '''<dimension ref="A1:D5"/><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15" x14ac:dyDescent="0.25"/><sheetData>
<row r="1" spans="1:4" x14ac:dyDescent="0.25"><c r="A1"><v>100</v></c><c r="B1"><v>200</v></c><c r="D1"><f t="shared" ref="D1:D5" si="0">Calc!C2*2</f><v>20</v></c></row>
<row r="2" spans="1:4" x14ac:dyDescent="0.25"><c r="A2"><v>300</v></c><c r="B2"><v>400</v></c><c r="D2"><f t="shared" si="0"/><v>80</v></c></row>
<row r="3" spans="1:4" x14ac:dyDescent="0.25"><c r="D3"><f t="shared" si="0"/><v>180</v></c></row>
<row r="4" spans="1:4" x14ac:dyDescent="0.25"><c r="D4"><f t="shared" si="0"/><v>322</v></c></row>
<row r="5" spans="1:4" x14ac:dyDescent="0.25"><c r="D5"><f t="shared" si="0"/><v>500</v></c></row>
</sheetData>''' + TAIL

STRINGS = ["Qty", "Price", "Amount", "Running", "Share", "Rate", "Total"]


def build() -> bytes:
    sst = "".join(f"<si><t>{s}</t></si>" for s in STRINGS)
    sst_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="http://schemas.openxmlformats.org/'
               f'spreadsheetml/2006/main" count="{len(STRINGS)}" uniqueCount="{len(STRINGS)}">{sst}</sst>').encode()
    # The builder writes a sharedStrings part only for strings it placed itself, so the part is supplied here.
    return workbook(sheets=[{"name": "Calc", "xml": CALC}, {"name": "Other", "xml": OTHER}],
                    names=[("Rate", "Calc!$F$1")], app="Hand-written XML in the layout Excel uses (xlsx-review test fixture)",
                    shared_strings=True, replace={"xl/sharedStrings.xml": sst_xml})


def main() -> int:
    data = build()
    (HERE / "excel_shared_formulas.xlsx").write_bytes(data)
    print("excel_shared_formulas.xlsx", len(data), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
