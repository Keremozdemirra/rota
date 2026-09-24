"""Reading the registry files: allowlist, cleaning, malformed rows, truncated and foreign files."""
import gzip
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import FILES, FIXTURES, PLACEHOLDERS, eu_ets, gz  # noqa: E402


def operators():
    st = eu_ets.Stats("operators")
    return list(eu_ets.read_operators(FILES["operators_daily.csv.gz"], st)), st


class Operators(unittest.TestCase):
    def test_counts_and_malformed_rows(self):
        rows, st = operators()
        d = st.as_dict()
        self.assertEqual((d["rows_read"], d["rows_kept"], d["malformed_rows"], d["duplicate_rows"]), (29, 25, 3, 1))
        self.assertEqual(d["rows_with_undecodable_bytes"], 1)
        self.assertIn("5 fields, expected 28", d["malformed_examples"][0])

    def test_only_allowlisted_fields_and_no_placeholder_text(self):
        rows, _ = operators()
        self.assertEqual(set(rows[0]), {"registry", "registry_name", "installation_id", "name", "name_withheld",
                                        "permit_id", "activity_code", "activity", "city", "lei", "lei_registered",
                                        "lei_ok", "first_year", "last_year", "permit_revoked"})
        blob = json.dumps(rows, ensure_ascii=False)
        for p in PLACEHOLDERS:
            self.assertNotIn(p, blob)

    def test_person_like_operator_name_is_withheld_with_its_city(self):
        rows, st = operators()
        ship = next(r for r in rows if r["installation_id"] == 223104)
        self.assertEqual((ship["name"], ship["name_withheld"], ship["city"]), (eu_ets.WITHHELD, 1, None))
        self.assertEqual(st.withheld, 10)
        kept = next(r for r in rows if r["installation_id"] == 232740)  # "Tropic 4 Limited"
        self.assertEqual(kept["name_withheld"], 0)

    def test_control_and_bidi_characters_are_stripped(self):
        rows, _ = operators()
        self.assertEqual(next(r for r in rows if r["installation_id"] == 262)["name"],
                         "Wiegand-Glashüttenwerke Werk Steinbach")

    def test_long_ids_leis_and_placeholders(self):
        rows, _ = operators()
        by = {(r["registry"], r["installation_id"]): r for r in rows}
        self.assertIn(("CY", 210000000000005), by)  # Cyprus uses 15-digit ids
        voest = by[("AT", 16)]
        self.assertEqual((voest["lei"], voest["lei_registered"], voest["lei_ok"]),
                         ("529900FGOWZKLBZ81V67", "5299-00FGOWZKLBZ81V-67", 1))
        self.assertEqual(by[("IE", 201019)]["lei_ok"], 0)  # as registered; check digits fail
        self.assertIsNone(by[("AT", 200442)]["city"])  # "-" in the registry
        self.assertIn("�", by[("DK", 347)]["city"])  # the Latin-1 byte, visible, not fatal


