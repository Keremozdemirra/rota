"""Country input: what people type becomes the alpha-3 code the API expects, locally."""
import unittest

try:
    from . import ctfixtures as fx
except ImportError:
    import ctfixtures as fx

from climate_trace_mcp import countries as C


class ResolveTest(fx.HomeIsolated):
    def test_codes_in_any_case(self):
        for q in ("DEU", "deu", " DE ", "de"):
            self.assertEqual(C.resolve(q), ("DEU", "Germany"))
        self.assertEqual(C.resolve("PL")[0], "POL")
        self.assertEqual(C.resolve("GB")[0], "GBR")

    def test_english_names_with_and_without_accents(self):
        cases = {
            "Poland": "POL", "germany": "DEU", "Côte d'Ivoire": "CIV", "Cote d’Ivoire": "CIV",
            "Türkiye": "TUR", "Turkey": "TUR", "Åland Islands": "ALA", "Aland Islands": "ALA",
            "Curaçao": "CUW", "São Tomé and Príncipe": "STP",
        }
        for q, a3 in cases.items():
            self.assertEqual(C.resolve(q)[0], a3, q)

    def test_official_and_api_names_both_resolve(self):
        # The API still says "The former Yugoslav Republic of Macedonia"; UN M49 says "North Macedonia".
        self.assertEqual(C.resolve("North Macedonia")[0], "MKD")
        self.assertEqual(C.resolve("The former Yugoslav Republic of Macedonia")[0], "MKD")
        self.assertEqual(C.resolve("Netherlands (Kingdom of the)")[0], "NLD")
        self.assertEqual(C.resolve("the Netherlands")[0], "NLD")

    def test_common_names_and_parentheticals(self):
        cases = {"UK": "GBR", "U.S.A.": "USA", "United States": "USA", "Russia": "RUS", "Iran": "IRN",
                 "Bolivia": "BOL", "Vietnam": "VNM", "South Korea": "KOR", "North Korea": "PRK",
                 "DR Congo": "COD", "Congo": "COG", "Hong Kong": "HKG", "St. Lucia": "LCA",
                 "Micronesia": "FSM", "Czech Republic": "CZE", "Ivory Coast": "CIV"}
        for q, a3 in cases.items():
            self.assertEqual(C.resolve(q)[0], a3, q)

    def test_codes_climate_trace_uses_beyond_iso(self):
        self.assertEqual(C.resolve("Kosovo"), ("XKX", "Kosovo"))
        self.assertEqual(C.resolve("XKX")[0], "XKX")
        self.assertEqual(C.resolve("ZNC")[0], "ZNC")
        self.assertEqual(C.resolve("TW")[0], "TWN")
        self.assertNotIn("XK", C.BY_ALPHA2)  # not an ISO 3166-1 code; not invented here

    def test_unknown_and_ambiguous_names_fail_with_hints(self):
        with self.assertRaises(C.CountryError) as cm:
            C.resolve("Korea")
        self.assertIn("Republic of Korea", str(cm.exception))
        with self.assertRaises(C.CountryError):
            C.resolve("Atlantis")
        with self.assertRaises(C.CountryError):
            C.resolve("XYZ")  # three letters, but not a code in the table

    def test_bad_input_types_and_hostile_text(self):
        for bad in (None, 276, ["DEU"], "", "   "):
            with self.assertRaises(C.CountryError):
                C.resolve(bad)
        with self.assertRaises(C.CountryError) as cm:
            C.resolve("Germ\x1b[2Jany‮" + "x" * 500)
        msg = str(cm.exception)
        self.assertNotIn("\x1b", msg)
        self.assertNotIn("‮", msg)
        self.assertLess(len(msg), 400)

    def test_table_shape(self):
        self.assertEqual(len(C.BY_ALPHA3), 251)
        self.assertTrue(all(len(k) == 3 and k.isupper() for k in C.BY_ALPHA3))
        self.assertTrue(all(len(k) == 2 and v in C.BY_ALPHA3 for k, v in C.BY_ALPHA2.items()))
        self.assertEqual(len(set(C.BY_ALPHA2.values())), len(C.BY_ALPHA2))


if __name__ == "__main__":
    unittest.main()
