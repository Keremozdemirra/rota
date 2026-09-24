"""Check a filled copy of EFRAG's VSME Digital Template (xlsx) against the VSME text.

Where things are found. EFRAG's template gives every datapoint an Excel defined
name equal to its element name in the VSME XBRL taxonomy (for example
`GrossScope1GreenhouseGasEmissions`); EFRAG's own converter reads the file the same
way. Questions that switch a disclosure on or off ("Has the undertaking obtained
the necessary information...?") carry no name, so they are found by their label:
the language-independent key in the label cell's formula
(`=template_label_has_the_undertaking_...`) or, in versions before 1.1.0, the
English label text. No sheet, row or column position is assumed, which is what
keeps the check working across template versions 1.0.0 to 1.3.0, whose layouts differ.

What is checked. Each disclosure B1 to C9 is reported as filled, missing, not
applicable (as the template's own questions allow), omitted (classified or
sensitive, ticked in the template) or inconsistent. Every consistency check cites
the paragraph of Annex I (the standard) or Annex II (the guidance) of Commission
Recommendation (EU) 2025/1710 that justifies it; the template up to version 1.3.0
implements that Recommendation. Tolerances are this tool's own choice (see TOLERANCE).
Every paragraph reference and threshold below (50 employees, para 40; a headcount of
150, para 42(b); 200 000 hours, Annex II paras 120-121) was checked against the Official
Journal text (OJ L, 2025/1710, 5.8.2025) on 2026-09-24.
"""
from __future__ import annotations

import re

from .xlsx import UNCACHED, CellError, Workbook, WorkbookError

KNOWN_VERSIONS = ("1.0.0", "1.0.1", "1.1.0", "1.1.1", "1.2.0", "1.3.0")
IMPLEMENTS = ("Commission Recommendation (EU) 2025/1710 of 30 July 2025, Annex I (standard) and Annex II "
              "(guidance), OJ L, 2025/1710, 5.8.2025")
SHEETS = ("General Information", "Environmental Disclosures", "Social Disclosures", "Governance Disclosures")

# The tool's own choice, not a VSME rule: two figures that should be equal may differ by
# rounding up to 0.5 % of the larger one, or by 0.01 in absolute terms.
TOLERANCE_REL = 0.005
TOLERANCE_ABS = 0.01

# Names that EFRAG corrected after template 1.0.1.
ALIASES = {
    "NumberOfPermanentContractEmployees": ("NumberOfPermanentContactEmployees",),
    "MostSeniorLevelAccountableForImplementationOfPolicies":
        ("MostSeniorLevelAccountableForImplementationOfPracticesPoliciesAndOrFutureInitiatives",),
    "WasteGeneratedTable": ("WasteTable",),
}

AREA_UNITS = ("hectares (ha)", "squared meters (m2)")
MASS_UNITS = ("kilograms (kg)", "metric tonnes (t)")
WASTE_UNITS = MASS_UNITS + ("cubic meters (m3)",)
UNIT_WORDS = re.compile(r"\b(kwh|mwh|gwh|twh|gj|tj|kg|t|tonnes?|tons?|m3|m²|m2|ha|l|litres?|liters?|"
                        r"tco2e?q?|kgco2e?|eur|usd|%)\b", re.I)

ALWAYS, MAY = "always", "may"


def when(condition):
    return ("if", condition)


class Item:
    """One datapoint (or a table of them) of a disclosure.

    differs_2026: how Delegated Regulation (EU) 2026/1560 treats the datapoint when it does not require
    it as the 2025 Recommendation does; a gap is then reported as "depends", not "missing".
    depends_if: (test, question) for a gap that a fact outside the datapoint may explain.
    """

    def __init__(self, names, label, para, need=ALWAYS, box=None, kind="value", nonneg=False, unit=None,
                 differs_2026=None, depends_if=None):
        self.names = (names,) if isinstance(names, str) else tuple(names)
        self.label, self.para, self.need, self.box = label, para, need, box
        self.kind, self.nonneg, self.unit = kind, nonneg, unit
        self.differs_2026, self.depends_if = differs_2026, depends_if


class Depends:
    """A condition this tool cannot settle from the workbook, with the question that would settle it."""

    def __init__(self, question: str):
        self.question = question


def _addresses_given(t) -> bool:
    return any(not empty(v) for _, v in t.column("AddressOfSite"))


GEOLOCATION_QUESTION = (
    "Para 24(e)(vii) asks for the geolocation of sites. The site addresses are given but no coordinates: the "
    "template fills them from the address only when its automatic geolocation box is ticked, by asking "
    "OpenStreetMap from Excel. Are the coordinates provided another way, or should that box be ticked?")


# Questions in the template that make a disclosure applicable, found by their label.
# The phrase is matched against the label key (underscores read as spaces) and the English text.
QUESTIONS = {
    "certifications": ("General Information", "has the undertaking obtained any sustainability related cert"),
    "strategy_elements": ("General Information", "has the strategy key elements that relate to or affect"),
    "energy_breakdown": ("Environmental Disclosures", "obtained the necessary information to provide an energy consumption breakdown"),
    "ghg_targets": ("Environmental Disclosures", "established ghg emission reduction targets"),
    "scope3": ("Environmental Disclosures", "disclosing entity specific information on scope 3"),
    "high_impact": ("Environmental Disclosures", "is the undertaking operating in high impact sectors"),
    "pollution": ("Environmental Disclosures", "already required by law or other national regulations to report"),
    "bsa_sites": ("Environmental Disclosures", "have sites that are located in or near"),
    "water_processes": ("Environmental Disclosures", "production processes in place which significantly consume water"),
    "material_flows": ("Environmental Disclosures", "operate in a sector using significant material"),
    "climate_hazards": ("Environmental Disclosures", "identified climate related hazards"),
    "several_countries": ("Social Disclosures", "operating in more than one country"),
    "convictions": ("Governance Disclosures", "incurred in convictions and fines"),
    "c8_revenues": ("Governance Disclosures", "deriving revenues from one of the activit"),
    "governance_body": ("Governance Disclosures", "have a governance body in place"),
}
# Auxiliary inputs of the template's own calculations, found by their label (numbers).
AUX = {
    "left": ("Social Disclosures", "number of employees who left during the reporting period"),
    "begin": ("Social Disclosures", "number of employees at the beginning of the reporting period"),
    "end": ("Social Disclosures", "number of employees at the end of the reporting period"),
    "hours": ("Social Disclosures", "total number of hours worked in a year by all employees"),
    "pay_male": ("Social Disclosures", "average gross hourly pay level of male employees"),
    "pay_female": ("Social Disclosures", "average gross hourly pay level of female employees"),
    "cba_count": ("Social Disclosures", "number of employees covered by collective bargaining"),
    "mgmt_male": ("Social Disclosures", "number of male employees at management level"),
    "mgmt_female": ("Social Disclosures", "number of female employees at management level"),
    "board_female": ("Governance Disclosures", "number of female board members"),
    "board_male": ("Governance Disclosures", "number of male board members"),
}
TEXT_QUESTIONS = {
    "transition_plan_status": ("Environmental Disclosures", "status of implementation of a trans"),
}

ENERGY_ROWS = ("Electricity", "SelfGeneratedElectricity", "Fuels")
ENERGY = [f"EnergyConsumptionFrom{r}_{m}" for r in ENERGY_ROWS
          for m in ("RenewableEnergyMember", "NonRenewableEnergyMember", "TotalRenewableAndNonRenewableEnergyMember")]
COLUMNS = ("", "_BaselineYearMember", "_TargetYearMember")
CB = "template_checkbox_"

