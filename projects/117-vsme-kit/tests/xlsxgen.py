"""Synthetic VSME Digital Templates for the tests.

Nothing here is copied from EFRAG's workbook. The defined names are the datapoint
names EFRAG's template uses (MIT licence, see THIRD_PARTY_NOTICES.md); positions,
labels and every value are invented. `complete()` gives a consistent, fully filled
invented undertaking; each test changes what it needs.

    python3 tests/xlsxgen.py out.xlsx                  # the complete synthetic template
    python3 tests/xlsxgen.py out.xlsx --with-errors    # the README example: four problems added
"""
from __future__ import annotations

import sys
import zipfile
from xml.sax.saxutils import escape

GI, ENV, SOC, GOV = "General Information", "Environmental Disclosures", "Social Disclosures", "Governance Disclosures"
INTRO, TOC = "Introduction", "Table of Contents & Validation"


def col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Book:
    """A minimal xlsx writer: inline strings, numbers, booleans, formulas with or without cached results."""

    def __init__(self):
        self.sheets = {}      # name -> {(c, r): (value, formula)}
        self.names = {}       # defined name -> (sheet, c1, r1, c2, r2)
        self.order = []

    def sheet(self, name):
        if name not in self.sheets:
            self.sheets[name] = {}
            self.order.append(name)
        return self.sheets[name]

    def set(self, sheet, c, r, value, formula=None):
        self.sheet(sheet)[(c, r)] = (value, formula)

    def name(self, name, sheet, c1, r1, c2=None, r2=None):
        self.sheet(sheet)
        self.names[name] = (sheet, c1, r1, c2 or c1, r2 or r1)

    def _cell(self, c, r, value, formula):
        ref = f"{col(c)}{r}"
        f = f"<f>{escape(formula)}</f>" if formula is not None else ""
        if value is None and formula is None:
            return ""
        if value is None:  # a formula saved without a result
            return f'<c r="{ref}">{f}</c>'
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b">{f}<v>{int(value)}</v></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{ref}">{f}<v>{value!r}</v></c>'
        if formula is not None:
            return f'<c r="{ref}" t="str">{f}<v>{escape(str(value))}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'

    def _sheet_xml(self, cells):
        rows = {}
        for (c, r), (v, f) in cells.items():
            rows.setdefault(r, []).append((c, v, f))
        body = "".join(f'<row r="{r}">' + "".join(self._cell(c, r, v, f) for c, v, f in sorted(rows[r])) + "</row>"
                       for r in sorted(rows))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{body}</sheetData></worksheet>")

    def save(self, path):
        def q(s):
            return "'" + s.replace("'", "''") + "'"
        sheets = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(self.order, 1))
        names = "".join(
            f'<definedName name="{n}">{escape(q(s))}!${col(c1)}${r1}' + (f":${col(c2)}${r2}" if (c2, r2) != (c1, r1) else "")
            + "</definedName>" for n, (s, c1, r1, c2, r2) in sorted(self.names.items()))
        wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
              f"<sheets>{sheets}</sheets><definedNames>{names}</definedNames></workbook>")
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                          f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(self.order) + 1))
                + "</Relationships>")
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="xml" ContentType="application/xml"/></Types>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/_rels/workbook.xml.rels", rels)
            for i, n in enumerate(self.order, 1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", self._sheet_xml(self.sheets[n]))
        return path


# name -> (sheet, kind, value). kind: v = one cell, t = a column of 5 rows, r = a row of cells.
# Values describe an invented undertaking: 48 employees, one site, figures that add up.
SINGLE = {
    "BasisForPreparation": (GI, "Option B (Basic Module and Comprehensive Module)"),
    "BasisForReporting": (GI, "Sustainability report prepared on an individual basis"),
    "UndertakingsLegalForm": (GI, "private limited liability undertaking"),
    "Assets": (GI, 4200000), "Turnover": (GI, 6300000), "NumberOfEmployees": (GI, 48),
    "TypeOfNumberOfEmployees": (GI, "Headcount"),
    "EmployeeCountingMethodology": (GI, "At the end of the reporting period"),
    "CountryOfPrimaryOperationsAndLocationOfSignificantAssets": (GI, "Country A"),
    "DescriptionOfSustainabilityRelatedCertificationsOrLabels": (GI, "Placeholder certificate text"),
    "PracticePolicyAndOrFutureInitiativeIsPubliclyAvailable": (GI, False),
    "UndertakingHasSetATargetWhichIsRelatedToAPolicy": (GI, True),
    "DescriptionOfSignificantGroupsOfProductsAndOrServicesOffered": (GI, "Placeholder products text"),
    "DescriptionOfSignificantMarketsTheUndertakingOperatesIn": (GI, "Placeholder markets text"),
    "DescriptionOfMainBusinessRelationships": (GI, "Placeholder relationships text"),
    "DescriptionOfPracticesPoliciesAndOrFutureInitiatives": (GI, "Placeholder practices text"),
    "DescriptionOfATargetRelatedToAPolicy": (GI, "Placeholder target text"),
    "MostSeniorLevelAccountableForImplementationOfPolicies": (GI, "Placeholder role"),
    "template_reporting_period_startdate": (GI, "2025-01-01"),
    "template_reporting_period_enddate": (GI, "2025-12-31"),
    "TotalEnergyConsumption": (ENV, 1250),
    "EnergyConsumptionFromElectricity_RenewableEnergyMember": (ENV, 300),
    "EnergyConsumptionFromElectricity_NonRenewableEnergyMember": (ENV, 500),
    "EnergyConsumptionFromElectricity_TotalRenewableAndNonRenewableEnergyMember": (ENV, 800),
    "EnergyConsumptionFromSelfGeneratedElectricity_RenewableEnergyMember": (ENV, 50),
    "EnergyConsumptionFromSelfGeneratedElectricity_NonRenewableEnergyMember": (ENV, 0),
    "EnergyConsumptionFromSelfGeneratedElectricity_TotalRenewableAndNonRenewableEnergyMember": (ENV, 50),
    "EnergyConsumptionFromFuels_RenewableEnergyMember": (ENV, 0),
    "EnergyConsumptionFromFuels_NonRenewableEnergyMember": (ENV, 400),
    "EnergyConsumptionFromFuels_TotalRenewableAndNonRenewableEnergyMember": (ENV, 400),
    "GrossScope1GreenhouseGasEmissions": (ENV, 210),
    "GrossLocationBasedScope2GreenhouseGasEmissions": (ENV, 180),
    "TotalGrossLocationBasedScope1AndScope2GHGEmissions": (ENV, 390),
    "Scope1AndScope2GreenhouseGasEmissionsIntensityValueLocationBased": (ENV, 390 / 6300000),
    "GreenhouseGasEmissionReductionTargetBaseYear": (ENV, 2020),
    "GreenhouseGasEmissionReductionTargetYear": (ENV, 2030),
    "GrossScope1GreenhouseGasEmissions_BaselineYearMember": (ENV, 260),
    "GrossScope1GreenhouseGasEmissions_TargetYearMember": (ENV, 130),
    "GrossLocationBasedScope2GreenhouseGasEmissions_BaselineYearMember": (ENV, 240),
    "GrossLocationBasedScope2GreenhouseGasEmissions_TargetYearMember": (ENV, 120),
    "TotalGrossLocationBasedScope1AndScope2GHGEmissions_BaselineYearMember": (ENV, 500),
    "TotalGrossLocationBasedScope1AndScope2GHGEmissions_TargetYearMember": (ENV, 250),
    "DisclosureOfListOfMainActionsTheEntitySeeksInOrderToAchieveItsTargets": (ENV, "Placeholder actions text"),
    "PubliclyAvailableDisclosure": (ENV, False),
    "TotalSealedArea": (ENV, 1200), "TotalNatureOrientedAreaOnSite": (ENV, 300),
    "TotalNatureOrientedAreaOffSite": (ENV, 0), "TotalUseOfLand": (ENV, 5000),
    "TotalSealedArea_unit": (ENV, "squared meters (m2)"), "TotalUseOfLand_unit": (ENV, "squared meters (m2)"),
    "TotalAmountOfWaterWithdrawnFromAllSites": (ENV, 2400),
    "AmountOfWaterWithdrawnAtSitesLocatedInAreasOfHighWaterStress": (ENV, 0),
    "UndertakingAppliesCircularEconomyPrinciples": (ENV, "YES"),
    "DescriptionOfHowCircularEconomyPrinciplesAreApplied": (ENV, "Placeholder circularity text"),
    "TotalHazardousWasteGeneratedMass": (ENV, 1.0), "TotalNonHazardousWasteGeneratedMass": (ENV, 20),
    "TotalWasteGeneratedMass": (ENV, 21.0),
    "DescriptionOfClimateRelatedHazardsAndClimateRelatedTransitionEvents": (ENV, "Placeholder hazards text"),
    "DisclosureOfHowItHasAssessedTheExposureAndSensitivityOfItsAssetsActivitiesAndValueChainToTheseHazardsAndTransitionEvents": (ENV, "Placeholder assessment text"),
    "TimeHorizonsOfAnyClimateRelatedHazardsAndTransitionEventsIdentified": (ENV, "Placeholder horizons text"),
    "DisclosureOfWhetherItHasUndertakenClimateChangeAdaptationActionsForAnyClimateRelatedHazardsAndTransitionEvents": (ENV, "Placeholder adaptation text"),
    "NumberOfPermanentContractEmployees": (SOC, 44), "NumberOfTemporaryContractEmployees": (SOC, 4),
    "NumberOfMaleEmployees": (SOC, 30), "NumberOfFemaleEmployees": (SOC, 17),
    "NumberOfOtherGenderEmployees": (SOC, 0), "NumberOfNonReportedGenderEmployees": (SOC, 1),
    "EmployeeTurnoverRate": (SOC, 5 / 47),
    "NumberOfRecordableWorkRelatedAccidentsInTheReportingPeriod": (SOC, 2),
    "RateOfRecordableWorkRelatedAccidentsInTheReportingPeriod": (SOC, 2 / 81600 * 200000),
    "NumberOfFatalitiesAsAResultOfWorkRelatedInjuriesAndWorkRelatedIllHealth": (SOC, 0),
    "EmployeesReceivePayEqualOrAboveMinimumWageDeterminedByNationalLawOrCollectiveAgreement": (SOC, "YES"),
    "PercentageGapInPayBetweenFemaleAndMaleEmployees": (SOC, (24.0 - 22.5) / 24.0),
    "PercentageOfEmployeesCoveredByCollectiveBargainingAgreements": (SOC, 40 / 48),
    "AverageNumberOfAnnualTrainingHoursPerMaleEmployee": (SOC, 12),
    "AverageNumberOfAnnualTrainingHoursPerFemaleEmployee": (SOC, 14),
    "FemaleToMaleRatioAtManagementLevelForTheReportingPeriod": (SOC, 0.5),
    "TotalNumberOfSelfEmployedWorkersWithoutPersonnelThatAreWorkingExclusivelyForTheUndertaking": (SOC, 1),
    "TotalNumberOfTemporaryWorkersProvidedByUndertakingsPrimarilyEngagedInEmploymentActivities": (SOC, 3),
    "UndertakingHasACodeOfConductOrHumanRightsPolicyForItsOwnWorkforce": (SOC, "YES"),
    "UndertakingHasAComplaintHandlingMechanismForItsOwnWorkforce": (SOC, "YES"),
    "UndertakingHasConfirmedHumanRightsIncidentsInItsOwnWorkforce": (SOC, "NO"),
    "UndertakingIsAwareOfAnyConfirmedIncidentsInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers": (SOC, "NO"),
    "UndertakingsAreExcludedFromAnyEuReferenceBenchmarksThatAreAlignedWithTheParisAgreement": (GOV, "NO"),
    "GenderDiversityRatioInGovernanceBody": (GOV, 0.5),
    "RevenueDerivedFromControversialWeaponsAntiPersonnelMinesClusterMunitionsChemicalWeaponsAndBiologicalWeapons": (GOV, None),
    "RevenueDerivedFromCultivationAndProductionOfTobacco": (GOV, None), "RevenueDerivedFromChemicalProduction": (GOV, None),
    "GrossMarketBasedScope2GreenhouseGasEmissions": (ENV, None),
    "TotalGrossMarketBasedScope1AndScope2GHGEmissions": (ENV, None),
    "GrossScope3GreenhouseGasEmissions_CurrentlyStatedMember": (ENV, None),
    "TotalGrossLocationBasedGHGEmissions_CurrentlyStatedMember": (ENV, None),
    "URLOrLinkToThePubliclyAvailableDisclosure": (ENV, None),
    "AmountOfEmissionToAir_unit": (ENV, None),
    "AreaOfSiteInBiodiversitySensitiveArea_unit": (ENV, None),
    "WaterDischargeFromUndertakingProductionProcesses": (ENV, None), "TotalWaterConsumption": (ENV, None),
    "TotalVolumeOfMaterialUsed": (ENV, None),
    "DescriptionOfKeyElementsOfStrategyThatRelatesToOrAffectsSustainabilityIssues": (GI, None),
    "SpecificationOfAnyConfirmedIncidentInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers": (SOC, None),
    "DescriptionOfActionsTakeToAddressTheConfirmedIncidents": (SOC, None),
    "RevenueDerivedFromCoal": (GOV, None), "RevenueDerivedFromOil": (GOV, None), "RevenueDerivedFromGas": (GOV, None),
    "TotalRevenuesDerivedFromFossilFuelCoalOilAndGasSector": (GOV, None),
    "TotalNumberOfConvictionsForTheViolationOfAntiCorruptionAndAntiBriberyLaws": (GOV, None),
    "TotalAmountOfFinesForTheViolationOfAnticorruptionAndAntibriberyLaws": (GOV, None),
}
# Tables: columns that belong together share rows, as in EFRAG's template.
# group -> (sheet, [column names], [rows of values])
GROUPS = {
    "nace": (GI, ["NaceSectorClassificationCodes"], [("NACE C - 25.62 Placeholder activity",)]),
    "sites": (GI, ["AddressOfSite", "CountryOfSite", "GPSLocationOfSite"],
              [("1 Placeholder Street", "Country A", "50.00000, 4.00000")]),
    "subsidiaries": (GI, ["NameOfTheSubsidiary", "RegisteredAddressOfTheSubsidiary"], []),
    "waste": (ENV, ["TypeOfWasteAxis", "WasteDivertedToRecycleOrReuseMass", "WasteDirectedToDisposalMass",
                    "TotalWasteRecycledReusedAndDirectedToDisposalMass", "WasteDivertedToRecycleOrReuseMass_unit"],
              [("Placeholder non-hazardous waste", 18, 2, 20, "metric tonnes (t)"),
               ("Placeholder hazardous waste", 0.8, 0.2, 1.0, "metric tonnes (t)")]),
    "materials": (ENV, ["NameOfMaterialUsed", "WeightOfMaterialUsed", "WeightOfMaterialUsed_unit"],
                  [("Placeholder material", 140, "metric tonnes (t)")]),
    "pollutants": (ENV, ["TypeOfPollutantAxis", "AmountOfEmissionToAir", "AmountOfEmissionToWater",
                         "AmountOfEmissionToSoil"], []),
    "bsa": (ENV, ["IdentifierOfSitesInBiodiversitySensitiveAreasTypedAxis", "AreaOfSiteInBiodiversitySensitiveArea"], []),
    "countries": (SOC, ["CountryOfEmploymentContractAxis", "NumberOfEmployeesForCountryOfEmploymentContract"], []),
    "incident_types": (SOC, ["TypeOfHumanRightRelatedToTheConfirmedIncident"], []),
}
# question phrase (as label key) -> (sheet, answer)
QUESTIONS = {
    "has_the_undertaking_obtained_any_sustainability_related_certifications_or_labels": (GI, True),
    "has_the_strategy_key_elements_that_relate_to_or_affect_sustainability_issues": (GI, False),
    "has_the_undertaking_obtained_the_necessary_information_to_provide_an_energy_consumption_breakdown": (ENV, True),
    "has_the_undertaking_has_established_ghg_emission_reduction_targets": (ENV, True),
    "is_the_undertaking_disclosing_entity_specific_information_on_scope_3_emissions": (ENV, False),
    "is_the_undertaking_operating_in_high_impact_sectors": (ENV, True),
    "is_the_undertaking_already_required_by_law_or_other_national_regulations_to_report_its_pollutants": (ENV, False),
    "does_the_undertaking_have_sites_that_are_located_in_or_near_biodiversity_sensitive_areas": (ENV, False),
    "does_the_undertaking_have_production_processes_in_place_which_significantly_consume_water": (ENV, False),
    "does_the_undertaking_operate_in_a_sector_using_significant_material_flows": (ENV, True),
    "has_the_undertaking_identified_climate_related_hazards_and_transition_events": (ENV, True),
    "undertaking_operating_in_more_than_one_country": (SOC, False),
    "has_the_undertaking_incurred_in_convictions_and_fines_in_the_reporting_period": (GOV, False),
    "is_the_undertaking_deriving_revenues_from_one_of_the_activities_listed_below": (GOV, False),
    "does_the_undertaking_have_a_governance_body_in_place": (GOV, True),
}
AUX = {
    "number_of_employees_who_left_during_the_reporting_period": (SOC, 5),
    "number_of_employees_at_the_beginning_of_the_reporting_period": (SOC, 46),
    "number_of_employees_at_the_end_of_the_reporting_period": (SOC, 48),
    "total_number_of_hours_worked_in_a_year_by_all_employees": (SOC, 81600),
    "average_gross_hourly_pay_level_of_male_employees": (SOC, 24.0),
    "average_gross_hourly_pay_level_of_female_employees": (SOC, 22.5),
    "number_of_employees_covered_by_collective_bargaining_agreements": (SOC, 40),
    "number_of_male_employees_at_management_level": (SOC, 4),
    "number_of_female_employees_at_management_level": (SOC, 2),
    "number_of_female_board_members_at_the_end_of_the_reporting_period": (GOV, 1),
    "number_of_male_board_members_at_the_end_of_the_reporting_period": (GOV, 2),
}
TEXT_QUESTIONS = {"status_of_implementation_of_a_transition_plan": (ENV, "A transition plan has already been adopted")}
CHECKBOXES = ["b1_basis_for_preparation", "b1_other_undertakings_information", "b1_list_of_subsidiaries",
              "b1_list_of_sites", "b1_certifications_or_labels", "b2_practices_policies_and_future_initiatives",
              "b3_total_energy_consumption", "b3_breakdown_of_energy_consumption", "b3_estimated_ghg_emissions",
              "b4_pollution_of_air_water_and_soil", "b5_sites_in_biodiversity_sensitive_areas", "b5_biodiversity_land_use",
              "b6_water_withdrawal", "b6_water_consumption", "b7_description_of_circular_economy_principles",
              "b7_waste_generated", "b7_annual_mass_flow_of_materials", "b8_type_of_contract", "b8_gender",
              "b8_country_of_employment", "b8_turnover_rate", "b9_health_and_safety",
              "b10_remuneration_and_collective_bargaining", "b10_number_annual_training_hours_per_employee",
              "b11_convitions_and_fines_for_corruption_and_bribery"]


def complete(version="1.3.0", labels="keys", overrides=None, drop=(), rename=None, checked=(), extra_sheets=(),
             questions=None, aux=None, b2_practices=True, uncached=(), validation="COMPLETE"):
    """A Book for an invented, fully filled template, changed as asked.

    labels: "keys" labels are formulas `template_label_<key>` with English cached text (1.1.0 onwards);
            "text" labels are plain English text (1.0.x).
    overrides: {name: value, or group: [rows]}; drop: names to leave out; rename: {name: other name};
    checked: checkbox suffixes ticked as classified or sensitive; uncached: names whose cell is a formula without result.
    """
    b = Book()
    for s in (INTRO, TOC, GI, ENV, SOC, GOV):
        b.sheet(s)
    b.set(INTRO, 2, 1, "Version:", "template_label_version" if labels == "keys" else None)
    b.set(INTRO, 3, 1, version)
    if labels == "keys":
        b.name("template_reporting_template_version", INTRO, 3, 1)
    b.set(TOC, 3, 3, validation, 'IF(TRUE,"COMPLETE","INCOMPLETE")')
    b.name("template_overall_validation_status", TOC, 3, 3)
    for i, box in enumerate(CHECKBOXES, 5):
        b.set(TOC, 4, i, box in checked)
        b.name("template_checkbox_" + box, TOC, 4, i)
    values = {k: v for k, (s, v) in SINGLE.items()}
    values.update(overrides or {})
    rows = {GI: 3, ENV: 3, SOC: 3, GOV: 3}
    rename = rename or {}

    def label(sheet, row, key):
        text = key.replace("_", " ").capitalize() + "?"
        b.set(sheet, 3, row, text, ("template_label_" + key) if labels == "keys" else None)

    for name, (sheet, _) in SINGLE.items():
        r = rows[sheet]
        rows[sheet] += 1
        if name in drop:
            continue
        b.name(rename.get(name, name), sheet, 4, r)
        v = values.get(name)
        if name in uncached:
            b.set(sheet, 4, r, None, "SUM(A1:A2)")
        elif v is not None:
            b.set(sheet, 4, r, v)
    for group, (sheet, names, table) in GROUPS.items():
        r = rows[sheet]
        rows[sheet] += 6
        table = values.get(group, table)
        for i, name in enumerate(names):
            if name in drop:
                continue
            b.name(rename.get(name, name), sheet, 4 + i, r, 4 + i, r + 4)
        for j, row in enumerate(table):
            for i, v in enumerate(row):
                if v is not None:
                    b.set(sheet, 4 + i, r + j, v)
    r = rows[GI]
    rows[GI] += 2
    label(GI, r, "has_the_undertaking_put_in_place_specific_practices_policies")
    b.set(GI, 3, r + 1, b2_practices)
    grid = [True, False, True] + [False] * 7
    for i, v in enumerate(grid):
        b.set(GI, 4 + i, r + 1, v)
    b.name("SustainabilityIssueAddressedByPracticePolicyAndOrFutureInitiative", GI, 4, r + 1, 13, r + 1)
    qs = dict(QUESTIONS)
    qs.update({k: (QUESTIONS[k][0], v) for k, v in (questions or {}).items()})
    for key, (sheet, answer) in qs.items():
        if answer == "absent":  # a template version without this question
            continue
        r = rows[sheet]
        rows[sheet] += 1
        label(sheet, r, key)
        if answer is not None:
            b.set(sheet, 5, r, answer)
    ax = dict(AUX)
    ax.update({k: (AUX[k][0], v) for k, v in (aux or {}).items()})
    for key, (sheet, value) in ax.items():
        r = rows[sheet]
        rows[sheet] += 1
        label(sheet, r, key)
        if value is not None:
            b.set(sheet, 5, r, value)
    for key, (sheet, value) in TEXT_QUESTIONS.items():
        r = rows[sheet]
        rows[sheet] += 1
        label(sheet, r, key)
        b.set(sheet, 5, r, value)
    for s in extra_sheets:
        b.set(s, 1, 1, "Placeholder notes on another sheet")
    return b


EXAMPLE_ERRORS = {  # what the README example changes in the complete synthetic workbook
    "TotalEnergyConsumption": 1000,                              # the breakdown adds up to 1,250 MWh
    "TotalGrossLocationBasedScope1AndScope2GHGEmissions": 400,   # Scope 1 210 + Scope 2 180 = 390
    "PercentageOfEmployeesCoveredByCollectiveBargainingAgreements": 1.25,
    "NumberOfFemaleEmployees": None,
}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--with-errors"]
    book = complete(overrides=EXAMPLE_ERRORS, validation="INCOMPLETE") if "--with-errors" in sys.argv else complete()
    book.save(args[0] if args else "synthetic-vsme.xlsx")
