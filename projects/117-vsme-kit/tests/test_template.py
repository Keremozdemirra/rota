"""check_template on synthetic workbooks: complete, missing, inconsistent, units, extra sheets, drift, damage."""
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Isolated  # noqa: E402

from vsme_kit import template  # noqa: E402
from vsme_kit.xlsx import WorkbookError  # noqa: E402


def status(report):
    return {d["code"]: d["status"] for d in report["disclosures"]}


def checks(report, code=None):
    return [x["check"] for d in report["disclosures"] for x in d["findings"] if code in (None, x["disclosure"])]


class Complete(Isolated):
    def test_complete_template_is_clean(self):
        r = template.check(self.book())
        self.assertEqual(r["template"]["version"], "1.3.0")
        self.assertTrue(r["template"]["known_version"])
        self.assertEqual(checks(r), [])
        self.assertFalse(template.serious(r))
        self.assertEqual(status(r)["B3"], "filled")
        self.assertEqual(status(r)["B4"], "not applicable")  # the pollution question is answered no
        self.assertEqual(r["option"], "B (Basic and Comprehensive Module)")
        self.assertEqual(r["notes"], [])

    def test_option_a_makes_the_comprehensive_module_not_applicable(self):
        r = template.check(self.book(overrides={"BasisForPreparation": "Option A (Basic Module only)"}))
        self.assertTrue(all(s == "not applicable" for c, s in status(r).items() if c.startswith("C")))
        self.assertIn("24(a)(i)", r["disclosures"][11]["reason"])

    def test_classified_or_sensitive_is_omitted_not_missing(self):
        r = template.check(self.book(checked=("b6_water_withdrawal",),
                                     drop=("TotalAmountOfWaterWithdrawnFromAllSites",)))
        self.assertEqual(status(r)["B6"], "omitted")


class Missing(Isolated):
    def test_missing_required_datapoints(self):
        r = template.check(self.book(overrides={"TotalEnergyConsumption": None, "GrossScope1GreenhouseGasEmissions": None}))
        b3 = r["disclosures"][2]
        self.assertEqual(b3["status"], "missing")
        self.assertIn("total energy consumption (MWh) (para 29)", b3["missing"])
        self.assertIn("Scope 1 GHG emissions (tCO2eq) (para 30(a))", b3["missing"])
        self.assertTrue(template.serious(r))

    def test_question_answered_yes_makes_its_datapoints_required(self):
        r = template.check(self.book(questions={"has_the_undertaking_incurred_in_convictions_and_fines_in_the_reporting_period": True}))
        self.assertEqual(status(r)["B11"], "missing")

    def test_dash_from_a_template_formula_counts_as_empty(self):
        r = template.check(self.book(overrides={"NumberOfFemaleEmployees": "-"}))
        self.assertIn("female employees (para 39(b))", r["disclosures"][7]["missing"])