DISCLOSURES = [
    ("B1", "Basis for preparation", "24-25", [
        Item("BasisForPreparation", "module option (A or B)", "24(a)", box=CB + "b1_basis_for_preparation"),
        Item("BasisForReporting", "individual or consolidated basis", "24(c)", box=CB + "b1_other_undertakings_information"),
        Item(("NameOfTheSubsidiary", "RegisteredAddressOfTheSubsidiary"), "list of subsidiaries with registered address",
             "24(d)", need=when("consolidated"), box=CB + "b1_list_of_subsidiaries", kind="table"),
        Item("UndertakingsLegalForm", "legal form", "24(e)(i)", box=CB + "b1_other_undertakings_information"),
        Item("NaceSectorClassificationCodes", "NACE code(s)", "24(e)(ii)", box=CB + "b1_other_undertakings_information", kind="table"),
        Item("Assets", "balance sheet total", "24(e)(iii)", box=CB + "b1_other_undertakings_information", nonneg=True),
        Item("Turnover", "turnover", "24(e)(iv)", box=CB + "b1_other_undertakings_information", nonneg=True),
        Item("NumberOfEmployees", "number of employees", "24(e)(v)", box=CB + "b1_other_undertakings_information", nonneg=True),
        Item("TypeOfNumberOfEmployees", "headcount or full-time equivalents", "24(e)(v)", box=CB + "b1_other_undertakings_information"),
        Item("CountryOfPrimaryOperationsAndLocationOfSignificantAssets", "country of primary operations", "24(e)(vi)",
             box=CB + "b1_other_undertakings_information"),
        Item(("AddressOfSite", "CountryOfSite"), "list of sites", "24(e)(vii)", box=CB + "b1_list_of_sites", kind="table"),
        Item("GPSLocationOfSite", "geolocation (coordinates) of sites", "24(e)(vii)", box=CB + "b1_list_of_sites", kind="table",
             depends_if=(_addresses_given, GEOLOCATION_QUESTION)),
        Item("DescriptionOfSustainabilityRelatedCertificationsOrLabels", "description of certifications or labels", "25",
             need=when("certifications"), box=CB + "b1_certifications_or_labels"),
    ]),
    ("B2", "Practices, policies and future initiatives for transitioning towards a more sustainable economy", "26-28", [
        Item("SustainabilityIssueAddressedByPracticePolicyAndOrFutureInitiative", "sustainability issues addressed",
             "26", need=when("practices"), box=CB + "b2_practices_policies_and_future_initiatives", kind="any_true"),
    ]),
    ("B3", "Energy and greenhouse gas emissions", "29-31", [
        Item("TotalEnergyConsumption", "total energy consumption (MWh)", "29", box=CB + "b3_total_energy_consumption",
             nonneg=True, unit="MWh"),
        Item(ENERGY, "energy consumption breakdown (MWh)", "29", need=when("energy_breakdown"),
             box=CB + "b3_breakdown_of_energy_consumption", kind="table", nonneg=True, unit="MWh"),
        Item("GrossScope1GreenhouseGasEmissions", "Scope 1 GHG emissions (tCO2eq)", "30(a)", box=CB + "b3_estimated_ghg_emissions",
             nonneg=True, unit="tCO2eq"),
        Item("GrossLocationBasedScope2GreenhouseGasEmissions", "location-based Scope 2 GHG emissions (tCO2eq)", "30(b)",
             box=CB + "b3_estimated_ghg_emissions", nonneg=True, unit="tCO2eq"),
        Item("GrossMarketBasedScope2GreenhouseGasEmissions", "market-based Scope 2 GHG emissions (tCO2eq)", "30",
             need=MAY, box=CB + "b3_estimated_ghg_emissions", nonneg=True, unit="tCO2eq"),
        Item("GrossScope3GreenhouseGasEmissions_CurrentlyStatedMember", "Scope 3 GHG emissions (tCO2eq)", "52-53",
             need=when("scope3"), box=CB + "b3_estimated_ghg_emissions", nonneg=True, unit="tCO2eq"),
    ]),
    ("B4", "Pollution of air, water and soil", "32", [
        Item("PubliclyAvailableDisclosure", "whether the information is already publicly available", "32",
             need=when("pollution"), box=CB + "b4_pollution_of_air_water_and_soil", kind="answer"),
        Item("URLOrLinkToThePubliclyAvailableDisclosure", "link to the published information", "32",
             need=when("pollution_public"), box=CB + "b4_pollution_of_air_water_and_soil"),
        Item(("TypeOfPollutantAxis", "AmountOfEmissionToAir", "AmountOfEmissionToWater", "AmountOfEmissionToSoil"),
             "pollutants with amounts", "32", need=when("pollution_table"), box=CB + "b4_pollution_of_air_water_and_soil",
             kind="table"),
    ]),
    ("B5", "Biodiversity", "33-34", [
        Item(("IdentifierOfSitesInBiodiversitySensitiveAreasTypedAxis", "AreaOfSiteInBiodiversitySensitiveArea"),
             "sites in or near biodiversity sensitive areas, with area", "33", need=when("bsa_sites"),
             box=CB + "b5_sites_in_biodiversity_sensitive_areas", kind="table",
             differs_2026="Under Delegated Regulation (EU) 2026/1560, para 35 asks for the sites and the name of the "
                          "biodiversity-sensitive area, not their area."),
        Item(("TotalSealedArea", "TotalNatureOrientedAreaOnSite", "TotalNatureOrientedAreaOffSite", "TotalUseOfLand"),
             "land-use metrics", "34", need=MAY, box=CB + "b5_biodiversity_land_use", kind="table", nonneg=True),
    ]),
    ("B6", "Water", "35-36", [
        Item("TotalAmountOfWaterWithdrawnFromAllSites", "total water withdrawal", "35", box=CB + "b6_water_withdrawal", nonneg=True),
        Item("AmountOfWaterWithdrawnAtSitesLocatedInAreasOfHighWaterStress", "water withdrawal at sites in areas of high water-stress",
             "35", need=MAY, box=CB + "b6_water_withdrawal", nonneg=True),
        Item("WaterDischargeFromUndertakingProductionProcesses", "water discharge from production processes", "36",
             need=when("water_processes"), box=CB + "b6_water_consumption", nonneg=True),
        Item("TotalWaterConsumption", "water consumption", "36", need=when("water_processes"), box=CB + "b6_water_consumption"),
    ]),
    ("B7", "Resource use, circular economy and waste management", "37-38", [
        Item("UndertakingAppliesCircularEconomyPrinciples", "whether circular economy principles are applied", "37",
             box=CB + "b7_description_of_circular_economy_principles"),
        Item("DescriptionOfHowCircularEconomyPrinciplesAreApplied", "how circular economy principles are applied", "37",
             need=when("circular_yes"), box=CB + "b7_description_of_circular_economy_principles"),
        Item(("TypeOfWasteAxis", "WasteDivertedToRecycleOrReuseMass", "WasteDirectedToDisposalMass"),
             "waste generated by type, diverted to recycling or reuse", "38(a)-(b)", box=CB + "b7_waste_generated", kind="table"),
        Item(("NameOfMaterialUsed", "WeightOfMaterialUsed"), "annual mass-flow of relevant materials", "38(c)",
             need=when("material_flows"), box=CB + "b7_annual_mass_flow_of_materials", kind="table"),
    ]),
    ("B8", "Workforce – General characteristics", "39-40", [
        Item("NumberOfPermanentContractEmployees", "employees with a permanent contract", "39(a)",
             box=CB + "b8_type_of_contract", nonneg=True),
        Item("NumberOfTemporaryContractEmployees", "employees with a temporary contract", "39(a)",
             box=CB + "b8_type_of_contract", nonneg=True),
        Item("NumberOfMaleEmployees", "male employees", "39(b)", box=CB + "b8_gender", nonneg=True),
        Item("NumberOfFemaleEmployees", "female employees", "39(b)", box=CB + "b8_gender", nonneg=True),
        Item("NumberOfEmployeesForCountryOfEmploymentContract", "employees by country of the employment contract", "39(c)",
             need=when("several_countries"), box=CB + "b8_country_of_employment", kind="table", nonneg=True),
        Item("EmployeeTurnoverRate", "employee turnover rate", "40", need=when("fifty_or_more"),
             box=CB + "b8_turnover_rate", nonneg=True,
             differs_2026="Under Delegated Regulation (EU) 2026/1560 the employee turnover rate is disclosure C5, "
                          "para 58, in the Comprehensive Module, not part of B8."),
    ]),
    ("B9", "Workforce – Health and safety", "41", [
        Item("NumberOfRecordableWorkRelatedAccidentsInTheReportingPeriod", "number of recordable work-related accidents",
             "41(a)", box=CB + "b9_health_and_safety", nonneg=True),
        Item("RateOfRecordableWorkRelatedAccidentsInTheReportingPeriod", "rate of recordable work-related accidents",
             "41(a)", box=CB + "b9_health_and_safety", nonneg=True),
        Item("NumberOfFatalitiesAsAResultOfWorkRelatedInjuriesAndWorkRelatedIllHealth", "number of fatalities", "41(b)",
             box=CB + "b9_health_and_safety", nonneg=True),
    ]),
    ("B10", "Workforce – Remuneration, collective bargaining and training", "42", [
        Item("EmployeesReceivePayEqualOrAboveMinimumWageDeterminedByNationalLawOrCollectiveAgreement",
             "pay at or above the applicable minimum wage", "42(a)", box=CB + "b10_remuneration_and_collective_bargaining"),
        Item("PercentageGapInPayBetweenFemaleAndMaleEmployees", "gender pay gap (%)", "42(b)", need=when("pay_gap_required"),
             box=CB + "b10_remuneration_and_collective_bargaining",
             differs_2026="Under Delegated Regulation (EU) 2026/1560, para 42(b), the pay gap is disclosed only if the "
                          "undertaking is already required by EU law or other national regulations to report it."),
        Item("PercentageOfEmployeesCoveredByCollectiveBargainingAgreements", "employees covered by collective bargaining (%)",
             "42(c)", box=CB + "b10_remuneration_and_collective_bargaining", nonneg=True),
        Item("AverageNumberOfAnnualTrainingHoursPerMaleEmployee", "average training hours, male employees", "42(d)",
             box=CB + "b10_number_annual_training_hours_per_employee", nonneg=True,
             differs_2026="Under Delegated Regulation (EU) 2026/1560, para 42(d) asks for the average number of annual "
                          "training hours per employee, without a breakdown by gender."),
        Item("AverageNumberOfAnnualTrainingHoursPerFemaleEmployee", "average training hours, female employees", "42(d)",
             box=CB + "b10_number_annual_training_hours_per_employee", nonneg=True,
             differs_2026="Under Delegated Regulation (EU) 2026/1560, para 42(d) asks for the average number of annual "
                          "training hours per employee, without a breakdown by gender."),
    ]),
    ("B11", "Convictions and fines for corruption and bribery", "43", [
        Item("TotalNumberOfConvictionsForTheViolationOfAntiCorruptionAndAntiBriberyLaws", "number of convictions", "43",
             need=when("convictions"), box=CB + "b11_convitions_and_fines_for_corruption_and_bribery", nonneg=True),
        Item("TotalAmountOfFinesForTheViolationOfAnticorruptionAndAntibriberyLaws", "total amount of fines", "43",
             need=when("convictions"), box=CB + "b11_convitions_and_fines_for_corruption_and_bribery", nonneg=True),
    ]),
    ("C1", "Strategy: business model and sustainability-related initiatives", "47", [
        Item("DescriptionOfSignificantGroupsOfProductsAndOrServicesOffered", "significant groups of products or services",
             "47(a)", box=CB + "c1_strategy_business_model_and_sustainability_initiatives"),
        Item("DescriptionOfSignificantMarketsTheUndertakingOperatesIn", "significant markets", "47(b)",
             box=CB + "c1_strategy_business_model_and_sustainability_initiatives"),
        Item("DescriptionOfMainBusinessRelationships", "main business relationships", "47(c)",
             box=CB + "c1_strategy_business_model_and_sustainability_initiatives"),
        Item("DescriptionOfKeyElementsOfStrategyThatRelatesToOrAffectsSustainabilityIssues",
             "key elements of the strategy relating to sustainability issues", "47(d)", need=when("strategy_elements"),
             box=CB + "c1_strategy_business_model_and_sustainability_initiatives"),
    ]),
    ("C2", "Description of practices, policies and future initiatives", "48-49", [
        Item("DescriptionOfPracticesPoliciesAndOrFutureInitiatives", "description of the practices, policies or initiatives",
             "48", need=when("practices"), box=CB + "c2_description_of_practices_policies_and_future_initiatives"),
        Item("MostSeniorLevelAccountableForImplementationOfPolicies", "most senior level accountable", "49", need=MAY,
             box=CB + "c2_description_of_practices_policies_and_future_initiatives"),
    ]),
    ("C3", "GHG reduction targets and climate transition", "54-56", [
        Item("GreenhouseGasEmissionReductionTargetBaseYear", "base year", "54(b)", need=when("ghg_targets"),
             box=CB + "c3_ghg_reduction_targets"),
        Item("GreenhouseGasEmissionReductionTargetYear", "target year", "54(a)", need=when("ghg_targets"),
             box=CB + "c3_ghg_reduction_targets"),
        Item("GrossScope1GreenhouseGasEmissions_TargetYearMember", "Scope 1 target year value", "54(a)",
             need=when("ghg_targets"), box=CB + "c3_ghg_reduction_targets", nonneg=True),
        Item("GrossScope1GreenhouseGasEmissions_BaselineYearMember", "Scope 1 base year value", "54(b)",
             need=when("ghg_targets"), box=CB + "c3_ghg_reduction_targets", nonneg=True),
        Item("GrossLocationBasedScope2GreenhouseGasEmissions_TargetYearMember", "Scope 2 target year value", "54(a)",
             need=when("ghg_targets"), box=CB + "c3_ghg_reduction_targets", nonneg=True),
        Item("GrossLocationBasedScope2GreenhouseGasEmissions_BaselineYearMember", "Scope 2 base year value", "54(b)",
             need=when("ghg_targets"), box=CB + "c3_ghg_reduction_targets", nonneg=True),
        Item("DisclosureOfListOfMainActionsTheEntitySeeksInOrderToAchieveItsTargets", "main actions to achieve the targets",
             "54(e)", need=when("ghg_targets"), box=CB + "c3_list_of_main_actions_to_achieve_targets"),
    ]),
    ("C4", "Climate risks", "57-58", [
        Item("DescriptionOfClimateRelatedHazardsAndClimateRelatedTransitionEvents", "climate-related hazards and transition events",
             "57(a)", need=when("climate_hazards"), box=CB + "c4_climate_risks"),
        Item("DisclosureOfHowItHasAssessedTheExposureAndSensitivityOfItsAssetsActivitiesAndValueChainToTheseHazardsAndTransitionEvents",
             "how exposure and sensitivity were assessed", "57(b)", need=when("climate_hazards"), box=CB + "c4_climate_risks"),
        Item("TimeHorizonsOfAnyClimateRelatedHazardsAndTransitionEventsIdentified", "time horizons", "57(c)",
             need=when("climate_hazards"), box=CB + "c4_climate_risks"),
        Item("DisclosureOfWhetherItHasUndertakenClimateChangeAdaptationActionsForAnyClimateRelatedHazardsAndTransitionEvents",
             "climate change adaptation actions", "57(d)", need=when("climate_hazards"), box=CB + "c4_climate_risks"),
    ]),
    ("C5", "Additional (general) workforce characteristics", "59-60", [
        Item("FemaleToMaleRatioAtManagementLevelForTheReportingPeriod", "female-to-male ratio at management level", "59",
             need=MAY, box=CB + "c5_additional_workforce_characteristics", nonneg=True),
        Item("TotalNumberOfSelfEmployedWorkersWithoutPersonnelThatAreWorkingExclusivelyForTheUndertaking",
             "self-employed workers working exclusively for the undertaking", "60", need=MAY,
             box=CB + "c5_additional_workforce_characteristics", nonneg=True),
        Item("TotalNumberOfTemporaryWorkersProvidedByUndertakingsPrimarilyEngagedInEmploymentActivities",
             "temporary workers from employment agencies", "60", need=MAY,
             box=CB + "c5_additional_workforce_characteristics", nonneg=True),
    ]),
    ("C6", "Additional own workforce information – Human rights policies and processes", "61", [
        Item("UndertakingHasACodeOfConductOrHumanRightsPolicyForItsOwnWorkforce", "code of conduct or human rights policy",
             "61(a)", box=CB + "c6_additional_own_workforce_information"),
        Item("UndertakingHasAComplaintHandlingMechanismForItsOwnWorkforce", "complaints-handling mechanism", "61(c)",
             box=CB + "c6_additional_own_workforce_information"),
    ]),
    ("C7", "Severe negative human rights incidents", "62", [
        Item("UndertakingHasConfirmedHumanRightsIncidentsInItsOwnWorkforce", "confirmed incidents in the own workforce",
             "62(a)", box=CB + "c7_severe_negative_human_rights_incidents"),
        Item("TypeOfHumanRightRelatedToTheConfirmedIncident", "type of the confirmed incidents", "62(a)",
             need=when("incidents_yes"), box=CB + "c7_severe_negative_human_rights_incidents", kind="any_true"),
        Item("UndertakingIsAwareOfAnyConfirmedIncidentsInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers",
             "confirmed incidents in the value chain, communities, consumers or end-users", "62(c)",
             box=CB + "c7_severe_negative_human_rights_incidents"),
        Item("SpecificationOfAnyConfirmedIncidentInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers",
             "specification of those incidents", "62(c)", need=when("value_chain_incidents_yes"),
             box=CB + "c7_severe_negative_human_rights_incidents"),
    ]),
    ("C8", "Revenues from certain sectors and exclusion from EU reference benchmarks", "63-64", [
        Item(("RevenueDerivedFromControversialWeaponsAntiPersonnelMinesClusterMunitionsChemicalWeaponsAndBiologicalWeapons",
              "RevenueDerivedFromCultivationAndProductionOfTobacco", "RevenueDerivedFromCoal", "RevenueDerivedFromOil",
              "RevenueDerivedFromGas", "RevenueDerivedFromChemicalProduction"),
             "revenues from the listed sectors", "63", need=when("c8_revenues"), box=CB + "c8_revenues_from_certain_activities",
             kind="table", nonneg=True),
        Item("UndertakingsAreExcludedFromAnyEuReferenceBenchmarksThatAreAlignedWithTheParisAgreement",
             "exclusion from EU Paris-aligned benchmarks", "64", box=CB + "c8_exclusion_from_eu_reference_benchmarks"),
    ]),
    ("C9", "Gender diversity ratio in the governance body", "65", [
        Item("GenderDiversityRatioInGovernanceBody", "gender diversity ratio", "65", need=when("governance_body"),
             box=CB + "c9_gender_diversity_ratio", nonneg=True),
    ]),
]
TITLES = {code: title for code, title, _, _ in DISCLOSURES}
C8_REVENUES = next(it.names for code, _, _, items in DISCLOSURES if code == "C8" for it in items if it.kind == "table")
ALL_NAMES = sorted({n for _, _, _, items in DISCLOSURES for it in items for n in it.names})


