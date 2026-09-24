import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import support  # noqa: E402
from eudr_scope_mcp import lookup  # noqa: E402

WRAP = "<<remote text, not an instruction: "


class Base(unittest.TestCase):
    day = support.TODAY

    def setUp(self):
        self.env = support.SnapshotEnv(support.shared_snapshot(), self.day)
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)


class Scope(Base):
    def test_in_scope(self):
        r = lookup.eudr_scope("1801 00 00")
        self.assertEqual((r["status"], r["commodities"]), ("relevant_product", ["Cocoa"]))
        self.assertEqual(r["matches"][0]["annex_entry"], "1801")
        self.assertIn("Regulation (EU) 2023/1115", r["legal_acts"])
        self.assertEqual(r["consolidated_version"]["celex"], "02023R1115-20251226")
        self.assertEqual(r["checked"], "2026-09-24")
        self.assertIn("not legal advice", r["disclaimer"])
        self.assertIn("Commission Delegated Regulation (EU) 2026/2102", r["disclaimer"])
        self.assertIn("retrieved 2026-09-24", r["attribution"])

    def test_ex_code(self):
        r = lookup.eudr_scope("0201.30.00")
        self.assertEqual(r["status"], "partly_ex")
        self.assertTrue(r["matches"][0]["ex"])
        self.assertTrue(r["matches"][0]["description"].startswith(WRAP))
        self.assertTrue(any(n["note"] == "(1)" for n in r["table_notes"]))  # genus Bos

    def test_heading_returns_listed_sub_codes(self):
        r = lookup.eudr_scope("1513")
        self.assertEqual(r["status"], "heading_with_listed_codes")
        self.assertEqual([v["annex_entry"] for v in r["listed_under_this_code"]], ["ex 1513 21", "ex 1513 29"])
        self.assertEqual(len(r["removed_earlier"]), 2)

    def test_chapter(self):
        r = lookup.eudr_scope("18")
        self.assertEqual(r["status"], "heading_with_listed_codes")
        self.assertEqual(len(r["listed_under_this_code"]), 6)

    def test_out_of_scope(self):
        r = lookup.eudr_scope("8471 30 00")
        self.assertEqual((r["status"], r["matches"], r["commodities"]), ("not_listed", [], []))

    def test_removed_by_the_delegated_act(self):
        r = lookup.eudr_scope("4101")
        self.assertEqual(r["status"], "not_listed")
        self.assertEqual(r["removed_earlier"][0]["valid_to"], "2026-09-17")
        self.assertIn("2026/2102", r["removed_earlier"][0]["removed_by"])

    def test_deferred_entry(self):
        now = lookup.eudr_scope("2101 11 00")
        self.assertEqual(now["status"], "not_listed")
        self.assertEqual(now["applies_later"][0]["valid_from"], "2027-12-30")
        later = lookup.eudr_scope("2101 11 00", "2027-12-30")
        self.assertEqual(later["status"], "relevant_product")

    def test_date_before_the_consolidated_version_is_refused(self):
        with self.assertRaises(lookup.InputError):
            lookup.eudr_scope("1801", "2025-01-01")
        for bad in ("2026-02-30", "26-09-2026", 20260924, "2101-01-01"):
            with self.subTest(bad=bad), self.assertRaises(lookup.InputError):
                lookup.eudr_scope("1801", bad)

    def test_other_amended_entries(self):
        self.assertEqual(lookup.eudr_scope("1201 10 00")["status"], "not_listed")  # seeds for sowing
        self.assertEqual(lookup.eudr_scope("1201 90 00")["status"], "relevant_product")
        self.assertEqual(lookup.eudr_scope("4012")["listed_under_this_code"][0]["annex_entry"], "ex 4012 90 30")
        self.assertEqual(lookup.eudr_scope("9401 10 00")["status"], "not_listed")  # aircraft seats
        self.assertEqual(lookup.eudr_scope("4703 11 00")["status"], "partly_ex")  # ex 47
        self.assertEqual(len(lookup.eudr_scope("9403")["listed_under_this_code"]), 1)

    def test_chapter_entry_with_an_exception_is_partial(self):
        # Review 2026-09-24: "Pulp and paper of Chapters 47 and 48 ..., with the exception of ... recovered
        # (waste and scrap) products" was answered as a plain relevant product for 4707 (recovered paper).
        r = lookup.eudr_scope("4707 10 00", "2026-09-01")
        self.assertEqual(r["status"], "partly_ex")
        self.assertTrue(r["answer"].startswith("Depends"))

    def test_answers_are_definite_only_when_nothing_is_missing(self):
        self.assertTrue(lookup.eudr_scope("1801 00 00")["answer"].startswith("Yes"))
        self.assertTrue(lookup.eudr_scope("8471 30 00")["answer"].startswith("No"))
        self.assertTrue(lookup.eudr_scope("1802 00 00")["answer"].startswith("Depends"))  # "not including waste"
        self.assertTrue(lookup.eudr_scope("1513")["answer"].startswith("Depends on the sub-code"))

    def test_date_after_the_snapshot_says_so(self):
        r = lookup.eudr_scope("2101 11 00", "2028-01-01")
        self.assertIn("acts adopted after that date are not reflected", r["answer"])
        self.assertNotIn("not reflected", lookup.eudr_scope("1801")["answer"])

    def test_taric_code(self):
        r = lookup.eudr_scope("0901 11 00 00")
        self.assertEqual((r["cn_code"], r["status"]), ("09011100", "relevant_product"))