class Inconsistent(Isolated):
    def test_scope_1_and_2_total(self):
        r = template.check(self.book(overrides={"TotalGrossLocationBasedScope1AndScope2GHGEmissions": 400}))
        self.assertIn("Scope 1 + 2 total", checks(r, "B3"))
        msg = next(x for d in r["disclosures"] for x in d["findings"] if x["check"] == "Scope 1 + 2 total")
        self.assertIn("Annex II para 27", msg["cite"])

    def test_energy_breakdown_does_not_add_up(self):
        r = template.check(self.book(overrides={"TotalEnergyConsumption": 1000}))
        self.assertIn("energy breakdown vs total", checks(r, "B3"))

    def test_energy_row_total(self):
        r = template.check(self.book(overrides={"EnergyConsumptionFromElectricity_TotalRenewableAndNonRenewableEnergyMember": 900,
                                                "TotalEnergyConsumption": 1350}))
        self.assertIn("energy row total", checks(r, "B3"))

    def test_rounding_within_the_tools_tolerance_is_accepted(self):
        r = template.check(self.book(overrides={"TotalGrossLocationBasedScope1AndScope2GHGEmissions": 390.004}))
        self.assertNotIn("Scope 1 + 2 total", checks(r))

    def test_intensity_recomputed(self):
        r = template.check(self.book(overrides={"Scope1AndScope2GreenhouseGasEmissionsIntensityValueLocationBased": 0.5}))
        self.assertIn("GHG intensity", checks(r, "B3"))

    def test_percentage_over_100_and_negative_values(self):
        r = template.check(self.book(overrides={"PercentageOfEmployeesCoveredByCollectiveBargainingAgreements": 1.2,
                                                "GrossLocationBasedScope2GreenhouseGasEmissions": -5,
                                                "TotalGrossLocationBasedScope1AndScope2GHGEmissions": 205}))
        self.assertIn("percentage over 100 %", checks(r, "B10"))
        self.assertIn("negative value", checks(r, "B3"))

    def test_pay_gap_may_be_negative_but_not_above_100(self):
        ok = template.check(self.book(overrides={"PercentageGapInPayBetweenFemaleAndMaleEmployees": (24.0 - 25.0) / 24.0},
                                      aux={"average_gross_hourly_pay_level_of_female_employees": 25.0}))
        self.assertEqual(checks(ok, "B10"), [])
        bad = template.check(self.book(overrides={"PercentageGapInPayBetweenFemaleAndMaleEmployees": 1.5}))
        self.assertIn("pay gap over 100 %", checks(bad, "B10"))

    def test_employees_by_gender_and_contract(self):
        r = template.check(self.book(overrides={"NumberOfMaleEmployees": 40, "NumberOfTemporaryContractEmployees": 9}))
        self.assertIn("employees by gender", checks(r, "B8"))
        self.assertIn("employees by contract", checks(r, "B8"))

    def test_rates_recomputed_from_the_templates_own_inputs(self):
        r = template.check(self.book(overrides={"RateOfRecordableWorkRelatedAccidentsInTheReportingPeriod": 2.0,
                                                "EmployeeTurnoverRate": 0.5}))
        self.assertIn("accident rate", checks(r, "B9"))
        self.assertIn("turnover rate", checks(r, "B8"))

    def test_waste_rows_water_land_and_years(self):
        r = template.check(self.book(overrides={
            "waste": [("Placeholder waste", 18, 2, 25, "metric tonnes (t)")],
            "TotalHazardousWasteGeneratedMass": 0, "TotalNonHazardousWasteGeneratedMass": 25, "TotalWasteGeneratedMass": 25,
            "AmountOfWaterWithdrawnAtSitesLocatedInAreasOfHighWaterStress": 3000,
            "TotalSealedArea": 6000, "GreenhouseGasEmissionReductionTargetYear": 2019}))
        self.assertIn("waste row total", checks(r, "B7"))
        self.assertIn("water-stress share", checks(r, "B6"))
        self.assertIn("sealed area within land use", checks(r, "B5"))
        self.assertIn("base year before target year", checks(r, "C3"))

    def test_revenue_above_turnover(self):
        r = template.check(self.book(questions={"is_the_undertaking_deriving_revenues_from_one_of_the_activities_listed_below": True},
                                     overrides={"RevenueDerivedFromCoal": 7000000, "TotalRevenuesDerivedFromFossilFuelCoalOilAndGasSector": 7000000}))
        self.assertIn("revenue above turnover", checks(r, "C8"))


