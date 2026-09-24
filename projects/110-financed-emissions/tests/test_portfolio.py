"""Aggregation, data-quality weighting, rounding, currencies and row validation."""
import json
import socket
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import financed_emissions as fe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
D = Decimal
BASE = "position_id,asset_class,currency,outstanding,denominator,scope1_tco2e,scope2_tco2e,dq_score"


def run(lines, header=BASE, **kwargs):
    return fe.compute(("\n".join([header] + lines) + "\n").encode("utf-8"), **kwargs)


def reasons(result, i=0):
    return " | ".join(result["not_computed"][i]["reasons"])


class DataQualityWeighting(unittest.TestCase):
    def test_box_6_1_6_example(self):
        # PCAF Part A, 3rd ed., Box 6.1-6 (pp. 167-168): 3.03 for business loans, 3.53 for oil and gas.
        # The printed denominator repeats 108,977 for 108,997; the rounded result is the same either way.
        result = fe.compute_file(str(FIXTURES / "pcaf_box_6_1_6.csv"))
        loans = result["by_asset_class"][0]
        self.assertEqual(loans["key"], "business_loans_unlisted_equity")
        self.assertEqual(fe.fmt_t(loans["dq_weighted"]), "3.03")
        sectors = {g["name"]: g for g in result["by_sector"]}
        self.assertEqual(fe.fmt_t(sectors["Oil & Gas"]["dq_weighted"]), "3.53")
        self.assertEqual(result["totals"]["scope1_2"], D("53000"))

    def test_scope3_weighted_separately(self):
        header = BASE + ",scope3_tco2e,dq_score_scope3"
        result = run(["A,business_loan,EUR,100,1000,10,0,1,50,4",
                      "B,business_loan,EUR,300,1000,10,0,3,,"], header)
        t = result["totals"]
        self.assertEqual(t["dq_weighted"], D("2.5"))           # (100x1 + 300x3) / 400
        self.assertEqual(t["dq_weighted_scope3"], D("4"))      # only A has scope 3
        self.assertEqual(t["scope3_positions"], 1)

    def test_missing_score_is_left_out_and_reported(self):
        result = run(["A,business_loan,EUR,100,1000,10,0,2", "B,business_loan,EUR,300,1000,10,0,"])
        self.assertEqual(len(result["positions"]), 2)
        t = result["totals"]
        self.assertEqual(t["dq_weighted"], D("2"))
        self.assertEqual(t["dq_share"], D("0.25"))
        self.assertTrue(any("no data quality score" in w["message"] for w in result["warnings"]))
        text = fe.render(result)
        self.assertIn("cover 25.0% of the computed outstanding", text)

    def test_invalid_scores(self):
        result = run(["A,business_loan,EUR,1,10,1,0,0", "B,business_loan,EUR,1,10,1,0,6",
                      "C,business_loan,EUR,1,10,1,0,2.5", "D,securitization,EUR,1,10,1,0,2.5",
                      "E,business_loan,EUR,1,10,1,0,high", "F,business_loan,EUR,1,10,1,0,2.0"])
        self.assertEqual([p["position_id"] for p in result["positions"]], ["D", "F"])
        self.assertIn("from 1 (highest quality) to 5", reasons(result, 0))
        self.assertIn("whole numbers", reasons(result, 2))
        self.assertIn("is not a number", reasons(result, 3))
        # an unreadable score is an error, not a missing score
        self.assertFalse(any(w["position_id"] == "E" for w in result["warnings"]))

    def test_no_scores_at_all(self):
        result = run(["A,business_loan,EUR,100,1000,10,0,"])
        self.assertIsNone(result["totals"]["dq_weighted"])
        self.assertIn("n/a", fe.render(result))


