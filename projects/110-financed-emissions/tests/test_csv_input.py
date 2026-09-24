"""What real CSV exports look like: Excel encodings, delimiters, decimal commas, broken files."""
import codecs
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import financed_emissions as fe  # noqa: E402

D = Decimal
HEADER = "position_id,counterparty,asset_class,currency,outstanding,denominator,scope1_tco2e,scope2_tco2e,dq_score"
ROW = "P1,Société Générale Immobilière (fictional),mortgage,EUR,150000,300000,4.2,1.0,4"
CSV = HEADER + "\r\n" + ROW + "\r\n"


class Encodings(unittest.TestCase):
    def check(self, data, encoding_label):
        result = fe.compute(data)
        self.assertEqual(result["input"]["encoding"], encoding_label)
        p = result["positions"][0]
        self.assertEqual(p["counterparty"], "Société Générale Immobilière (fictional)")
        self.assertEqual(p["financed"]["scope1"], D("2.1"))
        return result

    def test_utf8(self):
        self.check(CSV.encode("utf-8"), "utf-8")

    def test_utf8_with_bom_from_excel(self):
        self.check(codecs.BOM_UTF8 + CSV.encode("utf-8"), "utf-8-sig")

    def test_utf16_with_bom(self):
        self.check(CSV.encode("utf-16"), "utf-16")

    def test_utf16_le_without_bom(self):
        self.check(CSV.encode("utf-16-le"), "utf-16-le")

    def test_utf16_be_without_bom(self):
        self.check(CSV.encode("utf-16-be"), "utf-16-be")

    def test_windows_1252_fallback(self):
        result = self.check(CSV.encode("cp1252"), "cp1252")
        self.assertTrue(any("not valid UTF-8" in n for n in result["notes"]))

    def test_latin1_when_cp1252_cannot_decode(self):
        # 0x81 is unassigned in Windows-1252, so only Latin-1 can read this file.
        data = CSV.encode("latin-1") + b"P2,\x81x,mortgage,EUR,1,2,1,1,4\n"
        result = fe.compute(data)
        self.assertEqual(result["input"]["encoding"], "latin-1")

    def test_explicit_encoding(self):
        result = fe.compute(CSV.encode("cp1252"), encoding="cp1252")
        self.assertEqual(result["positions"][0]["counterparty"], "Société Générale Immobilière (fictional)")
        with self.assertRaises(fe.InputError):
            fe.compute(CSV.encode("cp1252"), encoding="utf-8")
        with self.assertRaises(fe.InputError):
            fe.compute(CSV.encode("utf-8"), encoding="no-such-codec")

    def test_nul_bytes_that_are_not_utf16(self):
        with self.assertRaises(fe.InputError) as ctx:
            fe.compute(b"\x00\x00position_id\x00\x00,\x00a")
        self.assertIn("NUL", str(ctx.exception))

    def test_xlsx_is_refused_with_advice(self):
        with self.assertRaises(fe.InputError) as ctx:
            fe.compute(b"PK\x03\x04" + b"\x00" * 40)
        self.assertIn("save the sheet as CSV", str(ctx.exception))