class Yearly(unittest.TestCase):
    def test_counts_orphans_and_missing_years(self):
        rows, _ = operators()
        known = {(r["registry"], r["installation_id"]) for r in rows}
        st = eu_ets.Stats("yearly")
        yearly = list(eu_ets.read_yearly(FILES["operators_yearly_activity_daily.csv.gz"], st, known))
        d = st.as_dict()
        self.assertEqual((d["malformed_rows"], d["duplicate_rows"], d["rows_without_installation"]), (3, 1, 1))
        self.assertEqual(d["rows_kept"], len(yearly))
        self.assertEqual(d["rows_read"], d["rows_kept"] + 3 + 1 + 1 + d["rows_without_values"])
        at14 = sorted(y[2] for y in yearly if y[:2] == ("AT", 14))
        self.assertNotIn(2008, at14)
        self.assertEqual((at14[0], at14[-1]), (2005, 2012))

    def test_missing_column_is_an_error_not_silent_nulls(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "y.csv.gz"
            p.write_bytes(gz("INSTALLATION_IDENTIFIER,REGISTRY_CODE,PERIOD_YEAR,VERIFIED_EMISSIONS\n1,AT,2020,5\n"))
            with self.assertRaisesRegex(eu_ets.ParseError, "SURR_ALL"):
                list(eu_ets.read_yearly(p, eu_ets.Stats("y"), set()))


class BrokenFiles(unittest.TestCase):
    def read(self, data: bytes):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "operators_daily.csv.gz"
            p.write_bytes(data)
            return list(eu_ets.read_operators(p, eu_ets.Stats("operators_daily.csv.gz")))

    def test_truncated_gzip(self):
        data = FILES["operators_daily.csv.gz"].read_bytes()
        with self.assertRaisesRegex(eu_ets.ParseError, "truncated"):
            self.read(data[: len(data) // 2])

    def test_html_error_page_instead_of_gzip(self):
        with self.assertRaisesRegex(eu_ets.ParseError, "not a readable gzip"):
            self.read(b"<html><body>Too Many Requests</body></html>")

    def test_empty_file(self):
        with self.assertRaisesRegex(eu_ets.ParseError, "empty"):
            self.read(gz(""))

    def test_nul_bytes_do_not_stop_the_reader(self):
        text = gzip.decompress(FILES["operators_daily.csv.gz"].read_bytes()).replace(b"Tarco", b"Tar\x00co")
        rows = self.read(gzip.compress(text))
        self.assertIn("Tarco Vej A/S", [r["name"] for r in rows])


class Compliance(unittest.TestCase):
    def test_codes_years_and_broken_rows(self):
        st = eu_ets.Stats("c")
        rows = list(eu_ets.read_compliance_xlsx(FILES["compliance_2024_code_en.xlsx"], 2024, st))
        self.assertIn(("DE", 69, 2024, "A", 2024), rows)
        self.assertIn(("AT", 201836, 2024, "EXCLUDED SINCE 2021", 2024), rows)  # empty year: the file's year
        self.assertEqual((st.malformed, st.read), (1, 11))  # the blank row under the header is not counted

    def test_names_in_the_compliance_file_are_not_read(self):
        rows = list(eu_ets.read_compliance_xlsx(FILES["compliance_2024_code_en.xlsx"], 2024, eu_ets.Stats("c")))
        self.assertNotIn("Mustermann", json.dumps(rows))

    def test_not_an_xlsx(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.xlsx"
            p.write_bytes(b"<html>429 Too Many Requests</html>")
            with self.assertRaisesRegex(eu_ets.ParseError, "not an XLSX"):
                list(eu_ets.read_compliance_xlsx(p, 2024, eu_ets.Stats("c.xlsx")))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("xl/workbook.xml", "<workbook")
            p.write_bytes(buf.getvalue())
            with self.assertRaisesRegex(eu_ets.ParseError, "unreadable XLSX"):
                list(eu_ets.read_compliance_xlsx(p, 2024, eu_ets.Stats("c.xlsx")))


class Helpers(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(eu_ets.clean_text("a‮b\x00c d​"), "a b c d")
        self.assertEqual(len(eu_ets.clean_text("x" * 500)), 240)
        self.assertEqual(eu_ets.clean_text(None), "")

    def test_lei_check_digits(self):
        # 549300QGIICV4ZFTKX83 is ThyssenKrupp Steel Europe AG at GLEIF (checked 2026-09-24)
        self.assertTrue(eu_ets.lei_check_digits_ok(eu_ets.normalize_lei("5493-00QGIICV4ZFTKX-83")))
        self.assertFalse(eu_ets.lei_check_digits_ok("549300QGIICV4ZFTKX84"))
        self.assertFalse(eu_ets.lei_check_digits_ok("43700H0UCVNPOGDUF25"))  # 19 characters, in the registry

    def test_name_guard(self):
        why = eu_ets.withhold_reason
        org = ("Nordwind Energie GmbH", "HRB 00001", "DE")
        # withheld: a holder who may be a person, and every sole-trader or partnership marker
        self.assertTrue(why("Ziegelei Erika Musterfrau", 20, "DE", "Musterstadt", "Erika Musterfrau", "", "DE"))
        self.assertTrue(why("Erika Musterfrau", 20, "DE", "", *org))  # a person-shaped name, whatever the holder
        for name in ("Hof Musterfrau e.K.", "Musterfrau Einzelunternehmen", "Kwekerij Musterfrau V.O.F.",
                     "Musterfrau eenmanszaak", "Tuilerie Musterfrau EIRL", "Juan Ejemplo empresario individual",
                     "Jan Musterfrau OSVČ", "Jana Musterfrau fyzická osoba", "Fornace Esempio ditta individuale",
                     "Partenreederei MS Beispiel", "Janez Musterfrau s.p."):
            self.assertEqual(why(name, 20, "DE", "", "Irgendwer", "", "DE"), "sole-trader or partnership marker", name)
        self.assertEqual(why("Ceramica Ejemplo", 32, "ES", "", "Juan Ejemplo", "00000000T", "ES"), "personal identifier")
        self.assertIsNone(why("Heizkraftwerk Nordhafen", 20, "DE", "Nordhafen", "Stadtwerke Nordhafen GmbH", "", "DE"))
        self.assertIsNone(why("f11407", 10, "AT", "", "Max Musterfrau", "", "AT"))  # aircraft operators are codes
        self.assertIsNone(why("X Power Plant", 20, "GB", "", *org))

    def test_guard_list_holes_from_the_review(self):
        form = eu_ets.has_legal_form
        # initials are not company forms, only a trailing form is
        self.assertFalse(form("A. B. Musterson"))
        self.assertFalse(form("S. A. Ejemplo"))
        self.assertFalse(form("K. G. Musterfrau"))
        self.assertTrue(form("SPP Mobilita s. r. o."))
        self.assertTrue(form("Volvo AB"))
        self.assertTrue(form("Rederiaktiebolaget Eckerö"))
        self.assertTrue(form("AVIA Mineralölhandelsges.m.b.H."))
        self.assertTrue(form("Musterfrau Sp. z o.o."))
        # "& Co", EIRL and partnership forms show no legal person
        for name in ("Janez Beispiel & Co", "Musterfrau & Cie", "Musterfrau EIRL", "Musterfrau GbR", "Musterfrau OHG"):
            self.assertFalse(form(name), name)
        self.assertFalse(form("Musterfrau sas", "IT"))  # an Italian s.a.s. is a partnership
        self.assertTrue(form("Musterfrau SAS", "FR"))
        # words that are also personal names do not explain a name
        for name in ("Marine Musterfrau", "Line Musterfrau", "Jet Musterfrau", "Anna Power"):
            self.assertTrue(eu_ets.withhold_reason(name, 50, "DK", "", "Nordwind Shipping A/S", "", "DK"), name)
        self.assertTrue(eu_ets.withhold_reason("Janez Beispiel & Co", 20, "SI", "", "Janez Beispiel & Co", "", "SI"))

    def test_greek_and_cyrillic_names_are_tokenised(self):
        self.assertTrue(eu_ets.has_legal_form("ΠΑΡΑΔΕΙΓΜΑ Α.Ε."))
        self.assertTrue(eu_ets.has_legal_form("Пример ЕООД"))
        self.assertEqual(eu_ets._words("ΠΑΡΑΔΕΙΓΜΑ ΜΟΝΟΠΡΟΣΩΠΗ"), ["παραδειγμα", "μονοπροσωπη"])

    def test_personal_identifier_formats(self):
        self.assertTrue(eu_ets.personal_id("00000000T", "ES"))
        self.assertFalse(eu_ets.personal_id("B00000000", "ES"))  # a company's CIF
        self.assertTrue(eu_ets.personal_id("RSSMRA80A01H501U", "IT"))
        self.assertFalse(eu_ets.personal_id("00000000000", "IT"))  # a partita IVA
        self.assertTrue(eu_ets.personal_id("800101-1234", "SE"))
        self.assertFalse(eu_ets.personal_id("556000-1234", "SE"))  # an organisation number


class Listing(unittest.TestCase):
    def entries(self):
        return json.loads((FIXTURES / "listing.json").read_text(encoding="utf-8"))

    def test_real_listing_resolves(self):
        files = eu_ets.resolve_files(self.entries())
        self.assertTrue(files["operators"].startswith("https://dlsclimabi.blob.core.windows.net/"))
        self.assertTrue(files["yearly"].endswith("/operators_yearly_activity_daily.csv.gz"))
        self.assertEqual(sorted(files["compliance"]), [2021, 2022, 2023, 2024])

    def test_foreign_hosts_plain_http_and_credentials_are_refused(self):
        for bad in ("https://evil.example.com/x/operators_daily.csv.gz", "http://climate.ec.europa.eu/operators_daily.csv.gz",
                    "https://user:pw@dlsclimabi.blob.core.windows.net/operators_daily.csv.gz",
                    "https://europa.eu.evil.com/operators_daily.csv.gz"):
            e = self.entries()
            e[1]["url"] = bad
            with self.assertRaises(eu_ets.FetchError):
                eu_ets.resolve_files(e)

    def test_listing_without_the_daily_files(self):
        with self.assertRaisesRegex(eu_ets.FetchError, "no longer offers operators_daily"):
            eu_ets.resolve_files([e for e in self.entries() if "operators_daily" not in e["url"]])


if __name__ == "__main__":
    unittest.main()
