"""Reading CN codes and country names as people type them."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cbam_test_support  # noqa: E402,F401
from cbam_mcp.codes import (ISO_BY_TABLE_NAME, InputError, cn_candidates, country_key, format_cn,  # noqa: E402
                            normalize_cn, resolve_country)


class CnCodes(unittest.TestCase):
    def test_spellings_of_one_code(self):
        for text in ("7208 51 20", "72085120", "7208.51.20", "7208-51-20", " 7208 51 20 ",
                     "7208  51 20", "CN 7208 51 20", 72085120):
            self.assertEqual(normalize_cn(text), ("72085120", []), repr(text))

    def test_prefix_lengths(self):
        self.assertEqual(normalize_cn("72")[0], "72")
        self.assertEqual(normalize_cn("7208")[0], "7208")
        self.assertEqual(normalize_cn("7208 51")[0], "720851")
        self.assertEqual(normalize_cn("2507 00 80 80")[0], "2507008080")

    def test_odd_length_is_read_as_prefix_with_warning(self):
        digits, warnings = normalize_cn("7202 2")
        self.assertEqual(digits, "72022")
        self.assertIn("prefix", warnings[0])

    def test_ex_prefix_is_ignored_and_said(self):
        self.assertEqual(normalize_cn("ex2507 00 80")[0], "25070080")  # review: no space after "ex"
        digits, warnings = normalize_cn("ex 2507 00 80")
        self.assertEqual(digits, "25070080")
        self.assertIn("'ex'", warnings[0])

    def test_rejects_what_is_not_a_code(self):
        for bad in ("", "   ", "72A8", "7", "12345678901", "٧٢٠٨", "7208x",
                    None, True, 7.5, ["7208"]):
            with self.assertRaises(InputError, msg=repr(bad)):
                normalize_cn(bad)

    def test_fullwidth_digits_are_digits(self):
        # NFKC turns the digits of East Asian input methods into ASCII; Arabic-Indic digits stay rejected.
        self.assertEqual(normalize_cn("７２０８")[0], "7208")

    def test_format_and_candidates(self):
        self.assertEqual(format_cn("72085120"), "7208 51 20")
        self.assertEqual(format_cn("2507008080"), "2507 00 80 80")
        self.assertEqual(format_cn("72022"), "7202 2")
        self.assertEqual(cn_candidates("2716"), ["2716", "271600", "27160000"])
        self.assertEqual(cn_candidates("722100"), ["722100", "72210000"])


class Countries(unittest.TestCase):
    TABLES = ["India", "Türkiye", "Korea, Republic of (South Korea)",
              "North Korea (Democratic People's Republic of Korea)", "Other Countries and Territories", "Namibia"]

    def test_names_codes_and_aliases(self):
        cases = {"India": "India", "IN": "India", "in": "India", "TÜRKIYE": "Türkiye", "Turkiye": "Türkiye",
                 "turkey": "Türkiye", "TR": "Türkiye", "South Korea": "Korea, Republic of (South Korea)",
                 "KR": "Korea, Republic of (South Korea)", "NA": "Namibia", "other": "Other Countries and Territories",
                 "North Korea (Democratic People’s Republic of Korea)":
                     "North Korea (Democratic People's Republic of Korea)"}
        for typed, name in cases.items():
            self.assertEqual(resolve_country(typed, self.TABLES)[0], name, typed)

    def test_sourced_and_tool_aliases(self):
        tables = self.TABLES + ["China", "United States", "United Kingdom"]
        extra = {"Czechia": {"iso": "CZ", "kind": "eu"}}
        for typed, name in {"PRC": "China", "People’s Republic of China": "China",
                            "S. Korea": "Korea, Republic of (South Korea)", "ROK": "Korea, Republic of (South Korea)",
                            "USA": "United States", "UK": "United Kingdom", "Republic of Türkiye": "Türkiye",
                            "Czech Republic": "Czechia"}.items():
            self.assertEqual(resolve_country(typed, tables, extra)[0], name, typed)

    def test_extra_names_from_the_regulation(self):
        extra = {"Norway": {"iso": "NO", "kind": "annex_iii"}, "Germany": {"iso": "DE", "kind": "eu"}}
        self.assertEqual(resolve_country("NO", self.TABLES, extra)[0], "Norway")
        self.assertEqual(resolve_country("germany", self.TABLES, extra)[0], "Germany")

    def test_unknown_gives_suggestions_or_nothing(self):
        self.assertEqual(resolve_country("Indai", self.TABLES), (None, ["India"]))
        self.assertEqual(resolve_country("Kosovo", self.TABLES), (None, []))

    def test_bad_input(self):
        for bad in ("", "  ", None, 42, "x" * 101):
            with self.assertRaises(InputError):
                resolve_country(bad, self.TABLES)

    def test_iso_table_is_one_code_per_country(self):
        codes = list(ISO_BY_TABLE_NAME.values())
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(len(c) == 2 and c.isupper() for c in codes))

    def test_key_ignores_case_accents_apostrophes(self):
        self.assertEqual(country_key("Curaçao"), country_key("CURACAO"))
        self.assertEqual(country_key("People’s"), country_key("people's"))


if __name__ == "__main__":
    unittest.main()