class Layout(unittest.TestCase):
    def test_semicolon_and_decimal_comma(self):
        text = HEADER.replace(",", ";") + "\n" + "P1;Haus (fictional);mortgage;EUR;150.000;300.000;4,2;1,0;4\n"
        result = fe.compute(text.encode("utf-8"), decimal_comma=True)
        self.assertEqual(result["input"]["delimiter"], ";")
        self.assertEqual(result["positions"][0]["financed"]["scope1"], D("2.1"))

    def test_decimal_comma_without_the_flag_is_refused_not_misread(self):
        text = HEADER.replace(",", ";") + "\n" + "P1;Haus (fictional);mortgage;EUR;150000;300000;4,2;1;4\n"
        result = fe.compute(text.encode("utf-8"))
        self.assertIn("--decimal-comma", " ".join(result["not_computed"][0]["reasons"]))

    def test_tab_separated(self):
        text = HEADER.replace(",", "\t") + "\n" + ROW.replace(",", "\t") + "\n"
        result = fe.compute(text.encode("utf-8"))
        self.assertEqual(result["input"]["delimiter"], "tab")
        self.assertEqual(len(result["positions"]), 1)

    def test_excel_sep_line(self):
        text = "sep=;\n" + HEADER.replace(",", ";") + "\n" + ROW.replace(",", ";") + "\n"
        result = fe.compute(text.encode("utf-8"))
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["positions"][0]["line"], 3)

    def test_quoted_fields_blank_lines_and_header_spelling(self):
        header = "Position ID,Counterparty,Asset Class,Currency,Outstanding,Denominator,Scope1-tCO2e,Scope2 tCO2e,DQ score"
        text = header + "\n\n" + 'P1,"Smith, Jones & Co (fictional)",mortgage,EUR,"150,000,000.5",300000000,4.2,1,4\n\n'
        result = fe.compute(text.encode("utf-8"))
        p = result["positions"][0]
        self.assertEqual(p["counterparty"], "Smith, Jones & Co (fictional)")
        self.assertEqual(p["outstanding"], D("150000000.5"))

    def test_unknown_columns_are_noted(self):
        text = HEADER + ",internal_rating\n" + ROW + ",AA\n"
        result = fe.compute(text.encode("utf-8"))
        self.assertTrue(any("ignored columns: internal_rating" in n for n in result["notes"]))

    def test_more_cells_than_columns(self):
        result = fe.compute((HEADER + "\n" + ROW + ",surplus\n").encode("utf-8"))
        self.assertIn("more cells than the header", result["not_computed"][0]["reasons"][0])

    def test_short_rows_are_padded(self):
        text = HEADER + ",scope3_tco2e,dq_score_scope3\n" + ROW + "\n"
        result = fe.compute(text.encode("utf-8"))
        self.assertIsNone(result["positions"][0]["financed"]["scope3"])


class BrokenFiles(unittest.TestCase):
    def test_empty(self):
        for data in (b"", b"   \n\n", codecs.BOM_UTF8):
            with self.assertRaises(fe.InputError):
                fe.compute(data)

    def test_header_only(self):
        result = fe.compute((HEADER + "\n").encode("utf-8"))
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["not_computed"], [])
        text = fe.render(result)
        self.assertIn("Every position was computed", text)

    def test_missing_required_columns(self):
        with self.assertRaises(fe.InputError) as ctx:
            fe.compute(b"position_id,asset_class,outstanding\nA,mortgage,1\n")
        self.assertIn("denominator", str(ctx.exception))
        self.assertIn("dq_score", str(ctx.exception))

    def test_duplicate_columns(self):
        with self.assertRaises(fe.InputError):
            fe.compute((HEADER + ",outstanding\n" + ROW + ",1\n").encode("utf-8"))

    def test_missing_file_and_directory(self):
        with self.assertRaises(fe.InputError):
            fe.compute_file("/nonexistent/portfolio.csv")
        with self.assertRaises(fe.InputError):
            fe.compute_file(str(Path(__file__).resolve().parent))


class Numbers(unittest.TestCase):
    def test_accepted(self):
        cases = {"1234.5": "1234.5", "1,234,567": "1234567", "1,234.5": "1234.5", "1 234 567": "1234567",
                 "1'234'567.5": "1234567.5", "1.5e3": "1500", "-2": "-2", ".5": "0.5", " 7 ": "7",
                 "1\u00a0234": "1234"}
        for raw, want in cases.items():
            self.assertEqual(fe.parse_decimal(raw), D(want), raw)

    def test_refused(self):
        for raw in ("1,234", "12,5", "nan", "inf", "Infinity", "1e30", "€100", "1.2.3", "0x10", "1_000", "--1"):
            with self.assertRaises(ValueError, msg=raw):
                fe.parse_decimal(raw)

    def test_decimal_comma(self):
        cases = {"1.234,5": "1234.5", "12,5": "12.5", "1 234,5": "1234.5", "1.234.567": "1234567", "7": "7"}
        for raw, want in cases.items():
            self.assertEqual(fe.parse_decimal(raw, decimal_comma=True), D(want), raw)
        with self.assertRaises(ValueError):
            fe.parse_decimal("1.5", decimal_comma=True)

    def test_blank(self):
        self.assertIsNone(fe.parse_decimal(""))
        self.assertIsNone(fe.parse_decimal("   "))
        self.assertIsNone(fe.parse_decimal(None))


if __name__ == "__main__":
    unittest.main()
