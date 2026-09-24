"""Number extraction: each reading rule and each exclusion, one at a time."""
import unittest
from decimal import Decimal

from tests.support import IsolatedTestCase, excluded, kept, scan, tieout


def one(text, locale="en", **kw):
    nums = kept(text, locale, **kw)
    assert len(nums) == 1, [(n.written, n.reason) for n in scan(text, locale, **kw)]
    return nums[0]


class NumberFormat(IsolatedTestCase):
    def test_english_grouping_and_decimal(self):
        n = one("Revenue 1,234,567.89 in total")
        self.assertEqual((n.mantissa, n.decimals), (Decimal("1234567.89"), 2))

    def test_german_grouping_and_decimal(self):
        n = one("Umsatz 1.234.567,89 insgesamt", "de")
        self.assertEqual((n.mantissa, n.decimals), (Decimal("1234567.89"), 2))

    def test_lone_separator_with_three_digits_follows_the_document(self):
        self.assertEqual(one("1,234 staff", "en").mantissa, Decimal("1234"))
        self.assertEqual(one("1,234 staff", "de").mantissa, Decimal("1.234"))
        self.assertEqual(one("1.234 staff", "de").mantissa, Decimal("1234"))
        self.assertEqual(one("1.234 staff", "en").mantissa, Decimal("1.234"))
        self.assertIn("read as thousands", one("1.234 staff", "de").notes[0])

    def test_unambiguous_forms_win_over_the_document_locale(self):
        n = one("margin 14,2 in an English text", "en")
        self.assertEqual((n.mantissa, n.decimals), (Decimal("14.2"), 1))
        self.assertIn("de number format", n.notes[0])
        self.assertEqual(one("Marge 14.25 im Text", "de").mantissa, Decimal("14.25"))

    def test_leading_zero_is_always_a_decimal(self):
        self.assertEqual(one("0,125 share", "en").mantissa, Decimal("0.125"))

    def test_space_apostrophe_and_thin_space_grouping(self):
        self.assertEqual(one("CHF 1'234.50").mantissa, Decimal("1234.50"))
        self.assertEqual(one("4 213 500 €", "de").mantissa, Decimal("4213500"))
        self.assertEqual(one("4 213,5 €", "de").mantissa, Decimal("4213.5"))

    def test_malformed_groupings_are_excluded(self):
        self.assertEqual(excluded("options 1,2,3"), {"1,2,3": tieout.R_MALFORMED})
        self.assertEqual(excluded("build 12,34,567 units"), {"12,34,567": tieout.R_MALFORMED})

    def test_nbsp_between_two_numbers_splits_them(self):
        nums = kept("in 2025 1,310 staff")
        self.assertEqual([n.mantissa for n in nums], [Decimal("1310")])


