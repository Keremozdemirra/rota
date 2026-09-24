"""The numbers in the code must be the numbers in the quoted legal texts of the bundled snapshot."""
import unittest

from support import DATA

import csrd_scope
import csrd_scope_cellar as cellar

Q = DATA.quotes


class CodeMatchesText(unittest.TestCase):
    def test_thresholds_are_in_the_quoted_provisions(self):
        checks = [
            ("AD-19a-1", ["exceed a net turnover of EUR 450 000 000 and an average number of 1 000 employees"]),
            ("AD-29a-1", ["on a consolidated basis, a net turnover of EUR 450 000 000 and an average number of 1 000 employees"]),
            ("AD-1-3", ["exceed a net turnover of EUR 450 000 000 and an average number of 1 000 employees"]),
            ("CSRD-5-2-b", ["for financial years starting on or after 1 January 2027"]),
            ("CSRD-5-2-sub2", ["for financial years starting on or after 1 January 2028"]),
            ("CSRD-5-2-a", ["for financial years starting between 1 January 2024 and 31 December 2026",
                            "the average number of 500 employees"]),
            ("CSRD-5-2-derogation", ["between 1 January 2025 and 31 December 2026", "EUR 450 000 000 or an average number of 1 000"]),
            ("AD-40a-1-2", ["EUR 200 000 000 in the preceding financial year"]),
            ("AD-40a-1-4", ["EUR 200 000 000 in the preceding financial year"]),
            ("AD-40a-1-5", ["EUR 450 000 000 for each of the last two consecutive financial years"]),
            ("AD-3-4", ["balance sheet total: EUR 25 000 000", "net turnover: EUR 50 000 000", "during the financial year: 250"]),
            ("ADOLD-3-4", ["balance sheet total: EUR 20 000 000", "net turnover: EUR 40 000 000"]),
            ("AD-3-10", ["two consecutive financial years"]),
            ("DD-2-1", ["on or after 1 January 2024", "on or after 1 January 2023"]),
            ("OMNI-5-1", ["by 19 March 2027"]),
            ("STC-3", ["by 31 December 2025"]),
            ("OMNI-oj", ["2026/470 26.2.2026"]),
            ("STC-oj", ["2025/794 16.4.2025"]),
            ("TD-8-1-b", ["at least EUR 100 000"]),
            ("SFDR-2-12", ["(b) an alternative investment fund (AIF)", "(f) a UCITS"]),
        ]
        for qid, fragments in checks:
            for f in fragments:
                with self.subTest(qid=qid, fragment=f):
                    self.assertIn(f, Q[qid]["text"])
        self.assertEqual(csrd_scope.NET_TURNOVER_EUR, 450_000_000)
        self.assertEqual(csrd_scope.EMPLOYEES, 1_000)
        self.assertEqual(csrd_scope.LARGE_FROM_2024, (25_000_000, 50_000_000, 250))
        self.assertEqual(csrd_scope.LARGE_BEFORE_2024, (20_000_000, 40_000_000, 250))
        self.assertEqual(csrd_scope.SUBSIDIARY_OR_BRANCH_EUR, 200_000_000)

    def test_every_citation_used_is_quoted(self):
        for qid, (_, cites) in csrd_scope.QUESTIONS.items():
            for c in cites:
                self.assertIn(c, Q, f"question {qid} cites {c}")
        self.assertEqual(set(Q), {q[0] for q in cellar.QUOTES})

    def test_snapshot_shape(self):
        self.assertEqual(DATA.legal["pinned"], cellar.PINNED)
        self.assertEqual(len(DATA.ms["member_states"]), 27)
        self.assertEqual(len(DATA.forms["annex_i"]), 27)
        self.assertEqual(len(DATA.forms["annex_ii"]), 27)
        for m in DATA.nim["measures"]:
            # an allowlist: nothing that could name a natural person is kept
            self.assertLessEqual(set(m), {"directive", "country", "celex", "notified", "official_journal", "eli", "title"})
            self.assertLessEqual(len(m["title"]), 300)

    def test_no_english_corrigendum_or_later_amendment_is_pending(self):
        for x in DATA.legal["related_since_2024"]:
            if x["rel"] == "corrects":
                self.assertNotIn("ENG", x["languages"], x["celex"])
            if x["rel"] == "amends" and x["base"] in ("32013L0034", "32022L2464"):
                self.assertLessEqual(x["date"], "2026-03-18", x["celex"])


if __name__ == "__main__":
    unittest.main()