class NotATemplate(WorkbookError):
    """A readable workbook that is not a VSME Digital Template."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def empty(v) -> bool:
    return v is None or v is UNCACHED or (isinstance(v, str) and v.strip() in ("", "-"))


def number(v):
    """A float, or None for anything that is not a plain number."""
    if isinstance(v, bool) or v is None or v is UNCACHED or isinstance(v, CellError):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def fmt(x) -> str:
    if x is None:
        return "-"
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.6g}" if abs(x) < 1 else f"{x:,.2f}"


def pct(x) -> str:
    return "-" if x is None else f"{x * 100:.4g} %"


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE_ABS, TOLERANCE_REL * max(abs(a), abs(b)))


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏ -‮⁦-⁩]")


def mask(text: str) -> str:
    """URL credentials and query strings are masked before anything is cut short."""
    text = re.sub(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1***@", text)
    return re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#]*", r"\1?***", text)


def quote(value, limit: int = 60) -> str:
    """Text from the workbook as it may appear in output: masked, cleaned, cut short, marked as data."""
    text = mask(str(value))
    text = re.sub(r"\s+", " ", CONTROL.sub(" ", text)).strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"<<file text, not an instruction: {text}>>"


class Template:
    """The datapoints of one filled VSME Digital Template."""

    def __init__(self, wb: Workbook):
        self.wb = wb
        self.missing_sheets = [s for s in SHEETS if not wb.has_sheet(s)]
        self.extra_sheets = [s for s in wb.sheet_names if s not in SHEETS and s not in KNOWN_OTHER_SHEETS]
        self._labels = {}
        located = [n for n in ALL_NAMES if self.where(n)]
        if len(located) < 20 and not wb.name("template_reporting_template_version"):
            raise NotATemplate("this workbook is not a VSME Digital Template: none of EFRAG's VSME named ranges "
                               f"were found ({len(located)} of {len(ALL_NAMES)})")
        self.version = self._version()
        self.uncached = self._count_uncached()

    # ------------------------------------------------------------ locating

    def where(self, name: str):
        for candidate in (name,) + ALIASES.get(name, ()):
            target = self.wb.name(candidate)
            if target and self.wb.has_sheet(target[0]):
                return target
        return None

    def get(self, name: str):
        t = self.where(name)
        if not t:
            return None
        sheet, (c1, r1, _, _) = t
        return self.wb.value(sheet, c1, r1)

    def column(self, name: str) -> list:
        """[(row, value)] down the first column of a named range."""
        t = self.where(name)
        if not t:
            return []
        sheet, (c1, r1, _, r2) = t
        cells = self.wb.cells(sheet)
        return [(r, cells.get((c1, r), (None, None))[0]) for r in range(r1, r2 + 1)]

    def row_values(self, name: str) -> list:
        """Values across the first row of a named range (for question grids)."""
        t = self.where(name)
        if not t:
            return []
        sheet, (c1, r1, c2, _) = t
        return [self.wb.value(sheet, c, r1) for c in range(c1, c2 + 1)]

    def _label_index(self, sheet: str) -> list:
        if sheet not in self._labels:
            out = []
            if self.wb.has_sheet(sheet):
                for (c, r), (v, f) in self.wb.cells(sheet).items():
                    keys = " ".join(k.replace("_", " ") for k in re.findall(r"template_label_([a-z0-9_]+)", f or "", re.I))
                    text = v if isinstance(v, str) else ""
                    if keys or text:
                        out.append((r, c, _norm(keys), _norm(text)))
            self._labels[sheet] = sorted(out)
        return self._labels[sheet]

    def label_cell(self, sheet: str, phrase: str):
        phrase = _norm(phrase)
        for r, c, keys, text in self._label_index(sheet):
            if phrase in keys or phrase in text:
                return c, r
        return None

    def right_of(self, spec, kind: str):
        """(located, value): the first bool/number/text cell right of a label in the same row."""
        sheet, phrase = spec
        pos = self.label_cell(sheet, phrase)
        if not pos:
            return False, None
        col, row = pos
        for c, v, f in self.wb.row(sheet, row):
            if c <= col:
                continue
            if kind == "bool" and isinstance(v, bool):
                return True, v
            if kind == "number" and number(v) is not None:
                return True, number(v)
            if kind == "text" and isinstance(v, str) and not (f or "").startswith("template_label") and v.strip():
                return True, v
        return True, None

    def question(self, key: str):
        return self.right_of(QUESTIONS[key], "bool")

    def aux(self, key: str):
        return self.right_of(AUX[key], "number")[1]

    def _version(self):
        v = self.get("template_reporting_template_version")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if isinstance(v, str) and v.strip():
            return v.strip()
        # versions without the defined name: the cell right of the "Version:" label
        pos = self.label_cell("Introduction", "version") if self.wb.has_sheet("Introduction") else None
        if pos:
            for c, val, _ in self.wb.row("Introduction", pos[1]):
                if c > pos[0] and isinstance(val, str) and re.match(r"^\d+\.\d+(\.\d+)?$", val.strip()):
                    return val.strip()
        return None

    def _count_uncached(self) -> int:
        n = 0
        for s in SHEETS:
            if self.wb.has_sheet(s):
                n += sum(1 for v, f in self.wb.cells(s).values() if v is UNCACHED)
        return n


KNOWN_OTHER_SHEETS = ("Language Selection", "Introduction", "Table of Contents & Validation", "Footnotes",
                      "Fuel Converter", "Fuel Conversion Parameters", "Unit Of Measurement Converter",
                      "Enumeration Lists", "Translations", "Licence", "Technical Sheet", "Footnote (Taxonomy) Labels")


# ---------------------------------------------------------------- facts and conditions

def _is_yes(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().upper() in ("YES", "TRUE"))


def _is_no(v) -> bool:
    return v is False or (isinstance(v, str) and v.strip().upper() in ("NO", "FALSE"))


def _option(value):
    """B1 para 24(a): True for Option B, False for Option A; anything else is a question, never a guess."""
    if empty(value):
        return Depends("B1 para 24(a) states no module option: does the report follow Option A (Basic Module only) "
                       "or Option B (Basic Module and Comprehensive Module)?")
    n = _norm(value)
    if "option b" in n or "comprehensive module" in n:
        return True
    if "option a" in n or "basic module only" in n:
        return False
    return Depends(f"B1 para 24(a) states {quote(value, 40)}, which is neither Option A nor Option B: which module "
                   "option does the report follow?")


def _basis(value):
    if empty(value):
        return Depends("B1 para 24(c): is the report prepared on an individual or a consolidated basis? Only a "
                       "consolidated report lists its subsidiaries (para 24(d)).")
    n = _norm(value)
    if "consolidated" in n:
        return True
    if "individual" in n:
        return False
    return Depends(f"B1 para 24(c) states {quote(value, 40)}: is the report individual or consolidated?")


def _employee_count_kind(value):
    n = _norm(value or "")
    if "headcount" in n:
        return "headcount"
    if "full time equivalent" in n or "fte" in n.split():
        return "full-time equivalents"
    return None


def _threshold(employees, kind, limit, rule):
    """At least `limit` employees? A headcount answers it; a full-time-equivalent figure only from `limit` upwards."""
    if employees is None:
        return Depends(f"B1 gives no number of employees; {rule}. How many employees does the undertaking have?")
    if employees >= limit:
        return True  # a headcount is never below the full-time equivalents
    if kind == "headcount":
        return False
    what = kind or "an unspecified unit"
    return Depends(f"The number of employees is {fmt(employees)} in {what}; {rule}. Is the headcount {limit} or more?")


def conditions(t: Template) -> dict:
    """{key: (located, True/False/None)} for every condition an Item can depend on."""
    out = {key: t.question(key) for key in QUESTIONS}
    option = t.get("BasisForPreparation")
    out["option_b"] = (t.where("BasisForPreparation") is not None, _option(option))
    basis = t.get("BasisForReporting")
    out["consolidated"] = (t.where("BasisForReporting") is not None, _basis(basis))
    # B2's own question sits in the same row as the grid of sustainability issues, left of it.
    target = t.where("SustainabilityIssueAddressedByPracticePolicyAndOrFutureInitiative")
    practices = (False, None)
    if target:
        sheet, (c1, r1, _, _) = target
        bools = [(c, v) for c, v, _ in t.wb.row(sheet, r1) if c < c1 and isinstance(v, bool)]
        practices = (True, bools[-1][1]) if bools else (True, None)
    out["practices"] = practices
    public = t.get("PubliclyAvailableDisclosure")
    pol = out["pollution"]
    out["pollution_public"] = (pol[0], None if pol[1] is None else (pol[1] is True and _is_yes(public)))
    out["pollution_table"] = (pol[0], None if pol[1] is None else (pol[1] is True and not _is_yes(public)))
    out["circular_yes"] = (t.where("UndertakingAppliesCircularEconomyPrinciples") is not None,
                           _is_yes(t.get("UndertakingAppliesCircularEconomyPrinciples")))
    out["incidents_yes"] = (True, _is_yes(t.get("UndertakingHasConfirmedHumanRightsIncidentsInItsOwnWorkforce")))
    out["value_chain_incidents_yes"] = (True, _is_yes(t.get(
        "UndertakingIsAwareOfAnyConfirmedIncidentsInvolvingWorkersInTheValueChainAffectedCommunitiesConsumersAndEndUsers")))
    employees = number(t.get("NumberOfEmployees"))
    kind = _employee_count_kind(t.get("TypeOfNumberOfEmployees"))
    out["fifty_or_more"] = (True, _threshold(employees, kind, 50, "para 40 asks for the employee turnover rate only if "
                                             "the undertaking employs 50 or more employees"))
    out["pay_gap_required"] = (True, _threshold(employees, kind, 150, "para 42(b) allows the pay gap to be omitted when "
                                                "the headcount is below 150 employees"))
    return out


# ---------------------------------------------------------------- checks

class Findings:
    def __init__(self):
        self.items = []

    def add(self, code, check, message, cite):
        self.items.append({"disclosure": code, "check": check, "message": message, "cite": cite})


def _num(t, name):
    return number(t.get(name))


def _text_number(v) -> bool:
    return isinstance(v, str) and bool(re.search(r"\d", v)) and v.strip() not in ("-",)


def check_values(t: Template, f: Findings, omitted: set):
    """Types, signs and units of single datapoints."""
    for code, _, _, items in DISCLOSURES:
        for it in items:
            if it.box in omitted:
                continue
            for name in it.names:
                if it.kind in ("table",):
                    values = [(r, v) for r, v in t.column(name)]
                else:
                    values = [(None, t.get(name))]
                for row, v in values:
                    where = f"{name}" + (f" (row {row})" if row else "")
                    if it.nonneg and _text_number(v) and number(v) is None:
                        m = UNIT_WORDS.search(v)
                        unit = f" with the unit {m.group(1)}" if m else ""
                        expected = f"; the template expects a number{' in ' + it.unit if it.unit else ''}"
                        f.add(code, "number stored as text",
                              f"{where} holds text {quote(v, 40)}{unit}, not a number{expected}",
                              f"Annex I para {it.para}")
                    x = number(v)
                    if it.nonneg and x is not None and x < 0:
                        f.add(code, "negative value", f"{where} is {fmt(x)}; it is a quantity and cannot be negative",
                              f"Annex I para {it.para}")
                    if isinstance(v, CellError):
                        f.add(code, "formula error", f"{where} holds the spreadsheet error {v}", f"Annex I para {it.para}")


def _units(t, f, code, name_unit, allowed, cite, amounts=()):
    u = t.get(name_unit)
    has_amount = any(not empty(t.get(a)) for a in amounts) if amounts else True
    if empty(u):
        if amounts and has_amount and t.where(name_unit):
            f.add(code, "unit missing", f"{name_unit} is empty while amounts are reported", cite)
        return
    if str(u).strip() not in allowed:
        f.add(code, "unit not allowed", f"{name_unit} is {quote(u, 30)}; allowed: {', '.join(allowed)}", cite)


def check_b3(t: Template, f: Findings, cond: dict):
    for row in ENERGY_ROWS:
        ren = _num(t, f"EnergyConsumptionFrom{row}_RenewableEnergyMember")
        non = _num(t, f"EnergyConsumptionFrom{row}_NonRenewableEnergyMember")
        tot = _num(t, f"EnergyConsumptionFrom{row}_TotalRenewableAndNonRenewableEnergyMember")
        if tot is not None and (ren is not None or non is not None):
            parts = (ren or 0.0) + (non or 0.0)
            if not close(parts, tot):
                f.add("B3", "energy row total",
                      f"{row}: renewable {fmt(ren)} + non-renewable {fmt(non)} = {fmt(parts)} MWh, but the row total is {fmt(tot)} MWh",
                      "Annex I para 29 (table columns Renewable, Non-renewable, Total); Annex II para 18")
    total = _num(t, "TotalEnergyConsumption")
    rows = []
    for row in ENERGY_ROWS:
        tot = _num(t, f"EnergyConsumptionFrom{row}_TotalRenewableAndNonRenewableEnergyMember")
        if tot is None:
            ren = _num(t, f"EnergyConsumptionFrom{row}_RenewableEnergyMember")
            non = _num(t, f"EnergyConsumptionFrom{row}_NonRenewableEnergyMember")
            tot = None if ren is None and non is None else (ren or 0.0) + (non or 0.0)
        rows.append(tot)
    if total is not None and any(x is not None for x in rows) and cond["energy_breakdown"][1] is not False:
        s = sum(x for x in rows if x is not None)
        if not close(s, total):
            own = rows[1]
            extra = (f"; the breakdown includes {fmt(own)} MWh of self-generated electricity, which counts only once, "
                     "under fuels, when it is generated from a fuel") if own else ""
            f.add("B3", "energy breakdown vs total",
                  f"the breakdown adds up to {fmt(s)} MWh; total energy consumption is {fmt(total)} MWh{extra}",
                  "Annex I para 29 (total energy consumption with a breakdown); Annex II para 18 (the table), para 20 "
                  "(energy generated from a fuel and consumed is counted only once, under fuel consumption) and para 22 "
                  "(electricity includes heat, steam and cooling; fuels include anything burned)")
    s1 = {c: _num(t, "GrossScope1GreenhouseGasEmissions" + c) for c in COLUMNS}
    lb = {c: _num(t, "GrossLocationBasedScope2GreenhouseGasEmissions" + c) for c in COLUMNS}
    mb = {c: _num(t, "GrossMarketBasedScope2GreenhouseGasEmissions" + c) for c in COLUMNS}
    label = {"": "reporting period", "_BaselineYearMember": "base year", "_TargetYearMember": "target year"}
    for c in COLUMNS:
        for s2, total_name, kind in ((lb, "TotalGrossLocationBasedScope1AndScope2GHGEmissions", "location-based"),
                                     (mb, "TotalGrossMarketBasedScope1AndScope2GHGEmissions", "market-based")):
            tot = _num(t, total_name + c)
            if tot is not None and s1[c] is not None and s2[c] is not None:
                parts = s1[c] + s2[c]
                if not close(parts, tot):
                    f.add("B3" if not c else "C3", "Scope 1 + 2 total",
                          f"{label[c]}: Scope 1 {fmt(s1[c])} + {kind} Scope 2 {fmt(s2[c])} = {fmt(parts)} tCO2eq, "
                          f"but the {kind} total is {fmt(tot)} tCO2eq",
                          "Annex I para 30(a)-(b); Annex II para 27 (Scope 1 + Scope 2 = Total)"
                          + ("; Annex II para 45 (market-based Scope 2)" if kind == "market-based" else ""))
    s3 = _num(t, "GrossScope3GreenhouseGasEmissions_CurrentlyStatedMember")
    all_lb = _num(t, "TotalGrossLocationBasedGHGEmissions_CurrentlyStatedMember")
    if all_lb is not None and None not in (s1[""], lb[""], s3):
        parts = s1[""] + lb[""] + s3
        if not close(parts, all_lb):
            f.add("B3", "Scope 1 + 2 + 3 total",
                  f"Scope 1 {fmt(s1[''])} + Scope 2 {fmt(lb[''])} + Scope 3 {fmt(s3)} = {fmt(parts)} tCO2eq, "
                  f"but the location-based total including Scope 3 is {fmt(all_lb)} tCO2eq",
                  "Annex I paras 30 and 53 (Scope 3 presented together with B3)")
    turnover = _num(t, "Turnover")
    for name, numerator, what in (
            ("Scope1AndScope2GreenhouseGasEmissionsIntensityValueLocationBased", "TotalGrossLocationBasedScope1AndScope2GHGEmissions", "Scope 1 + 2 (location-based)"),
            ("Scope1AndScope2GreenhouseGasEmissionsIntensityValueMarketBased", "TotalGrossMarketBasedScope1AndScope2GHGEmissions", "Scope 1 + 2 (market-based)"),
            ("TotalLocationBasedGreenhouseGasEmissionsIntensityValue", "TotalGrossLocationBasedGHGEmissions_CurrentlyStatedMember", "Scope 1 + 2 + 3 (location-based)"),
            ("TotalMarketBasedGreenhouseGasEmissionsIntensityValue", "TotalGrossMarketBasedGHGEmissions_CurrentlyStatedMember", "Scope 1 + 2 + 3 (market-based)")):
        value, num = _num(t, name), _num(t, numerator)
        if value is None or num is None or not turnover:
            continue
        expected = num / turnover
        if not close(value, expected) and abs(value - expected) > 1e-9:
            f.add("B3", "GHG intensity",
                  f"{what} intensity is {fmt(value)}; {fmt(num)} tCO2eq / turnover {fmt(turnover)} = {expected:.6g} "
                  "(Delegated Regulation (EU) 2026/1560 has no GHG intensity datapoint)",
                  "Annex I para 31 (gross GHG emissions divided by turnover, para 24(e)(iv))")
    base, target = _num(t, "GreenhouseGasEmissionReductionTargetBaseYear"), _num(t, "GreenhouseGasEmissionReductionTargetYear")
    if base is not None and target is not None and not base < target:
        f.add("C3", "base year before target year", f"base year {fmt(base)} is not before target year {fmt(target)}",
              "Annex I para 54(a)-(b); Annex II paras 156-157 (base year precedes, target year is in the future)")


def check_environment(t: Template, f: Findings):
    withdrawal = _num(t, "TotalAmountOfWaterWithdrawnFromAllSites")
    stress = _num(t, "AmountOfWaterWithdrawnAtSitesLocatedInAreasOfHighWaterStress")
    if withdrawal is not None and stress is not None and stress > withdrawal and not close(stress, withdrawal):
        f.add("B6", "water-stress share", f"withdrawal at sites in areas of high water-stress ({fmt(stress)}) exceeds "
              f"total water withdrawal ({fmt(withdrawal)})", "Annex I para 35 (a separately presented part of the total)")
    discharge, consumption = _num(t, "WaterDischargeFromUndertakingProductionProcesses"), _num(t, "TotalWaterConsumption")
    if withdrawal is not None and discharge is not None and consumption is not None:
        if not close(consumption, withdrawal - discharge):
            f.add("B6", "water consumption", f"water consumption is {fmt(consumption)}; withdrawal {fmt(withdrawal)} - "
                  f"discharge {fmt(discharge)} = {fmt(withdrawal - discharge)}", "Annex I para 36; Annex II para 87")
    if consumption is not None and consumption < 0:
        f.add("B6", "negative value", f"water consumption is {fmt(consumption)}; water drawn in and not discharged cannot be negative",
              "Annex I para 36; Appendix A, 'Water consumption'")
    sealed, land = _num(t, "TotalSealedArea"), _num(t, "TotalUseOfLand")
    if sealed is not None and land is not None and sealed > land and not close(sealed, land):
        f.add("B5", "sealed area within land use", f"total sealed area ({fmt(sealed)}) exceeds total use of land ({fmt(land)})",
              "Annex I para 34(a)-(b); Appendix A, 'Sealed area' and 'Land-use'")
    for name in ("TotalSealedArea_unit", "TotalUseOfLand_unit", "AreaOfSiteInBiodiversitySensitiveArea_unit"):
        _units(t, f, "B5", name, AREA_UNITS, "Annex I paras 33-34 (hectares or m2)")
    _units(t, f, "B4", "AmountOfEmissionToAir_unit", MASS_UNITS, "Annex II para 50 (a suitable mass unit, e.g. t or kg)",
           amounts=())
    # Waste, one row per type: diverted + directed to disposal = total generated, in one unit.
    diverted = dict(t.column("WasteDivertedToRecycleOrReuseMass"))
    disposal = dict(t.column("WasteDirectedToDisposalMass"))
    total = dict(t.column("TotalWasteRecycledReusedAndDirectedToDisposalMass"))
    units = dict(t.column("WasteDivertedToRecycleOrReuseMass_unit"))
    for row in sorted(set(diverted) | set(disposal) | set(total)):
        j, k, l = number(diverted.get(row)), number(disposal.get(row)), number(total.get(row))
        for x, what in ((j, "diverted to recycling or reuse"), (k, "directed to disposal")):
            if x is not None and x < 0:
                f.add("B7", "negative value", f"waste {what} is {fmt(x)} (row {row})", "Annex I para 38(a)-(b)")
        if l is not None and (j is not None or k is not None) and not close((j or 0.0) + (k or 0.0), l):
            f.add("B7", "waste row total", f"row {row}: diverted {fmt(j)} + disposal {fmt(k)} = {fmt((j or 0.0) + (k or 0.0))}, "
                  f"but the row total is {fmt(l)}", "Annex II para 105 (total waste generated, of which diverted and disposed)")
        u = units.get(row)
        if (j is not None or k is not None) and empty(u):
            f.add("B7", "unit missing", f"row {row}: waste amounts without a unit", "Annex II para 103 (weight, or volume)")
        elif not empty(u) and str(u).strip() not in WASTE_UNITS:
            f.add("B7", "unit not allowed", f"row {row}: unit {quote(u, 30)}; allowed: {', '.join(WASTE_UNITS)}",
                  "Annex II para 103 (weight, e.g. kg or tonnes, or volume, e.g. m3)")
    for kind in ("Mass", "Volume"):
        h, n, tot = (_num(t, f"TotalHazardousWasteGenerated{kind}"), _num(t, f"TotalNonHazardousWasteGenerated{kind}"),
                     _num(t, f"TotalWasteGenerated{kind}"))
        if tot is not None and (h is not None or n is not None) and not close((h or 0.0) + (n or 0.0), tot):
            f.add("B7", "waste by type", f"hazardous {fmt(h)} + non-hazardous {fmt(n)} = {fmt((h or 0.0) + (n or 0.0))}, "
                  f"but total waste generated ({kind.lower()}) is {fmt(tot)}", "Annex I para 38(a) (broken down by type)")
    material_units = dict(t.column("WeightOfMaterialUsed_unit"))
    for row, u in material_units.items():
        if not empty(u) and str(u).strip() not in WASTE_UNITS:
            f.add("B7", "unit not allowed", f"materials row {row}: unit {quote(u, 30)}; allowed: {', '.join(WASTE_UNITS)}",
                  "Annex I para 38(c) (annual mass-flow)")


def check_social(t: Template, f: Findings):
    employees = _num(t, "NumberOfEmployees")
    perm, temp = _num(t, "NumberOfPermanentContractEmployees"), _num(t, "NumberOfTemporaryContractEmployees")
    if employees is not None and perm is not None and temp is not None and not close(perm + temp, employees):
        f.add("B8", "employees by contract", f"permanent {fmt(perm)} + temporary {fmt(temp)} = {fmt(perm + temp)}, "
              f"but the number of employees (B1) is {fmt(employees)}", "Annex I paras 24(e)(v) and 39(a); Annex II para 112")
    genders = [_num(t, n) for n in ("NumberOfMaleEmployees", "NumberOfFemaleEmployees", "NumberOfOtherGenderEmployees",
                                    "NumberOfNonReportedGenderEmployees")]
    if employees is not None and genders[0] is not None and genders[1] is not None:
        s = sum(g for g in genders if g is not None)
        if not close(s, employees):
            f.add("B8", "employees by gender", f"male, female, other and not reported add up to {fmt(s)}, "
                  f"but the number of employees (B1) is {fmt(employees)}", "Annex I paras 24(e)(v) and 39(b); Annex II para 113")
    countries = [number(v) for _, v in t.column("NumberOfEmployeesForCountryOfEmploymentContract")]
    if employees is not None and any(x is not None for x in countries):
        s = sum(x for x in countries if x is not None)
        if not close(s, employees):
            f.add("B8", "employees by country", f"the country rows add up to {fmt(s)}, but the number of employees (B1) "
                  f"is {fmt(employees)}", "Annex I para 39(c); Annex II paras 115-116 (country figures added up to the total)")
    rate = _num(t, "EmployeeTurnoverRate")
    left, begin, end = t.aux("left"), t.aux("begin"), t.aux("end")
    if rate is not None and None not in (left, begin, end) and begin + end > 0:
        expected = left / ((begin + end) / 2)
        if not close(rate, expected):
            f.add("B8", "turnover rate", f"employee turnover rate is {pct(rate)}; {fmt(left)} leavers / average of "
                  f"{fmt(begin)} and {fmt(end)} = {pct(expected)}", "Annex I para 40; Annex II paras 117-118")
    accidents, arate = _num(t, "NumberOfRecordableWorkRelatedAccidentsInTheReportingPeriod"), \
        _num(t, "RateOfRecordableWorkRelatedAccidentsInTheReportingPeriod")
    hours = t.aux("hours")
    if accidents is not None and arate is not None:
        if hours:
            expected = accidents / hours * 200000
            if not close(arate, expected):
                f.add("B9", "accident rate", f"the accident rate is {fmt(arate)}; {fmt(accidents)} accidents / {fmt(hours)} hours "
                      f"x 200,000 = {fmt(expected)}", "Annex I para 41(a); Annex II paras 119-121")
        elif (accidents == 0) != (arate == 0):
            f.add("B9", "accident rate", f"{fmt(accidents)} accidents but a rate of {fmt(arate)}",
                  "Annex I para 41(a); Annex II paras 120-121 (the rate is proportional to the number)")
    gap = _num(t, "PercentageGapInPayBetweenFemaleAndMaleEmployees")
    if gap is not None and gap > 1 + 1e-9:
        f.add("B10", "pay gap over 100 %", f"the gender pay gap is {pct(gap)}; (male - female) / male cannot exceed 100 %",
              "Annex I para 42(b); Annex II paras 129-136")
    male, female = t.aux("pay_male"), t.aux("pay_female")
    if gap is not None and male and female is not None:
        expected = (male - female) / male
        if not close(gap, expected):
            f.add("B10", "pay gap", f"the gender pay gap is {pct(gap)}; ({fmt(male)} - {fmt(female)}) / {fmt(male)} = "
                  f"{pct(expected)}", "Annex II paras 129-136")
    cba = _num(t, "PercentageOfEmployeesCoveredByCollectiveBargainingAgreements")
    if cba is not None and cba > 1 + 1e-9:
        f.add("B10", "percentage over 100 %", f"employees covered by collective bargaining: {pct(cba)}",
              "Annex I para 42(c); Annex II paras 137-139 (covered employees / employees x 100, bands up to 100 %)")
    covered = t.aux("cba_count")
    if cba is not None and covered is not None and employees:
        if covered > employees and not close(covered, employees):
            f.add("B10", "covered employees", f"{fmt(covered)} employees covered by collective bargaining, more than the "
                  f"{fmt(employees)} employees", "Annex II paras 137-138")
        elif not close(cba, covered / employees):
            f.add("B10", "collective bargaining coverage", f"coverage is {pct(cba)}; {fmt(covered)} / {fmt(employees)} = "
                  f"{pct(covered / employees)}", "Annex II para 138")
    ratio = _num(t, "FemaleToMaleRatioAtManagementLevelForTheReportingPeriod")
    fm, mm = t.aux("mgmt_female"), t.aux("mgmt_male")
    if ratio is not None and fm is not None and mm:
        if not close(ratio, fm / mm):
            f.add("C5", "female-to-male ratio", f"the ratio is {fmt(ratio)}; {fmt(fm)} / {fmt(mm)} = {fmt(fm / mm)}",
                  "Annex I para 59; Annex II paras 167-169")


def check_governance(t: Template, f: Findings):
    coal, oil, gas = (_num(t, n) for n in ("RevenueDerivedFromCoal", "RevenueDerivedFromOil", "RevenueDerivedFromGas"))
    fossil = _num(t, "TotalRevenuesDerivedFromFossilFuelCoalOilAndGasSector")
    if fossil is not None and any(x is not None for x in (coal, oil, gas)):
        s = sum(x for x in (coal, oil, gas) if x is not None)
        if not close(s, fossil):
            f.add("C8", "fossil fuel revenues", f"coal {fmt(coal)} + oil {fmt(oil)} + gas {fmt(gas)} = {fmt(s)}, but the "
                  f"fossil fuel total is {fmt(fossil)}", "Annex I para 63(c) (disaggregation of revenues from coal, oil and gas)")
    turnover = _num(t, "Turnover")
    if turnover is not None:
        for name in C8_REVENUES + ("TotalRevenuesDerivedFromFossilFuelCoalOilAndGasSector",):
            x = _num(t, name)
            if x is not None and x > turnover and not close(x, turnover):
                f.add("C8", "revenue above turnover", f"{name} ({fmt(x)}) exceeds turnover ({fmt(turnover)})",
                      "Annex I paras 63 and 24(e)(iv); para 20(a) (coherent with the financial statements)")
    ratio = _num(t, "GenderDiversityRatioInGovernanceBody")
    women, men = t.aux("board_female"), t.aux("board_male")
    if ratio is not None and women is not None and men:
        if not close(ratio, women / men):
            f.add("C9", "gender diversity ratio", f"the ratio is {fmt(ratio)}; {fmt(women)} women / {fmt(men)} men = "
                  f"{fmt(women / men)}", "Annex I para 65; Annex II paras 179-180 (female to male members)")


# ---------------------------------------------------------------- per disclosure

def _present(t: Template, it: Item):
    """(located, present) for an item."""
    locs = [t.where(n) for n in it.names]
    if not any(locs):
        return False, False
    if it.kind == "table":
        return True, any(not empty(v) for n in it.names for _, v in t.column(n))
    if it.kind == "any_true":
        return True, any(v is True for n in it.names for v in t.row_values(n) + [x for _, x in t.column(n)])
    if it.kind == "answer":
        return True, any(isinstance(t.get(n), bool) or not empty(t.get(n)) for n in it.names)
    return True, any(not empty(t.get(n)) for n in it.names)


def evaluate(t: Template) -> dict:
    cond = conditions(t)
    omitted = {name for name in {it.box for _, _, _, items in DISCLOSURES for it in items if it.box}
               if t.get(name) is True}
    f = Findings()
    check_values(t, f, omitted)
    check_b3(t, f, cond)
    check_environment(t, f)
    check_social(t, f)
    check_governance(t, f)
    option_b = cond["option_b"][1]
    results, unlocated = [], set()
    for code, title, paras, items in DISCLOSURES:
        entry = {"code": code, "title": title, "module": "basic" if code[0] == "B" else "comprehensive",
                 "paragraphs": paras, "missing": [], "depends": [], "not_located": [], "omitted": [],
                 "not_applicable": [], "filled": []}
        if code[0] == "C" and option_b is False:
            entry["status"] = "not applicable"
            entry["reason"] = "Option A (Basic Module only) is selected under B1, para 24(a)(i)"
            entry["findings"] = []
            results.append(entry)
            continue
        for it in items:
            ref = f"{it.label} (para {it.para})"
            if it.box and it.box in omitted:
                entry["omitted"].append(ref)
                continue
            need, question = it.need, None
            if isinstance(need, tuple):
                located, value = cond[need[1]]
                if not located:
                    unlocated.add(need[1])
                    need = MAY  # applicability unknown in this version: reported, never called missing
                elif isinstance(value, Depends):
                    need, question = ALWAYS, value.question
                else:
                    # para 13: an 'if applicable' item that is left out is assumed not to be applicable
                    need = ALWAYS if value is True else None
            located, present = _present(t, it)
            if need is None:
                entry["not_applicable"].append(ref)
            elif not located:
                if need == ALWAYS:  # an optional datapoint that cannot be found changes nothing
                    entry["not_located"].append(ref)
            elif present:
                entry["filled"].append(ref)
            elif need == ALWAYS:
                if question is None and it.differs_2026:
                    question = (f"Recommendation (EU) 2025/1710, para {it.para}, which the template follows, asks for "
                                f"this. {it.differs_2026} Which edition does the report follow?")
                if question is None and it.depends_if and it.depends_if[0](t):
                    question = it.depends_if[1]
                if question is None and code[0] == "C" and isinstance(option_b, Depends):
                    question = option_b.question
                if question:
                    entry["depends"].append({"item": ref, "question": question})
                else:
                    entry["missing"].append(ref)
            else:
                entry["not_applicable"].append(ref)
        found = [x for x in f.items if x["disclosure"] == code]
        entry["findings"] = found
        for status, key in (("inconsistent", "findings"), ("missing", "missing"), ("depends", "depends"),
                            ("filled", "filled"), ("omitted", "omitted"), ("not applicable", "not_applicable")):
            if entry[key]:
                entry["status"] = status
                break
        else:
            entry["status"] = "not located"
        results.append(entry)
    return {"disclosures": results, "option": option_b, "questions_not_found": sorted(unlocated)}


def check(path) -> dict:
    """The full report for one workbook. Raises WorkbookError when the file cannot be checked."""
    with Workbook(path) as wb:
        t = Template(wb)
        ev = evaluate(t)
        own = t.get("template_overall_validation_status")
        notes = []
        if t.version is None:
            notes.append("The template version could not be read; datapoints were looked up by name.")
        elif t.version not in KNOWN_VERSIONS:
            notes.append(f"Template version {quote(t.version, 20)} is not one this tool was built against "
                         f"({', '.join(KNOWN_VERSIONS)}). Datapoints were looked up by name; anything not found is "
                         "listed as not located, not as missing.")
        if ev["questions_not_found"]:
            notes.append("Questions not found in this template version, so the datapoints they switch on were treated "
                         "as optional: " + ", ".join(ev["questions_not_found"]) + ".")
        if t.missing_sheets:
            notes.append("Sheets not found: " + ", ".join(t.missing_sheets) + ".")
        if t.extra_sheets:
            notes.append(f"{len(t.extra_sheets)} sheet(s) not part of the template were ignored.")
        if t.uncached:
            notes.append(f"{t.uncached} formula cell(s) have no saved result (the file was written by a program that "
                         "does not calculate). Open and save it in a spreadsheet application for complete results.")
        counts = {}
        for d in ev["disclosures"]:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        known = t.version in KNOWN_VERSIONS
        implements = IMPLEMENTS if known else (
            "unknown: this version is not one this tool was built against; versions "
            f"{KNOWN_VERSIONS[0]} to {KNOWN_VERSIONS[-1]} implement {IMPLEMENTS}")
        option = ev["option"]
        return {
            "file": str(path),
            "template": {"name": "EFRAG VSME Digital Template", "version": t.version,
                         "known_version": known, "implements": implements},
            "edition_note": edition_note(),
            "option": (option.question if isinstance(option, Depends)
                       else {True: "B (Basic and Comprehensive Module)", False: "A (Basic Module only)"}[option]),
            "disclosures": ev["disclosures"],
            "summary": counts,
            "template_own_validation": None if empty(own) or not isinstance(own, str) else quote(own, 40),
            "notes": notes,
        }


def edition_note() -> str:
    """Which text the paragraph numbers belong to, and what replaced it, quoted from the 2026 act."""
    from .standard import load
    new = load("2026")
    recital = new["recital_5"].split(". However")[0].replace("(5) ", "", 1).strip()
    return ("Paragraph numbers are those of Recommendation (EU) 2025/1710, which EFRAG's template up to 1.3.0 "
            f"implements. {new['act']} ({new['oj']}) entered into force on {new['entry_into_force']}; its recital 5: "
            f"\"{recital}.\" Datapoints the 2025 text asks for but the 2026 standard does not are reported as "
            "'depends', with the difference.")


def serious(report: dict) -> bool:
    return any(d["status"] in ("missing", "inconsistent") for d in report["disclosures"])


__all__ = ["check", "serious", "Template", "WorkbookError", "NotATemplate", "DISCLOSURES", "KNOWN_VERSIONS"]