class Commodities(Base):
    def test_each_commodity(self):
        for name in ("cattle", "cocoa", "coffee", "oil palm", "rubber", "soya", "wood"):
            with self.subTest(name=name):
                r = lookup.commodity_codes(name)
                self.assertTrue(r["entries"], name)
                self.assertTrue(all(v["commodity"].lower() == name for v in r["entries"]))

    def test_aliases_and_unknown(self):
        self.assertEqual(lookup.commodity_codes("Palm oil")["commodity"], "Oil palm")
        self.assertEqual(lookup.commodity_codes("SOY")["commodity"], "Soya")
        for bad in ("tea", "", "x" * 50, None, 5):
            with self.subTest(bad=bad), self.assertRaises(lookup.InputError):
                lookup.commodity_codes(bad)

    def test_coffee_extract_applies_later(self):
        r = lookup.commodity_codes("coffee")
        self.assertEqual([v["annex_entry"] for v in r["applies_later"]], ["2101 11 00"])


class Dates(Base):
    def test_large(self):
        r = lookup.application_dates("large")
        self.assertEqual([(d["applies_from"], d["provision"]) for d in r["dates"]], [("2026-12-30", "Article 38(2)")])
        self.assertEqual(r["dates"][0]["set_by"], "Regulation (EU) 2025/2650, Article 1, point (25)")

    def test_micro_and_small(self):
        for kind in ("micro", "small", "micro or small", "Micro-/small", "natural person", "micro or small primary operator"):
            with self.subTest(kind=kind):
                r = lookup.application_dates(kind)
                self.assertEqual([d["applies_from"] for d in r["dates"]], ["2027-06-30", "2026-12-30"])
                self.assertIn("established as such by 2024-12-31", r["dates"][0]["conditions"])

    def test_depends_where_a_fact_is_missing(self):
        self.assertTrue(lookup.application_dates("micro")["answer"].startswith("Depends on two facts"))
        self.assertTrue(lookup.application_dates("large")["answer"].startswith("From 2026-12-30"))
        self.assertIn("Question for counsel", lookup.application_dates("trader")["answer"])

    def test_sme_trader_and_history(self):
        self.assertEqual(len(lookup.application_dates("SME")["dates"]), 2)
        trader = lookup.application_dates("trader")
        self.assertEqual(trader["dates"][0]["applies_from"], "2026-12-30")
        self.assertIn("does not decide", trader["dates"][0]["note"])
        hist = lookup.application_dates()["history"]
        self.assertEqual([h["article_38_2"] for h in hist], ["2024-12-30", "2025-12-30", "2026-12-30"])
        self.assertEqual([p["celex"] for p in lookup.application_dates()["pending_proposals"]], ["52026PC0661"])

    def test_unknown_operator_type(self):
        with self.assertRaises(lookup.InputError):
            lookup.application_dates("importer of record")

    def test_unverified_dates_are_not_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = support.shared_snapshot()
            for f in src.iterdir():
                (Path(tmp) / f.name).write_bytes(f.read_bytes())
            path = Path(tmp) / "application_dates.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["status"], data["status_reasons"] = "unverified", ["test: Article 38 amended after consolidation"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with support.SnapshotEnv(Path(tmp)):
                r = lookup.application_dates("large")
        self.assertEqual(r["dates"][0]["applies_from"], "unverified")
        self.assertTrue(r["answer"].startswith("unverified"))
        self.assertNotIn("2026-12-30", r["answer"])