class SignsAndUnits(IsolatedTestCase):
    def test_parentheses_are_negative(self):
        n = one("Net result (1,234)", table=True)
        self.assertTrue(n.negative)
        self.assertEqual(n.sign, "parentheses")
        n = one("impairment (€4.2m)")
        self.assertEqual((n.negative, n.scale_exp, n.currency), (True, 6, "€"))

    def test_minus_signs(self):
        for text in ("-3.2%", "−3.2%", "a change of –3.2%", "€-3.2m", "-€3.2m"):
            self.assertTrue(one(text).negative, text)

    def test_hyphen_after_a_word_is_not_a_minus(self):
        self.assertEqual(excluded("COVID-19 costs"), {"19": tieout.R_CODE})

    def test_percent_forms(self):
        for text in ("61%", "61 %", "61 %", "61 per cent", "61 percent", "61 Prozent", "61pc"):
            self.assertEqual(one(text).unit, "%", text)

    def test_percentage_points_basis_points_per_mille(self):
        self.assertEqual(one("up 3.2pp").unit, "pp")
        self.assertEqual(one("up 3.2 percentage points").unit, "pp")
        self.assertEqual(one("150bps tighter").unit, "bp")
        self.assertEqual(one("150 basis points").unit, "bp")
        self.assertEqual(one("2‰ defaults").unit, "‰")

    def test_currency_symbols_and_codes(self):
        cases = {"€4.2bn": "€", "EUR 4.2bn": "EUR", "4.2bn EUR": "EUR", "US$4.2bn": "US$", "£3m": "£",
                 "4,2 Mrd. €": "€", "4.213 TEUR": "EUR", "3.1 million euros": "euros"}
        for text, cur in cases.items():
            n = one(text, "de" if "Mrd" in text or "TEUR" in text else "en")
            self.assertEqual(n.currency, cur, text)

    def test_scale_words_and_suffixes(self):
        cases = {"350k": 3, "350K users": 3, "4.2m": 6, "4.2mn": 6, "4.2 million": 6, "$4.2MM": 6, "4.2bn": 9,
                 "4.2 billion": 9, "$4.2B": 9, "1.2tn": 12, "$1.2T": 12, "12 thousand": 3}
        for text, exp in cases.items():
            self.assertEqual(one(text).scale_exp, exp, text)
        de = {"4,2 Mio.": 6, "4,2 Mrd.": 9, "4,2 Millionen": 6, "4,2 Milliarden": 9, "350 Tsd.": 3,
              "4,2 Billionen": 12, "4,2 Billion": 12}
        for text, exp in de.items():
            self.assertEqual(one(text, "de").scale_exp, exp, text)

    def test_german_billion_is_ten_to_the_twelve_only_in_german(self):
        self.assertEqual(one("4.2 Billion", "en").scale_exp, 9)

    def test_units_that_look_like_scales(self):
        self.assertEqual(one("a 4.2m² office").scale_exp, 0)
        self.assertEqual(one("12mm pipe").scale_exp, 0)
        self.assertEqual(one("350km route").scale_exp, 0)
        self.assertEqual(excluded("3T towers"), {"3": tieout.R_CODE})

    def test_scale_before_a_footnote_marker(self):
        nums = scan("Revenue €4.2bn¹ in total")
        self.assertEqual([(n.written, n.status) for n in nums], [("€4.2bn", None), ("¹", "excluded")])
        self.assertEqual(nums[0].scale_exp, 9)

    def test_multiples(self):
        for text in ("3.1x", "3.1×", "12.5x EBITDA"):
            self.assertEqual(one(text).unit, "x", text)
        self.assertEqual([n.unit for n in kept("a 3 x 4 grid")], [None, None])

    def test_ranges_share_units_scale_and_currency(self):
        a, b = kept("growth of 10–12% a year")
        self.assertEqual((a.unit, b.unit, a.range_role, b.range_role), ("%", "%", "from", "to"))
        a, b = kept("€10–12m budget")
        self.assertEqual((a.scale_exp, a.currency, b.scale_exp, b.currency), (6, "€", 6, "€"))
        a, b = kept("10 to 12% share")
        self.assertEqual(a.unit, "%")
        a, b = kept("between 10-12 sites")
        self.assertEqual((a.negative, b.negative), (False, False))

    def test_a_spaced_hyphen_before_a_number_is_a_minus(self):
        a, b = kept("from 10 -12 to 4")[:2]
        self.assertTrue(b.negative)

    def test_qualifiers(self):
        self.assertEqual(one("about 1,300 staff").qualifier, ("approximate", "about"))
        self.assertEqual(one("c. €4bn").qualifier, ("approximate", "c."))
        self.assertEqual(one("~60%").qualifier, ("approximate", "~"))
        self.assertEqual(one("more than 60%").qualifier, ("lower", "more than"))
        self.assertEqual(one("mehr als 60 %", "de").qualifier, ("lower", "mehr als"))
        self.assertEqual(one("up to €5bn").qualifier, ("upper", "up to"))
        self.assertIsNone(one("up 8.8% on 2024").qualifier)
        self.assertIsNone(one("etc. 12 more").qualifier)