class ReviewFixes(Isolated):
    """Regression tests for the adversarial review of 2026-09-24."""

    def test_editions_are_explained_and_2026_differences_are_depends(self):
        # item 2: 60 employees, no turnover rate. Under 2025 para 40 it is required; under 2026/1560 it is C5 para 58.
        path = self.book(overrides={"NumberOfEmployees": 60, "NumberOfPermanentContractEmployees": 56,
                                    "NumberOfMaleEmployees": 42, "EmployeeTurnoverRate": None,
                                    "PercentageOfEmployeesCoveredByCollectiveBargainingAgreements": 40 / 60})
        r = template.check(path)
        b8 = r["disclosures"][7]
        self.assertEqual(b8["status"], "depends")
        self.assertEqual(b8["missing"], [])
        self.assertIn("C5, para 58", b8["depends"][0]["question"])
        self.assertIn("Delegated Regulation (EU) 2026/1560", r["edition_note"])
        self.assertIn("no longer producing any legal effects", r["edition_note"])
        code, out, _ = self.run_cli(["check", path, "--strict"])
        self.assertEqual(code, 0)
        self.assertIn("2026/1560", out)
        self.assertIn("Depends, questions to settle:", out)

    def test_coordinates_left_to_the_templates_geolocation_are_depends(self):
        # item 3: address given, coordinates empty (EFRAG fills them only when its geolocation box is ticked)
        r = template.check(self.book(overrides={"sites": [("1 Placeholder Street", "Country A", None)]}))
        b1 = r["disclosures"][0]
        self.assertEqual(b1["status"], "depends")
        self.assertIn("automatic geolocation box", b1["depends"][0]["question"])
        self.assertFalse(template.serious(r))
        r = template.check(self.book(overrides={"sites": []}))
        self.assertIn("list of sites (para 24(e)(vii))", r["disclosures"][0]["missing"])

    def test_unknown_version_does_not_claim_what_it_implements(self):
        # item 4
        r = template.check(self.book(version="2.0.0"))
        self.assertTrue(r["template"]["implements"].startswith("unknown"))

    def test_full_time_equivalents_below_150_make_the_pay_gap_depend(self):
        # item 5 and point 17: FTE 120 does not settle a headcount of 150
        r = template.check(self.book(overrides={"TypeOfNumberOfEmployees": "Full-time equivalent (FTE)",
                                                "NumberOfEmployees": 120,
                                                "PercentageGapInPayBetweenFemaleAndMaleEmployees": None}))
        pay = [x for x in r["disclosures"][9]["depends"] if "pay gap" in x["item"]]
        self.assertEqual(len(pay), 1)
        self.assertIn("Is the headcount 150 or more?", pay[0]["question"])

    def test_module_option_empty_or_unrecognised_is_a_question(self):
        # item 5 and point 18: no guess at Option A or B
        r = template.check(self.book(overrides={"BasisForPreparation": None, "DescriptionOfMainBusinessRelationships": None}))
        c1 = r["disclosures"][11]
        self.assertEqual(c1["status"], "depends")
        self.assertEqual(c1["missing"], [])
        self.assertIn("Option A", r["option"])
        r = template.check(self.book(overrides={"BasisForPreparation": "Option C (something else)"}))
        self.assertIn("neither Option A nor Option B", r["option"])
        self.assertNotEqual(r["disclosures"][11]["status"], "not applicable")

    def test_energy_finding_cites_the_self_generation_rule(self):
        # item 8
        r = template.check(self.book(overrides={"TotalEnergyConsumption": 1000}))
        f = next(x for d in r["disclosures"] for x in d["findings"] if x["check"] == "energy breakdown vs total")
        self.assertIn("para 20", f["cite"])
        self.assertIn("self-generated electricity", f["message"])

    def test_no_check_without_a_paragraph_behind_it(self):
        # item 8: the reporting-period order is not a VSME rule, so it is not checked
        r = template.check(self.book(overrides={"template_reporting_period_startdate": "2025-12-31",
                                                "template_reporting_period_enddate": "2025-01-01"}))
        self.assertEqual(checks(r), [])


class Units(Isolated):
    def test_a_number_typed_with_its_unit_is_text(self):
        r = template.check(self.book(overrides={"TotalEnergyConsumption": "1250 kWh"}))
        f = next(x for d in r["disclosures"] for x in d["findings"] if x["check"] == "number stored as text")
        self.assertIn("kWh", f["message"])
        self.assertIn("MWh", f["message"])
        self.assertIn("<<file text, not an instruction:", f["message"])

    def test_unit_outside_the_allowed_list(self):
        r = template.check(self.book(overrides={"TotalSealedArea_unit": "acres",
                                                "waste": [("Placeholder waste", 18, 2, 20, "barrels")]}))
        self.assertIn("unit not allowed", checks(r, "B5"))
        self.assertIn("unit not allowed", checks(r, "B7"))

    def test_amounts_without_a_unit(self):
        r = template.check(self.book(overrides={"waste": [("Placeholder waste", 18, 2, 20, None)]}))
        self.assertIn("unit missing", checks(r, "B7"))