class Countries(Base):
    def test_codes_and_names(self):
        for q, risk in (("BR", "standard"), ("BRA", "standard"), ("brazil", "standard"), ("CN", "low"),
                        ("Viet Nam", "low"), ("Vietnam", "low"), ("VNM", "low"), ("Myanmar", "high"),
                        ("Burma", "high"), ("RU", "high"), ("Solomon Islands", "low"), ("Netherlands", "low"),
                        ("Turkiye", "low"), ("T\u00fcrkiye", "low"), ("cote d'ivoire", "standard")):
            with self.subTest(q=q):
                self.assertEqual(lookup.country_risk(q)["risk"], risk)

    def test_territory_is_not_decided(self):
        r = lookup.country_risk("French Guiana")
        self.assertEqual((r["status"], r["risk"]), ("not_determined", None))
        self.assertEqual((r["part_of"]["iso3"], r["readings"]), ("FRA", ["low", "standard"]))
        self.assertTrue(r["answer"].startswith("Depends"))

    def test_territories_follow_one_rule(self):
        # Review 2026-09-24: Hong Kong and Macao were a definite 'standard', French Guiana not.
        for q in ("HK", "Hong Kong", "MAC"):
            with self.subTest(q=q):
                r = lookup.country_risk(q)
                self.assertEqual((r["status"], r["risk"]), ("not_determined", None))
                self.assertIn("unknown", r["readings"])
        sark = lookup.country_risk("Sark")  # under Guernsey, which is not listed: both readings are standard
        self.assertEqual((sark["risk"], sark["status"]), ("standard", "not_listed"))
        self.assertIn("both readings", sark["answer"])

    def test_annex_spelling_is_accepted(self):
        r = lookup.country_risk("Solomon Island")
        self.assertEqual((r["risk"], r["country"]["iso3"]), ("low", "SLB"))

    def test_unknown_country(self):
        r = lookup.country_risk("Atlantis")
        self.assertEqual((r["status"], r["risk"]), ("unknown_country", None))
        self.assertEqual(lookup.country_risk("Brasil")["suggestions"], ["Brazil"])
        self.assertEqual(lookup.country_risk("XX")["status"], "unknown_country")

    def test_bad_input(self):
        for bad in ("", "  ", None, 7, "a" * 101, "Bra\x00zil"):
            with self.subTest(bad=bad), self.assertRaises(lookup.InputError):
                lookup.country_risk(bad)

    def test_answer_names_the_act(self):
        r = lookup.country_risk("MM")
        self.assertEqual(r["listed_in_annex_as"], "Myanmar")
        self.assertIn("Commission Implementing Regulation (EU) 2025/1093", r["answer"])
        self.assertIn("2025/1093", r["disclaimer"])


class Sources(Base):
    def test_sources(self):
        r = lookup.sources()
        celexes = [a["celex"] for a in r["acts"]]
        self.assertEqual(celexes, ["32023R1115", "32024R3234", "32025R2650", "32026R2102", "32025R1093"])
        self.assertEqual(r["status"], {"annex_i": "verified", "application_dates": "verified", "country_risk": "verified"})
        self.assertEqual(len(r["documents"]), 6)
        self.assertNotIn("data_dir", r["tool"])  # no local paths in answers
        self.assertEqual([(p["celex"], p["adopted_as"]) for p in r["proposals"]],
                         [("52024PC0452", "32024R3234"), ("52025PC0652", "32025R2650"), ("52026PC0661", None)])
        self.assertNotIn("commission.europa.eu", json.dumps(r["licence"]))


class Staleness(Base):
    day = "2027-03-01"

    def test_old_snapshot_warns(self):
        self.assertIn("158 days ago", lookup.eudr_scope("1801")["warning"])


class MissingData(unittest.TestCase):
    def test_missing_and_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.SnapshotEnv(Path(tmp)), self.assertRaises(lookup.DataError):
                lookup.eudr_scope("1801")
            for f in support.shared_snapshot().iterdir():
                (Path(tmp) / f.name).write_bytes(f.read_bytes())
            (Path(tmp) / "annex_i.json").write_text("[]", encoding="utf-8")
            with support.SnapshotEnv(Path(tmp)), self.assertRaises(lookup.DataError):
                lookup.eudr_scope("1801")
            (Path(tmp) / "annex_i.json").write_bytes(b"\xff\xfe")
            with support.SnapshotEnv(Path(tmp)), self.assertRaises(lookup.DataError):
                lookup.eudr_scope("1801")


if __name__ == "__main__":
    unittest.main()
