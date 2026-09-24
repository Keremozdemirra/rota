"""Each asset-class formula against values computed by hand, and against the worked
examples printed in PCAF Part A (Third Edition, December 2025)."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import financed_emissions as fe  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
D = Decimal


def one(csv_text, **kwargs):
    """Compute a one-row portfolio and return (result, position or None)."""
    result = fe.compute(csv_text.encode("utf-8"), **kwargs)
    return result, (result["positions"][0] if result["positions"] else None)


HEADER = ("position_id,asset_class,currency,outstanding,denominator_basis,denominator,total_equity,total_debt,"
          "instrument,scope1_tco2e,scope2_tco2e,scope3_tco2e,dq_score,dq_score_scope3,undrawn_commitment,"
          "allocation_pct,removals_tco2e,scope1_incl_lulucf_tco2e,fx_rate\n")


def row(asset_class, outstanding, denominator="", basis="", te="", td="", instrument="", s1="100", s2="10",
        s3="", dq="2", dq3="", undrawn="", alloc="", removals="", lulucf="", currency="EUR", fx=""):
    return HEADER + ",".join(str(x) for x in (
        "X1", asset_class, currency, outstanding, basis, denominator, te, td, instrument, s1, s2, s3, dq, dq3,
        undrawn, alloc, removals, lulucf, fx)) + "\n"


class HandComputed(unittest.TestCase):
    def test_listed_equity_evic(self):
        # 10m / 500m = 0.02; 0.02 x 200,000 = 4,000
        _, p = one(row("listed_equity", "10000000", "500000000", s1="200000", s2="10000", s3="50000", dq3="3"))
        self.assertEqual(p["attribution_factor"], D("0.02"))
        self.assertEqual(p["financed"]["scope1"], D("4000"))
        self.assertEqual(p["financed"]["scope2"], D("200"))
        self.assertEqual(p["financed"]["scope1_2"], D("4200"))
        self.assertEqual(p["financed"]["scope3"], D("1000"))
        self.assertIn("5.1, p. 42", p["citations"])

    def test_corporate_bond_private_issuer_equity_plus_debt(self):
        # 5m / (40m + 60m) = 0.05
        _, p = one(row("corporate_bond", "5000000", basis="total_equity_plus_debt", te="40000000", td="60000000",
                       s1="80000", s2="2000"))
        self.assertEqual(p["denominator_basis"], "total_equity_plus_debt")
        self.assertEqual(p["attribution_factor"], D("0.05"))
        self.assertEqual(p["financed"]["scope1_2"], D("4100"))

    def test_business_loan_default_basis_is_equity_plus_debt(self):
        _, p = one(row("business_loan", "2500000", "10000000", s1="1000", s2="200"))
        self.assertEqual(p["denominator_basis"], "total_equity_plus_debt")
        self.assertEqual(p["attribution_factor"], D("0.25"))
        self.assertEqual(p["financed"]["scope1_2"], D("300"))

    def test_business_loan_to_listed_company_uses_evic(self):
        _, p = one(row("business_loan", "3000000", "600000000", basis="evic", s1="12000", s2="0"))
        self.assertEqual(p["attribution_factor"], D("0.005"))
        self.assertEqual(p["financed"]["scope1"], D("60"))

    def test_total_assets_fallback(self):
        _, p = one(row("business_loan", "1000000", "8000000", basis="total_assets", s1="400", s2="0"))
        self.assertEqual(p["financed"]["scope1"], D("50"))
        self.assertEqual(p["denominator_basis"], "total_assets")

    def test_unlisted_equity(self):
        _, p = one(row("unlisted_equity", "3000000", "60000000", s1="900", s2="1400"))
        self.assertEqual(p["attribution_factor"], D("0.05"))
        self.assertEqual(p["financed"]["scope1_2"], D("115"))

    def test_project_finance_and_value_at_origination(self):
        _, p = one(row("project_finance", "45000000", "300000000", s1="1200", s2="300"))
        self.assertEqual(p["financed"]["scope1_2"], D("225"))
        _, q = one(row("project_finance", "200000", "800000", basis="project_value_at_origination", s1="40", s2="8"))
        self.assertEqual(q["attribution_factor"], D("0.25"))
        self.assertEqual(q["financed"]["scope1_2"], D("12"))
        self.assertIn("5.3, p. 69", q["citations"])

    def test_commercial_real_estate(self):
        # 18m / 30m = 0.6; building 410 + 620 tCO2e
        _, p = one(row("commercial_real_estate", "18000000", "30000000", s1="410", s2="620"))
        self.assertEqual(p["financed"]["scope1"], D("246"))
        self.assertEqual(p["financed"]["scope2"], D("372"))

    def test_mortgage_latest_property_value(self):
        _, p = one(row("mortgage", "150000", "300000", basis="latest_property_value", s1="4.2", s2="0"))
        self.assertEqual(p["financed"]["scope1"], D("2.1"))
        self.assertEqual(p["denominator_basis"], "latest_property_value")

    def test_motor_vehicle_loan(self):
        _, p = one(row("motor_vehicle_loan", "12000", "30000", s1="2.5", s2="0"))
        self.assertEqual(p["attribution_factor"], D("0.4"))
        self.assertEqual(p["financed"]["scope1"], D("1.0"))

    def test_motor_vehicle_unknown_value_is_100_percent(self):
        # 5.6, p. 91: value at origination unknown -> assume 100% attribution
        _, p = one(row("motor_vehicle_loan", "12000", "", s1="2.5", s2="0.5"))
        self.assertEqual(p["attribution_factor"], 1)
        self.assertEqual(p["financed"]["scope1_2"], D("3.0"))
        self.assertTrue(any("5.6, p. 91" in n for n in p["notes"]))
        self.assertEqual(p["flags"], [])

    def test_motor_vehicle_repaid_is_zero(self):
        _, p = one(row("motor_vehicle_loan", "0", "", s1="2.5", s2="0.5"))
        self.assertEqual(p["attribution_factor"], 0)
        self.assertEqual(p["financed"]["scope1_2"], 0)

    def test_use_of_proceeds_allocation_example_from_the_standard(self):
        # 5.7, p. 103: 50 MEUR in a 100 MEUR debt fund, 10% allocated -> 5 MEUR outstanding reported
        _, p = one(row("use_of_proceeds", "50000000", "100000000", s1="1000", s2="0", alloc="10", dq="2.6"))
        self.assertEqual(p["attribution_factor"], D("0.5"))
        self.assertEqual(p["financed"]["scope1"], D("500"))
        self.assertEqual(p["outstanding_reporting"], D("5000000"))
        self.assertEqual(p["dq_score"], D("2.6"))

    def test_use_of_proceeds_allocation_defaults_to_100(self):
        _, p = one(row("use_of_proceeds", "50000000", "100000000", s1="1000", s2="0"))
        self.assertEqual(p["outstanding_reporting"], D("50000000"))

    def test_securitization_investment_over_deal(self):
        # IAF x TAF = investment COA / deal COA = 10m / 500m; pool financed emissions 2,000
        _, p = one(row("securitization", "10000000", "500000000", s1="1500", s2="500", dq="3.4"))
        self.assertEqual(p["attribution_factor"], D("0.02"))
        self.assertEqual(p["financed"]["scope1_2"], D("40"))
        self.assertEqual(p["denominator_basis"], "deal_outstanding")

    def test_sovereign_debt(self):
        _, p = one(row("sovereign_debt", "30000000", "950000000000", s1="410000000", s2="", lulucf="385000000",
                       currency="USD"), reporting_currency="USD")
        self.assertEqual(fe.fmt_t(p["financed"]["scope1"]), "12,947.37")
        self.assertEqual(fe.fmt_t(p["financed"]["scope1_incl_lulucf"]), "12,157.89")
        self.assertIsNone(p["financed"]["scope2"])

    def test_sovereign_lulucf_may_be_negative(self):
        # A net sink including LULUCF is possible; only that column accepts a negative figure.
        _, p = one(row("sovereign_debt", "1000000", "100000000000", s1="5000000", s2="", lulucf="-2000000",
                       currency="USD"))
        self.assertEqual(p["financed"]["scope1_incl_lulucf"], D("-20"))

    def test_sub_sovereign_debt(self):
        _, p = one(row("sub_sovereign_debt", "10000000", "85000000000", s1="21000000", s2="", currency="USD"))
        self.assertEqual(fe.fmt_t(p["financed"]["scope1"]), "2,470.59")

    def test_removals_attributed_separately(self):
        _, p = one(row("project_finance", "6000000", "20000000", s1="150", s2="10", removals="42000"))
        self.assertEqual(p["financed"]["removals"], D("12600"))
        self.assertEqual(p["financed"]["scope1_2"], D("48"))

    def test_undrawn_commitment_separate(self):
        # 6.2: undrawn / same denominator; never part of financed emissions
        result, p = one(row("business_loan", "45000000", "300000000", s1="1200", s2="300", undrawn="5000000"))
        self.assertEqual(fe.fmt_t(p["undrawn"]["scope1_2"]), "25.00")
        self.assertEqual(result["totals"]["scope1_2"], D("225"))
        self.assertEqual(result["totals"]["undrawn_scope1_2"], p["undrawn"]["scope1_2"])


class WorkedExamplesFromTheStandard(unittest.TestCase):
    def test_table_5_2_2_portfolio(self):
        # PCAF Part A, 3rd ed., Tables 5.2-2 and 5.2-3 (p. 63): 6,100 / 1,260 / 10,000 / removals 2,200
        result = fe.compute_file(str(FIXTURES / "pcaf_table_5_2_2.csv"))
        t = result["totals"]
        self.assertEqual(t["scope1"], D("6100"))
        self.assertEqual(t["scope2"], D("1260"))
        self.assertEqual(t["scope3"], D("10000"))
        self.assertEqual(t["removals"], D("2200"))

    def test_table_10_3_2_sovereign_ppp_gdp(self):
        # Annex 10.3, Table 10.3-2 (p. 202): USD 1m exposure -> 106 (Singapore) and 91 (Hong Kong) tCO2e
        result = fe.compute_file(str(FIXTURES / "pcaf_table_10_3_2.csv"))
        by_id = {p["position_id"]: p for p in result["positions"]}
        self.assertEqual(fe.fmt_t(by_id["SG"]["financed"]["scope1"], 0), "106")
        self.assertEqual(fe.fmt_t(by_id["HK"]["financed"]["scope1"], 0), "91")


class AttributionFactorAboveOne(unittest.TestCase):
    def test_sub_sovereign_is_capped_at_one(self):
        # 5.10, p. 154: the ratio shall be capped at 1
        _, p = one(row("sub_sovereign_debt", "2000", "1000", s1="500", s2="", currency="USD"))
        self.assertEqual(p["attribution_factor"], 1)
        self.assertEqual(p["attribution_factor_uncapped"], 2)
        self.assertTrue(p["capped"])
        self.assertEqual(p["financed"]["scope1"], D("500"))
        self.assertTrue(p["flags"] and "capped at 1" in p["flags"][0])

    def test_mortgage_above_one_is_flagged_not_capped(self):
        # The standard gives no cap for mortgages: the factor is used as computed and flagged.
        result, p = one(row("mortgage", "315000", "300000", s1="3.4", s2="0.9"))
        self.assertEqual(p["attribution_factor"], D("1.05"))
        self.assertFalse(p["capped"])
        self.assertEqual(p["financed"]["scope1"], D("3.57"))
        self.assertEqual(len(result["flags"]), 1)
        self.assertIn("no cap", result["flags"][0]["message"])

    def test_listed_equity_above_one_is_flagged(self):
        _, p = one(row("listed_equity", "600", "500", s1="100", s2="0"))
        self.assertEqual(p["attribution_factor"], D("1.2"))
        self.assertTrue(p["flags"])

    def test_exactly_one_is_not_flagged(self):
        _, p = one(row("mortgage", "300000", "300000", s1="3", s2="1"))
        self.assertEqual(p["flags"], [])

    def test_undrawn_above_one_is_flagged(self):
        result, _ = one(row("business_loan", "10", "100", s1="1", s2="0", undrawn="500"))
        self.assertTrue(any(f["message"].startswith("undrawn:") for f in result["flags"]))


class DenominatorEdgeCases(unittest.TestCase):
    def failure(self, text, **kw):
        result = fe.compute(text.encode("utf-8"), **kw)
        self.assertEqual(result["positions"], [], result["positions"])
        return " | ".join(result["not_computed"][0]["reasons"])

    def test_zero_evic(self):
        why = self.failure(row("listed_equity", "100", "0"))
        self.assertIn("must be greater than 0", why)
        self.assertIn("cannot be negative", why)

    def test_negative_evic(self):
        why = self.failure(row("listed_equity", "100", "-5000"))
        self.assertIn("must be greater than 0", why)

    def test_missing_denominator(self):
        why = self.failure(row("commercial_real_estate", "100", ""))
        self.assertIn("property value at origination", why)
        self.assertIn("blank", why)

    def test_negative_single_denominator_points_to_the_split(self):
        why = self.failure(row("business_loan", "100", "-50"))
        self.assertIn("total_equity and total_debt", why)

    def test_negative_equity_set_to_zero_for_a_loan(self):
        # 5.2, p. 57, footnote 75: negative total equity counts as 0
        _, p = one(row("business_loan", "5000000", te="-2000000", td="25000000", s1="18000", s2="2500"))
        self.assertEqual(p["denominator"], D("25000000"))
        self.assertEqual(p["attribution_factor"], D("0.2"))
        self.assertTrue(any("footnote 75" in n for n in p["notes"]))

    def test_negative_equity_means_no_emissions_for_an_equity_stake(self):
        _, p = one(row("unlisted_equity", "1000000", te="-500000", td="4000000", s1="900", s2="100"))
        self.assertEqual(p["attribution_factor"], 0)
        self.assertEqual(p["financed"]["scope1_2"], 0)

    def test_project_finance_equity_instrument_with_negative_equity(self):
        _, p = one(row("project_finance", "1000000", te="-10", td="4000000", instrument="equity", s1="10", s2="1"))
        self.assertEqual(p["financed"]["scope1_2"], 0)
        _, q = one(row("project_finance", "1000000", te="-10", td="4000000", instrument="debt", s1="10", s2="1"))
        self.assertEqual(q["attribution_factor"], D("0.25"))

    def test_denominator_that_disagrees_with_the_split(self):
        why = self.failure(row("business_loan", "100", "999", te="400", td="500"))
        self.assertIn("does not equal total_equity + total_debt", why)

    def test_split_needs_both_parts(self):
        why = self.failure(row("business_loan", "100", te="400"))
        self.assertIn("give both total_equity and total_debt", why)

    def test_basis_not_allowed_for_the_class(self):
        why = self.failure(row("listed_equity", "100", "1000", basis="total_equity_plus_debt"))
        self.assertIn("is not used for listed_equity", why)

    def test_equity_instrument_conflict(self):
        why = self.failure(row("business_loan", "100", "1000", instrument="equity"))
        self.assertIn("conflicts", why)


class AttributeFunction(unittest.TestCase):
    def test_numbers_as_strings_and_floats(self):
        out = fe.attribute("mortgage", "240000", 3.4, denominator=400000.0)
        self.assertAlmostEqual(out["attribution_factor"], 0.6)
        self.assertAlmostEqual(out["financed_emissions_tco2e"], 2.04)
        self.assertTrue(out["arithmetic"][-1].startswith("financed emissions = 240,000 / 400,000.0 x 3.4 = 2.04"))

    def test_rejects_non_finite_and_bool(self):
        with self.assertRaises(ValueError):
            fe.attribute("mortgage", float("nan"), 1, denominator=10)
        with self.assertRaises(ValueError):
            fe.attribute("mortgage", True, 1, denominator=10)

    def test_sovereign_currency_checked(self):
        with self.assertRaises(ValueError):
            fe.attribute("sovereign_debt", 1, 1, denominator=100, currency="EUR")
        out = fe.attribute("sovereign_debt", 1000000, 61451586, denominator="579762000000")
        self.assertTrue(any("USD" in n for n in out["notes"]))

    def test_out_of_scope_and_unknown(self):
        with self.assertRaises(ValueError) as ctx:
            fe.attribute("swap", 1, 1, denominator=2)
        self.assertIn("derivatives", str(ctx.exception))
        with self.assertRaises(ValueError):
            fe.attribute("crypto", 1, 1, denominator=2)


if __name__ == "__main__":
    unittest.main()