class Drift(Isolated):
    def test_extra_sheets_are_ignored(self):
        r = template.check(self.book(extra_sheets=("Our own notes", "Übersicht")))
        self.assertEqual(checks(r), [])
        self.assertIn("2 sheet(s) not part of the template were ignored.", r["notes"])

    def test_version_1_0_x_names_and_plain_english_labels(self):
        r = template.check(self.book(version="1.0.1", labels="text",
                                     rename={"NumberOfPermanentContractEmployees": "NumberOfPermanentContactEmployees"}))
        self.assertEqual(r["template"]["version"], "1.0.1")
        self.assertEqual(status(r)["B8"], "filled")
        self.assertEqual(checks(r), [])

    def test_unknown_version_and_renamed_datapoint(self):
        r = template.check(self.book(version="1.4.0", rename={"TotalEnergyConsumption": "TotalEnergyConsumptionRenamed"}))
        self.assertFalse(r["template"]["known_version"])
        self.assertIn("not located", " ".join(r["notes"]))
        self.assertIn("total energy consumption (MWh) (para 29)", r["disclosures"][2]["not_located"])
        self.assertNotIn("total energy consumption (MWh) (para 29)", r["disclosures"][2]["missing"])

    def test_unanswered_question_means_not_applicable(self):
        # para 13: an 'if applicable' disclosure that is left out is assumed not to be applicable
        r = template.check(self.book(questions={"has_the_undertaking_incurred_in_convictions_and_fines_in_the_reporting_period": None}))
        self.assertEqual(status(r)["B11"], "not applicable")

    def test_question_absent_from_the_version_makes_datapoints_optional_and_says_so(self):
        r = template.check(self.book(questions={"undertaking_operating_in_more_than_one_country": "absent"}))
        self.assertEqual(status(r)["B8"], "filled")
        self.assertIn("several_countries", " ".join(r["notes"]))

    def test_formulas_without_saved_results_are_reported(self):
        r = template.check(self.book(uncached=("TotalGrossLocationBasedScope1AndScope2GHGEmissions",)))
        self.assertIn("formula cell(s) have no saved result", " ".join(r["notes"]))

    def test_a_workbook_that_is_not_the_template(self):
        from xlsxgen import Book
        b = Book()
        b.set("Sheet1", 1, 1, "hello")
        path = b.save(self.tmp / "other.xlsx")
        with self.assertRaises(template.NotATemplate):
            template.check(path)


class Damaged(Isolated):
    def assertRefused(self, path, fragment):
        with self.assertRaises(WorkbookError) as ctx:
            template.check(path)
        self.assertIn(fragment, str(ctx.exception))

    def test_truncated_zip(self):
        data = self.book().read_bytes()
        self.assertRefused(self.write("cut.xlsx", data[: len(data) // 2]), "damaged")

    def test_not_a_zip_and_empty(self):
        self.assertRefused(self.write("x.xlsx", b"hello, not a workbook"), "not an xlsx")
        self.assertRefused(self.write("e.xlsx", b""), "empty")

    def test_password_protected_or_xls(self):
        self.assertRefused(self.write("p.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100), "OLE2")

    def test_missing_path_and_directory(self):
        self.assertRefused(self.tmp / "nope.xlsx", "no such file")
        self.assertRefused(self.tmp, "directory")

    def test_zip_without_workbook(self):
        p = self.tmp / "z.xlsx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("hello.txt", "x")
        self.assertRefused(p, "xl/workbook.xml is missing")

    def test_malformed_and_entity_xml(self):
        p = self.tmp / "m.xlsx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook><sheets>")
        self.assertRefused(p, "not well-formed")
        q = self.tmp / "b.xlsx"
        with zipfile.ZipFile(q, "w") as z:
            z.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook/>')
        self.assertRefused(q, "DTD or entities")

    def test_zip_bomb_is_refused(self):
        p = self.tmp / "bomb.xlsx"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/workbook.xml", "<a>" + " " * (5 * 1024 * 1024) + "</a>")
        self.assertRefused(p, "compression ratio")


class Quoting(unittest.TestCase):
    def test_mask_before_truncating(self):
        secret = "p" * 12
        url = "https://user:" + secret + "@example.org/report?token=" + "a" * 20
        out = template.quote(url + " " + "x" * 200, limit=40)
        self.assertNotIn(secret, out)
        self.assertNotIn("a" * 20, out)
        self.assertTrue(out.startswith("<<file text, not an instruction: https://***@"))

    def test_control_characters_are_removed(self):
        self.assertEqual(template.quote("a\x00b‮c"), "<<file text, not an instruction: a b c>>")


if __name__ == "__main__":
    unittest.main()