class Exclusions(IsolatedTestCase):
    def test_years(self):
        for text in ("in 2025", "FY'25", "(2025)", "2025E", "2024–2026", "2025/26"):
            reasons = set(excluded(text).values())
            self.assertEqual(reasons, {tieout.R_YEAR}, text)
        self.assertEqual(kept("2,025 sites")[0].mantissa, Decimal("2025"))
        self.assertEqual(kept("€2025m")[0].mantissa, Decimal("2025"))

    def test_dates(self):
        for text in ("on 2026-09-24", "am 24.09.2026", "on 09/24/26", "on 24 September 2026", "on September 24, 2026",
                     "Stand: 24. September 2026", "in Sep-26", "Oct 10–12", "per 09/2026"):
            reasons = set(excluded(text, "de" if "Stand" in text else "en").values())
            self.assertEqual(reasons, {tieout.R_DATE}, text)

    def test_times(self):
        for text in ("at 14:30", "at 9.30am", "um 14 Uhr", "at 2pm"):
            self.assertEqual(set(excluded(text).values()), {tieout.R_TIME}, text)

    def test_page_and_slide_numbers(self):
        for text in ("see page 12", "see p. 12", "pp. 12–14", "S. 45", "slide 4", "Folie 3", "Page 3 of 10"):
            self.assertEqual(set(excluded(text).values()), {tieout.R_PAGE}, text)

    def test_standalone_page_number_lines(self):
        for line in ("12", "- 12 -", "Page 3", "3 / 10", "| 7"):
            self.assertEqual(set(excluded(line, lines=True).values()), {tieout.R_PAGE}, line)
        self.assertEqual(kept("12", table=True)[0].mantissa, Decimal("12"))

    def test_footnote_markers(self):
        self.assertEqual(excluded("grew 12%¹ in 2025")["¹"], tieout.R_FOOTNOTE)
        self.assertEqual(excluded("as reported [1]"), {"1": tieout.R_FOOTNOTE})
        self.assertEqual(excluded("as reported[^2]"), {"2": tieout.R_FOOTNOTE})
        self.assertEqual(excluded("studies [1, 3]"), {"1": tieout.R_FOOTNOTE, "3": tieout.R_FOOTNOTE})
        self.assertEqual(excluded("a 12 m² room")["²"], tieout.R_EXPONENT)

    def test_list_numbering(self):
        for text in ("1. Introduction", "2) Market", "(3) Outlook", "2.1 Market overview", "## 4. Results",
                     "- 5. Next steps"):
            self.assertEqual(set(excluded(text).values()), {tieout.R_LIST}, text)
        self.assertEqual(kept("2.1 million users")[0].scale_exp, 6)
        self.assertEqual(kept("12% of users")[0].unit, "%")

    def test_phone_numbers(self):
        for text in ("call +49 30 1234567", "Tel. 030 123456", "(030) 1234-567", "0800 123 4567", "T: +44 20 7946 0000"):
            reasons = set(excluded(text).values())
            self.assertEqual(reasons, {tieout.R_PHONE}, text)
        self.assertEqual(len(kept("+12.5 13.1 14.6")), 3)

    def test_labels(self):
        for text in ("Scope 3 emissions", "Scope 1, 2 and 3", "Figure 2", "ISO 14001", "Article 8", "§ 5", "#1 provider",
                     "Tabelle 1", "version 7", "SDG 13"):
            self.assertEqual(set(excluded(text).values()), {tieout.R_LABEL}, text)
        self.assertEqual(kept("In Figure 3, 61% of sites")[0].written, "61%")

    def test_codes(self):
        for text in ("CO2", "Q3", "FY25", "5G", "3D", "B2B", "COVID-19", "1H25", "tCO2e", "x86"):
            self.assertTrue(excluded(text), text)
            self.assertEqual(set(excluded(text).values()), {tieout.R_CODE}, text)

    def test_units_glued_to_numbers_are_kept(self):
        n = one("60GWh generated")
        self.assertEqual((n.mantissa, n.unit_word), (Decimal("60"), "GWh"))

    def test_ordinals(self):
        self.assertEqual(excluded("the 1st and 22nd"), {"1": tieout.R_ORDINAL, "22": tieout.R_ORDINAL})

    def test_links_emails_and_dois(self):
        self.assertEqual(set(excluded("see https://example.com/2025/report-12").values()), {tieout.R_LINK})
        self.assertEqual(set(excluded("mail cfo2025@example.com").values()), {tieout.R_LINK})
        self.assertEqual(set(excluded("doi:10.1016/j.jclepro.2023.01.004").values()), {tieout.R_LINK})

    def test_unit_label_thousands(self):
        self.assertEqual(excluded("Customers ('000)"), {"000": tieout.R_UNITLABEL})

    def test_min_digits(self):
        self.assertEqual(excluded("3 markets and 12 sites", min_digits=2), {"3": "fewer than 2 digits (--min-digits)"})


class Locale(IsolatedTestCase):
    def detect(self, *texts):
        return tieout.detect_locale([tieout.Segment(t, "x") for t in texts])

    def test_german_document(self):
        loc, ev = self.detect("Umsatz 4,2 Mrd. €", "1.234,5 und 14,2 %")
        self.assertEqual(loc, "de")
        self.assertEqual(ev["basis"], "number format")

    def test_english_document(self):
        self.assertEqual(self.detect("Revenue €4.2bn", "margin 14.2%")[0], "en")

    def test_dates_and_links_are_not_evidence(self):
        loc, ev = self.detect("am 24.09.2026 unter https://x.de/1.234,5")
        self.assertEqual((ev["en_numbers"], ev["de_numbers"]), (0, 0))

    def test_language_breaks_a_tie(self):
        loc, ev = self.detect("Die Zahl der Kunden ist 1.234 und die Zahl der Standorte ist 12")
        self.assertEqual(loc, "de")
        self.assertTrue(ev["basis"].startswith("language"))

    def test_no_evidence_defaults_to_english(self):
        self.assertEqual(self.detect("12 34")[0], "en")


if __name__ == "__main__":
    unittest.main()