class Aggregation(unittest.TestCase):
    def test_totals_are_sums_of_positions(self):
        result = fe.compute_file(str(ROOT / "examples" / "portfolio.csv"), reporting_currency="EUR")
        t = result["totals"]
        self.assertEqual(t["scope1_2"], fe._sum(p["financed"]["scope1_2"] for p in result["positions"]))
        self.assertEqual(sum(g["positions"] for g in result["by_asset_class"]), len(result["positions"]))
        self.assertEqual(fe.fmt_t(t["scope1_2"]), "50,811.84")
        self.assertEqual(t["scope3"], D("25775"))
        self.assertEqual(fe.fmt_t(t["dq_weighted"]), "2.20")
        self.assertEqual(fe.fmt_t(t["dq_weighted_scope3"]), "3.78")
        self.assertEqual(t["outstanding"], D("209755000"))

    def test_classes_in_standard_order_and_names(self):
        result = fe.compute_file(str(ROOT / "examples" / "portfolio.csv"), reporting_currency="EUR")
        keys = [g["key"] for g in result["by_asset_class"]]
        self.assertEqual(keys, [k for k, _, _ in fe.PCAF_CLASSES])
        self.assertEqual(result["by_asset_class"][9]["name"], "Sub-sovereign debt")

    def test_intensity_per_million(self):
        result = run(["A,listed_equity,EUR,2000000,100000000,5000,0,1"])
        # 2m/100m x 5,000 = 100 tCO2e over EUR 2m -> 50 tCO2e per EUR million
        self.assertEqual(result["totals"]["intensity_scope1_2"], D("50"))

    def test_coverage_counts_in_scope_failures_only(self):
        result = run(["A,listed_equity,EUR,300,1000,5,0,1", "B,mortgage,EUR,100,,1,1,4",
                      "C,derivative,EUR,999999,,,,"])
        t = result["totals"]
        self.assertEqual(t["coverage"], D("0.75"))
        self.assertEqual(t["not_computed_out_of_scope"], 1)

    def test_zero_outstanding_everywhere(self):
        result = run(["A,listed_equity,EUR,0,1000,5,0,1"])
        t = result["totals"]
        self.assertEqual(t["scope1_2"], 0)
        self.assertIsNone(t["dq_weighted"])
        self.assertIsNone(t["intensity_scope1_2"])
        fe.render(result)
        fe.to_json(result)


class Rounding(unittest.TestCase):
    def test_half_up_not_bankers(self):
        self.assertEqual(fe.fmt_t(D("0.125")), "0.13")
        self.assertEqual(fe.fmt_t(D("2.675")), "2.68")    # float round() gives 2.67
        self.assertEqual(fe.fmt_t(D("-0.001")), "0.00")
        self.assertEqual(fe.fmt_t(D("1234567.891")), "1,234,567.89")

    def test_total_is_summed_before_rounding(self):
        result = run([f"P{i},business_loan,EUR,1,3,1,0,1" for i in range(3)])
        shown = [fe.fmt_t(p["financed"]["scope1"]) for p in result["positions"]]
        self.assertEqual(shown, ["0.33", "0.33", "0.33"])
        self.assertEqual(fe.fmt_t(result["totals"]["scope1"]), "1.00")

    def test_ratio_significant_digits(self):
        self.assertEqual(fe.fmt_ratio(D(1) / D(579762)), "0.00000172485")
        self.assertEqual(fe.fmt_ratio(D("0.0625")), "0.0625")
        self.assertEqual(fe.fmt_ratio(D(2) / D(3)), "0.666667")

    def test_extreme_values_within_the_input_limits(self):
        # The largest outstanding over the smallest denominator the parser accepts, times the largest emissions.
        result = run(["A,listed_equity,EUR,9e23,0.000000000001,9e23,0,1"])
        self.assertTrue(result["flags"])
        text = fe.render(result, explain=True)
        self.assertIn("e+", text)
        json.dumps(fe.to_json(result), allow_nan=False)


class Currencies(unittest.TestCase):
    def test_other_currency_needs_a_rate(self):
        result = run(["A,listed_equity,EUR,100,1000,5,0,1", "B,listed_equity,USD,100,1000,5,0,1"],
                     reporting_currency="EUR")
        self.assertIn("never converts currencies", reasons(result))

    def test_user_rate_is_applied_to_the_outstanding_only(self):
        header = BASE + ",fx_rate"
        result = run(["A,listed_equity,USD,100,1000,5,0,1,0.9"], header, reporting_currency="EUR")
        p = result["positions"][0]
        self.assertEqual(p["attribution_factor"], D("0.1"))      # ratio in the row's own currency
        self.assertEqual(p["outstanding_reporting"], D("90.0"))
        self.assertIn("rate supplied by the user", "\n".join(p["arithmetic"]))

    def test_rate_on_a_reporting_currency_row(self):
        result = run(["A,listed_equity,EUR,100,1000,5,0,1,1.1"], BASE + ",fx_rate", reporting_currency="EUR")
        self.assertIn("already in the reporting currency", reasons(result))

    def test_rate_without_any_currency(self):
        header = "position_id,asset_class,outstanding,denominator,scope1_tco2e,scope2_tco2e,dq_score,fx_rate"
        result = run(["A,listed_equity,100,1000,5,0,1,1.1"], header)
        self.assertIn("no currency is stated", reasons(result))

    def test_several_currencies_without_a_reporting_currency(self):
        with self.assertRaises(fe.InputError):
            run(["A,listed_equity,EUR,100,1000,5,0,1", "B,listed_equity,USD,100,1000,5,0,1"])

    def test_single_currency_column_names_the_report(self):
        result = run(["A,listed_equity,GBP,100,1000,5,0,1"])
        self.assertEqual(result["input"]["reporting_currency"], "GBP")

    def test_bad_currency_code(self):
        result = run(["A,listed_equity,euro,100,1000,5,0,1"], reporting_currency="EUR")
        self.assertIn("ISO 4217", reasons(result))
        with self.assertRaises(fe.InputError):
            run(["A,listed_equity,EUR,100,1000,5,0,1"], reporting_currency="EURO")

    def test_sovereign_needs_usd(self):
        result = run(["S,sovereign_debt,EUR,100,1000000,5,,1"], reporting_currency="EUR")
        self.assertIn("in USD", reasons(result))
        header = "position_id,asset_class,outstanding,denominator,scope1_tco2e,scope2_tco2e,dq_score"
        result = run(["S,sovereign_debt,100,1000000,5,,1"], header)
        self.assertIn("currency unknown", reasons(result))


class RowValidation(unittest.TestCase):
    def test_negative_values(self):
        result = run(["A,listed_equity,EUR,-100,1000,5,0,1", "B,listed_equity,EUR,100,1000,-5,0,1"])
        self.assertIn("outstanding is negative", reasons(result, 0))
        self.assertIn("never as negative emissions", reasons(result, 1))

    def test_scope2_required_except_sovereign(self):
        result = run(["A,mortgage,EUR,100,1000,5,,1"])
        self.assertIn("scope2_tco2e is blank", reasons(result))
        self.assertIn("enter 0 if there is none", reasons(result))

    def test_scope1_required(self):
        result = run(["A,mortgage,EUR,100,1000,,1,1"])
        self.assertIn("scope1_tco2e is blank", reasons(result))

    def test_scope3_missing_is_a_warning_for_corporates(self):
        result = run(["A,business_loan,EUR,100,1000,5,1,1", "B,mortgage,EUR,100,1000,5,1,1"])
        messages = [(w["position_id"], w["message"]) for w in result["warnings"]]
        self.assertEqual([m[0] for m in messages if "scope 3 not supplied" in m[1]], ["A"])

    def test_duplicate_ids(self):
        result = run(["A,listed_equity,EUR,100,1000,5,0,1", "A,listed_equity,EUR,100,1000,5,0,1"])
        self.assertEqual(len(result["positions"]), 1)
        self.assertIn("already used on line 2", reasons(result))

    def test_long_ids_are_compared_in_full(self):
        a, b = "X" * 70 + "1", "X" * 70 + "2"
        result = run([f"{a},listed_equity,EUR,100,1000,5,0,1", f"{b},listed_equity,EUR,100,1000,5,0,1"])
        self.assertEqual(len(result["positions"]), 2)
        self.assertLessEqual(len(result["positions"][0]["position_id"]), 60)

    def test_markdown_escapes_file_text(self):
        header = BASE + ",counterparty"
        result = run(["A,listed_equity,EUR,100,1000,5,1,1,<img src=x onerror=alert(1)> | Co",
                      "B,mortgage,EUR,1,,1,1,1,<b>x</b>"], header)
        text = fe.render(result, markdown=True)
        self.assertNotIn("<img", text)
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;img", text)

    def test_unknown_and_out_of_scope_classes(self):
        result = run(["A,crypto,EUR,100,1000,5,0,1", "B,credit card,EUR,100,,,,", "C,,EUR,1,1,1,1,1"])
        self.assertIn("not one this calculator knows", reasons(result, 0))
        self.assertIn("consumer lending", reasons(result, 1))
        self.assertEqual(result["not_computed"][1]["reasons"], [fe.OUT_OF_SCOPE["consumer_loan"]])
        self.assertIn("asset_class is blank", reasons(result, 2))

    def test_aliases(self):
        result = run(["A,Mortgages,EUR,100,1000,5,1,1", "B,CRE,EUR,100,1000,5,1,1", "C,Listed Equity,EUR,1,10,1,0,1"])
        self.assertEqual([p["asset_class"] for p in result["positions"]],
                         ["mortgage", "commercial_real_estate", "listed_equity"])

    def test_all_reasons_are_reported_together(self):
        result = run(["A,mortgage,EUR,-1,,x,,9"])
        why = reasons(result)
        for part in ("outstanding is negative", "scope1_tco2e", "scope2_tco2e is blank", "dq_score is 9",
                     "property value at origination) is blank"):
            self.assertIn(part, why)

    def test_misplaced_optional_columns_warn(self):
        header = BASE + ",removals_tco2e,allocation_pct,undrawn_commitment,scope1_incl_lulucf_tco2e"
        result = run(["A,mortgage,EUR,100,1000,5,1,1,50,10,5,7"], header)
        text = " | ".join(w["message"] for w in result["warnings"])
        for part in ("removals_tco2e ignored", "allocation_pct applies to use_of_proceeds only",
                     "scope1_incl_lulucf_tco2e applies to sovereign"):
            self.assertIn(part, text)
        self.assertIsNotNone(result["positions"][0]["undrawn"])   # mortgages are loans: 6.2 applies

    def test_undrawn_on_equity_is_ignored(self):
        result = run(["A,listed_equity,EUR,100,1000,5,1,1,5"], BASE + ",undrawn_commitment")
        self.assertIsNone(result["positions"][0]["undrawn"])
        self.assertTrue(any("applies to loans only" in w["message"] for w in result["warnings"]))

    def test_control_characters_are_removed_from_names(self):
        header = BASE + ",counterparty"
        result = run(["A,listed_equity,EUR,100,1000,5,1,1,\"Evil\x1b[31m Corp\u202e\""], header)
        name = result["positions"][0]["counterparty"]
        self.assertNotIn("\x1b", name)
        self.assertNotIn("\u202e", name)

    def test_no_network_is_used(self):
        def refuse(*args, **kwargs):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", refuse), mock.patch.object(socket, "create_connection", refuse):
            result = fe.compute_file(str(ROOT / "examples" / "portfolio.csv"), reporting_currency="EUR")
            fe.render(result, explain=True)
            fe.to_json(result)
        self.assertEqual(len(result["positions"]), 15)


if __name__ == "__main__":
    unittest.main()
