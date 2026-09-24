# csrd-scope

<!-- mcp-name: io.github.Keremozdemirra/csrd-scope -->

**Is this undertaking in scope of the EU Corporate Sustainability Reporting Directive (CSRD), and from which financial year? A rules engine, as a command line tool and an MCP server, that cites the article behind every step.**

## Why it exists

The scope rules changed three times in three years:

- Directive (EU) 2022/2464 (the CSRD, December 2022) phased reporting in from financial year 2024 (FY2024).
- Directive (EU) 2025/794 ("stop-the-clock", in force 17 April 2025) moved the second and third sets of undertakings to FY2027 and FY2028.
- Directive (EU) 2026/470 (the Omnibus I content amendment, OJ L 2026/470 of 26.2.2026, in force 18 March 2026) replaced the scope with
  two cumulative tests, net turnover above EUR 450 000 000 and more than 1 000 employees on average, removed listed SMEs,
  limited the first set to FY2024-FY2026, and lets Member States exempt members of that set that do not exceed the new
  thresholds for FY2025-FY2026. Member States have until 19 March 2027 to transpose its reporting and audit articles
  (Articles 1 to 3; the due-diligence article by 26 July 2028).

Several answers depend on national law. The Commission's own interpretative Notice (C/2024/6792, FAQ 1-3) says that the
year that decides the size category, the two-consecutive-years rule and the way employees are averaged follow the national
measures, and that "Union legislation does not regulate the calculation of the average number of employees".

Scope answers are published today as consultancy guidance and web scope checkers, for example csrd-tools.com: "Find out
whether the CSRD still applies to you after the Omnibus, in a few clicks, with your first-report year" (checked 2026-09-24).
csrd-scope gives its answer as a chain of rules, each with the provision it applies and that provision's text, answers
"depends" with the question to put to counsel where national law or judgement decides, and runs offline.

## Example

Three **fictional** undertakings. Real output of `csrd-scope 0.1.0` on 2026-09-24.

A German GmbH, not listed, not designated a public-interest entity, above both new thresholds
(`examples/fictional-eu-manufacturer.json`):

```json
{
  "name": "Nordhafen Maschinenbau GmbH (fictional)",
  "currency": "EUR",
  "eu_undertaking": true,
  "member_state": "DE",
  "legal_form_in_annex_i_or_ii": true,
  "designated_pie": false,
  "financial_years": [
    {
      "year": 2025,
      "net_turnover_eur": 505000000,
      "average_employees": 1320,
      "balance_sheet_total_eur": 410000000
    },
    {
      "year": 2026,
      "net_turnover_eur": 520000000,
      "average_employees": 1450,
      "balance_sheet_total_eur": 430000000
    }
  ]
}
```

```
$ csrd-scope check --input examples/fictional-eu-manufacturer.json
Nordhafen Maschinenbau GmbH (fictional)
By financial year: FY2024-FY2026: no; FY2027-FY2028: yes. First reporting financial year: FY2027 (starts 2027-01-01).

Financial year  Starts      In scope  Figures
FY2024          2024-01-01  no        not supplied
FY2025          2025-01-01  no        supplied
FY2026          2026-01-01  no        supplied
FY2027          2027-01-01  yes       projected from FY2026 (assume_latest_figures_continue)
FY2028          2028-01-01  yes       projected from FY2026 (assume_latest_figures_continue)

Rules applied:
 1. Governed by the law of an EU Member State: Directive 2013/34/EU applies to the types of undertaking in Annexes I and II, and Art. 1(3) adds credit institutions and insurance undertakings of any legal form.  [AD-1-1, AD-1-3]
    - legal form covered
 2. Public-interest entity (Art. 2(1)): securities on an EU regulated market, credit institution, insurance undertaking, or designated by the Member State. Matters only for financial years starting in 2024-2026.  [AD-2-1]
    - no
 3. individual sustainability reporting (Art. 19a Directive 2013/34/EU)  [AD-19a-1, AD-2-1, AD-3-10, AD-3-4, CSRD-5-2-a, CSRD-5-2-b]
    - FY2024: no - Not in the set reporting for financial years starting in 2024-2026 (Art. 5(2) first subparagraph point (a)(i) Directive (EU) 2022/2464): not a public-interest entity (Art. 2(1)).
    - FY2025: no - Not in the set reporting for financial years starting in 2024-2026 (Art. 5(2) first subparagraph point (a)(i) Directive (EU) 2022/2464): not a public-interest entity (Art. 2(1)).
    - FY2026: no - Not in the set reporting for financial years starting in 2024-2026 (Art. 5(2) first subparagraph point (a)(i) Directive (EU) 2022/2464): not a public-interest entity (Art. 2(1)).
    - FY2027: yes - net turnover EUR 520 000 000 (threshold EUR 450 000 000), average employees 1 450 (threshold 1 000): both exceeded (Art. 19a(1); applies from financial years starting on or after 1 January 2027, Art. 5(2) first subparagraph point (b)(i)).
    - FY2028: yes - net turnover EUR 520 000 000 (threshold EUR 450 000 000), average employees 1 450 (threshold 1 000): both exceeded (Art. 19a(1); applies from financial years starting on or after 1 January 2027, Art. 5(2) first subparagraph point (b)(i)).

Questions for counsel:
 - Which national provisions transpose Articles 1 to 3 of Directive (EU) 2026/470 (deadline 19 March 2027) and Directive (EU) 2025/794 (deadline 31 December 2025) for this undertaking, and from which financial year do they apply?  [OMNI-5-1, STC-3]
 - Is the average number of employees computed as national law requires (full-time equivalents or headcount, part-time and temporary staff)? Union law does not regulate the calculation.  [NOTICE-FAQ3, OMNI-rec-7]
Note: Figures for FY2027 to FY2028 repeat the FY2026 figures (assume_latest_figures_continue=true); other figures can give another answer.

National measures notified for Germany (EUR-Lex/CELLAR, as of 2026-09-24):
 - 32022L2464: 0 measure(s), latest notified -
 - 32025L0794: 0 measure(s), latest notified -
 - 32026L0470: 0 measure(s), latest notified -
   EUR-Lex (CELLAR) lists the national measures a Member State notified to the Commission. A listed measure does not show that transposition is complete or correct, and an empty list does not show that none exists: check national law.

Legal basis: 02013L0034-20260318, 02022L2464-20260318, 32026L0470, 32025L0794, 32023L2775; checked 2026-09-24. EUR-Lex, on its consolidated texts: "This text is meant purely as a documentation tool and has no legal effect."
Source: EUR-Lex / CELLAR (Publications Office of the European Union), © European Union. Reuse: EUR-Lex legal notice (https://eur-lex.europa.eu/content/legal-notice/legal-notice.html): Official Journal texts may be re-used for commercial or non-commercial purposes (Commission Decision 2011/833/EU, Arts 4 and 6); consolidated texts are licensed CC BY 4.0. Legal texts 32013L0034 (consolidated 02013L0034-20260318), 32022L2464 (consolidated 02022L2464-20260318), 32026L0470, 32025L0794, 32023L2775, 32004L0109, 32019R2088, 52024XC06792; retrieved 2026-09-24. Derived: csrd-scope's encoding of the provisions cited, not the text itself.
Not legal advice. The answer is at EU-directive level; the obligation applies through the national law of the Member State concerned. Not covered: the content of the reports (European Sustainability Reporting Standards, Commission Delegated Regulation (EU) 2023/2772 and later delegated acts under Art. 29b), assurance (Art. 34 Directive 2013/34/EU, Directive 2006/43/EC), due diligence (Directive (EU) 2024/1760, CSDDD), and EU Taxonomy disclosures (Art. 8 Regulation (EU) 2020/852, Delegated Regulation (EU) 2021/2178).
```

A listed Dutch NV in the first set, below the new thresholds (excerpt of `csrd-scope check --input examples/fictional-listed-wave1.json`).
FY2027 is open because Directive (EU) 2026/470 need only be in national law by 19 March 2027, after that financial year starts:

```
Brightwater Components NV (fictional)
By financial year: FY2024: yes; FY2025-FY2027: depends; FY2028: no. First reporting financial year: FY2024 (starts 2024-01-01).

Financial year  Starts      In scope  Figures
FY2024          2024-01-01  yes       supplied
FY2025          2025-01-01  depends   supplied
FY2026          2026-01-01  depends   projected from FY2025 (assume_latest_figures_continue)
FY2027          2027-01-01  depends   projected from FY2025 (assume_latest_figures_continue)
FY2028          2028-01-01  no        projected from FY2025 (assume_latest_figures_continue)
...
    - FY2025: depends - In the 2024-2026 set (public-interest entity: yes; large undertaking (Art. 3(4)): yes; average employees 845 > 500: yes); the Member State may exempt it for FY2025 (Art. 5(2) fifth subparagraph): check national law.
    - FY2027: depends - net turnover EUR 322 000 000 (threshold EUR 450 000 000), average employees 845 (threshold 1 000): not both exceeded. It is a large undertaking (Art. 3(4)) under the text before Directive (EU) 2026/470, which national law may still apply to a financial year starting before the transposition deadline of 19 March 2027.
    - FY2028: no - net turnover EUR 322 000 000 (threshold EUR 450 000 000), average employees 845 (threshold 1 000): not both exceeded.
...
 - Has the Member State used the option to exempt undertakings or issuers from reporting for the financial years starting in 2025 and 2026, and does it reach this one? The text ('do not exceed a net turnover of EUR 450 000 000 or an average number of 1 000 employees') can be read as 'below at least one threshold' (recital 31: those outside the new scope) or as 'below both'.  [CSRD-5-2-derogation, OMNI-rec-31]
 - Articles 1 to 3 of Directive (EU) 2026/470 must be in national law by 19 March 2027, after this financial year starts. Under the earlier text (Art. 5(2)(b) Directive (EU) 2022/2464 as amended by Directive (EU) 2025/794), large undertakings, parents of large groups and issuers of that size report from financial years starting on or after 1 January 2027. Which text does national law apply to this financial year?  [CSRD2025-5-2-b, CSRD2025-5-2-sub3-b, OMNI-5-1]
```

A US group without EU listing, with an EU subsidiary (excerpt of `csrd-scope check --input examples/fictional-non-eu-group.json`):

```
Cascade Robotics Inc. (fictional)
By financial year: FY2024-FY2027: no; FY2028: yes. First reporting financial year: FY2028 (starts 2028-01-01).

Financial year  Starts      In scope  Figures
FY2024          2024-01-01  no        not supplied
FY2025          2025-01-01  no        not supplied
FY2026          2026-01-01  no        supplied
FY2027          2027-01-01  no        supplied
FY2028          2028-01-01  yes       projected from FY2027 (assume_latest_figures_continue)
...
    - FY2028: yes - EU net turnover of the third-country undertaking (FY2026 EUR 480 000 000, FY2027 EUR 515 000 000, FY2028 EUR 515 000 000) must exceed EUR 450 000 000 in each of the last two consecutive financial years; EU subsidiaries above EUR 200 000 000 in FY2027: Cascade Robotics GmbH; EU branches above it: none.
...
 - Is any EU subsidiary itself above the Art. 19a(1) or Art. 29a(1) thresholds? An Art. 40a report does not exempt it; until 6 January 2030 one EU subsidiary may report for all of them (Art. 48i). Assess each one separately with eu_undertaking=true.  [NOTICE-FAQ48, AD-48i-1]
```

`--json` gives the same answer as one object: `in_scope` (for the latest financial year assessed, named in
`in_scope_applies_to`), `first_reporting_financial_year` (with where the report is published), `by_financial_year`,
`rules_applied`, `questions_for_counsel`, `facts_needed`, `national_law`, `legal_basis_version`, `provisions` (the quoted
text of every provision cited), `what_this_is_not` and `attribution`.

## Install

```bash
uvx csrd-scope check --input undertaking.json      # or: pipx run csrd-scope check --input undertaking.json
uvx csrd-scope thresholds
claude mcp add csrd-scope -- uvx --from csrd-scope csrd-scope-mcp
```

Python 3.9 or later, standard library only. The quoted provisions it needs ship inside the package.

## Commands and MCP tools

| CLI | MCP tool | Returns |
| --- | --- | --- |
| `csrd-scope check --input FILE` (or flags, below) | `csrd_scope` | yes / no / depends, first reporting financial year, one result per financial year from FY2024, rules applied with citations, questions for counsel, facts needed, legal-basis version |
| `csrd-scope thresholds` | `thresholds` | the thresholds in force, with articles and quoted text |
| `csrd-scope timeline` | `timeline` | who reports for which financial year, how the dates changed, transposition deadlines |
| `csrd-scope sources [--member-state DE]` | `sources` | acts, CELEX numbers, consolidated versions, amendments and corrigenda since 2024, licence; for a Member State its notified national measures and the legal forms of Annexes I and II |
| `csrd-scope verify-sources` | | compares live CELLAR metadata with the bundled snapshot: exit 0 unchanged, 1 changed (rules need review), 2 could not check |
| `csrd-scope refresh [--out DIR]` | | rebuilds `data/` from CELLAR |

Add `--json` to any command for machine-readable output. Flags instead of a file:
`csrd-scope check --eu --legal-form yes --member-state FR --fy 2026,net_turnover_eur=480000000,average_employees=1200 --fy 2027,net_turnover_eur=480000000,average_employees=1200`;
third-country groups: `--non-eu --fy 2027,eu_net_turnover_eur=600000000 --eu-subsidiary "2027:Beta GmbH=300000000"`.

### Input

| Field | Meaning |
| --- | --- |
| `currency` | Required, must be `"EUR"`. Amounts are never converted: state the EUR figures. |
| `eu_undertaking` | Required. `true` if governed by the law of an EU Member State. |
| `financial_years` | Required. One object per financial year: `year` (the calendar year in which it starts), `net_turnover_eur`, `average_employees`, `balance_sheet_total_eur`; parents add `group_net_turnover_eur`, `group_average_employees`, `group_balance_sheet_total_eur`; third-country undertakings give `eu_net_turnover_eur`, `eu_subsidiaries` and `eu_branches` (lists of `{name, net_turnover_eur}`). Give the year before the first year of interest too: Art. 3(10) compares two years. |
| `legal_form_in_annex_i_or_ii` | EU undertakings: `true`, `false` or `null`. `csrd-scope sources --member-state XX` lists the forms. |
| `entity_type` | `other` (default), `credit_institution`, `insurance_undertaking` (any legal form, Art. 1(3)), `aif_or_ucits` (excluded, Art. 1(4)). |
| `listed_on_eu_regulated_market`, `only_debt_securities_min_denomination_eur_100000`, `designated_pie`, `parent_undertaking`, `financial_holding_undertaking`, `covered_by_parent_consolidated_sustainability_report`, `member_state_exemption_2025_2026` | The facts the scope rules turn on. `designated_pie`, the debt-only flag and the Member State's 2025-2026 option default to unknown, which gives "depends" where they matter. |
| `member_state`, `financial_year_starts_on` (`MM-DD`), `assume_latest_figures_continue` (default `true`: later years repeat the latest figures, and the output says so), `name` | Optional. |

Unknown fields, numbers given as strings, negative or non-finite numbers, and currencies other than EUR are refused with a message.

## How it decides

| Financial years | Rule | Provisions |
| --- | --- | --- |
| starting 2024-2026 | public-interest entity, large undertaking (two of: balance sheet EUR 25 000 000, net turnover EUR 50 000 000, 250 employees) and more than 500 employees; or a PIE parent of a large group with more than 500 employees (consolidated); issuers on the same size tests. Where the size category changes between two years, Art. 3(10)'s two-year rule and the year's own figures can differ: "depends" | Art. 5(2) first and third subpara. point (a) Dir. (EU) 2022/2464; Arts. 2(1), 3(4), 3(7), 3(10) Dir. 2013/34/EU; Del. Dir. (EU) 2023/2775 |
| starting 2025-2026 | Member States may exempt undertakings or issuers that "do not exceed" EUR 450 000 000 or 1 000 employees: "depends" unless `member_state_exemption_2025_2026` is given (the option reads either as "below at least one threshold" or "below both") | Art. 5(2) fifth subpara. Dir. (EU) 2022/2464 |
| starting on or after 1 January 2027 | net turnover > EUR 450 000 000 **and** more than 1 000 employees (individual), or the same on a consolidated basis for parents; credit institutions and insurers in any legal form; AIFs and UCITS excluded. A financial year starting before 19 March 2027 is "depends" for large undertakings below these tests, because national law may still apply the earlier text | Arts. 1(3), 1(4), 19a(1), 29a(1) Dir. 2013/34/EU; Art. 5(2) point (b) Dir. (EU) 2022/2464, before and after Dir. (EU) 2026/470 |
| starting on or after 1 January 2028 | third-country undertaking with EU net turnover > EUR 450 000 000 in each of the last two consecutive years (which two years is open where it matters), through an EU subsidiary above EUR 200 000 000, or an EU branch above EUR 200 000 000 where there is no "subsidiary undertaking as referred to in the first subparagraph" (any EU subsidiary, or only one above EUR 200 000 000: open where it matters) | Art. 40a(1) Dir. 2013/34/EU; Art. 5(2) second subpara. Dir. (EU) 2022/2464 |
| any | subsidiary exemption, financial-holding option, issuers of large-denomination debt only | Arts. 19a(9)-(10), 29a(7a)-(9), 40a(1) last subpara.; Art. 8(1)(b) Dir. 2004/109/EC |

"Depends" means one of: a Member State option or national transposition decides; a provision needs legal judgement
(for example Art. 40 against Art. 3(4), or the two readings of "the last two consecutive financial years"); or a fact is
missing. The output names which, and lists the question or the fact. Financial years are named by the calendar year in
which they start (FY2027 starts in 2027).

## Legal basis (verified 2026-09-24 against CELLAR)

| Act | CELEX | Version used |
| --- | --- | --- |
| Directive 2013/34/EU (Accounting Directive) | 32013L0034 | consolidated 02013L0034-20260318 |
| Directive (EU) 2022/2464 (CSRD) | 32022L2464 | consolidated 02022L2464-20260318; for the FY2027 transition also 02022L2464-20250417 |
| Directive (EU) 2026/470 (Omnibus I content amendment), OJ L 2026/470, 26.2.2026 | 32026L0470 | OJ text; in force 18 March 2026; Articles 1-3 transposed by 19 March 2027, Article 4 by 26 July 2028 |
| Directive (EU) 2025/794 (stop-the-clock), OJ L 2025/794, 16.4.2025 | 32025L0794 | OJ text; in force 17 April 2025; transposition by 31 December 2025 |
| Commission Delegated Directive (EU) 2023/2775 (size criteria) | 32023L2775 | OJ text; financial years from 1 January 2024 |
| Directive 2004/109/EC (Transparency Directive) | 32004L0109 | consolidated 02004L0109-20240109 |
| Regulation (EU) 2019/2088, Art. 2(12) | 32019R2088 | consolidated 02019R2088-20260702 |
| Commission Notice C/2024/6792 (interpretation, not binding, predates 2026/470) | 52024XC06792 | OJ text |

CELLAR also lists a consolidated version dated in the future, 02013L0034-20270130; compared with the version used, it
differs only in its list of amending acts. Consolidated texts can lag behind later acts, so every act relied on was
checked for amendments, corrigenda and consolidations since 2024: no amendment after 18 March 2026 and no corrigendum to
the English text (the corrigenda found concern other language versions). `data/SOURCES.md` has the table, the
SHA-256 of every document quoted and the queries; `csrd-scope verify-sources` repeats the check.

National transposition: the answer is at EU-directive level. For a Member State, csrd-scope lists the national measures
it notified for Directives 2022/2464, 2025/794 and 2026/470 as recorded in EUR-Lex (CELLAR) on 2026-09-24. A notified
measure does not show that transposition is complete or correct, and csrd-scope does not claim either: check national law.

## Data source, licence and attribution

- Source: CELLAR, the Publications Office repository behind EUR-Lex (SPARQL endpoint
  `https://publications.europa.eu/webapi/rdf/sparql` and `https://publications.europa.eu/resource/celex/<CELEX>`).
- Reuse of the acts as published in the Official Journal: the EUR-Lex legal notice
  (https://eur-lex.europa.eu/content/legal-notice/legal-notice.html, read 2026-09-24 from its archived copy of
  2026-09-22): "Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial or
  non-commercial purposes." The policy rests on Commission Decision 2011/833/EU, Article 4 ("All documents shall be
  available for reuse: (a) for commercial or non-commercial purposes under the conditions laid down in Article 6"),
  whose Article 6(2) conditions are to acknowledge the source and not to distort the original meaning or message.
- Reuse of the consolidated texts: the same notice licenses "the editorial content of this website, the summaries of
  EU legislation and the consolidated texts" under CC BY 4.0: "you can re-use the content provided you acknowledge
  the source and indicate any changes you have made." The quotations and dates are in `data/SOURCES.md`.
- Every answer carries the attribution line, and says "derived": the rules are csrd-scope's encoding of the provisions.
- Bundled in `data/`: identifiers, dates, titles, short quotations of the provisions the rules encode, the legal forms
  of Annexes I and II, the EU-27 list (EU Vocabularies country table) and national-measure metadata. No personal data.
- The code is MIT-licensed; the bundled legal material remains © European Union, reused under the EUR-Lex legal
  notice (Official Journal texts) and CC BY 4.0 (consolidated texts).

## What it reads, what it sends

- `check`, `thresholds`, `timeline`, `sources` and the MCP server read only the bundled snapshot. They send nothing.
- `refresh` and `verify-sources` send the fixed SPARQL queries and CELEX identifiers in `csrd_scope_cellar.py` to
  publications.europa.eu. Nothing you type is sent anywhere.
- Names you give are echoed back only after credential-like strings are masked and the text is bounded; national
  measure titles (third-party text) are bounded and marked as remote text.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Offline: the Directive's logic as a table of cases, each naming the provision it tests (thresholds exactly at the limit,
the two-consecutive-years rule, listed SMEs, credit institutions, insurers, funds, financial holding undertakings,
subsidiaries, third-country groups and issuers), strict input validation, the MCP protocol over stdio, and CELLAR
failures (network down, 404, 429, timeouts, broken connections, empty, `null`, non-UTF-8 and malformed answers) from
recorded, trimmed real responses.

## What this is not

Not legal advice. csrd-scope applies the EU directives as consolidated on 18 March 2026; the obligation itself applies
through national law, which may differ in timing, thresholds in national currency, options taken and definitions such
as the average number of employees. It does not cover the content of the report (European Sustainability Reporting
Standards: Commission Delegated Regulation (EU) 2023/2772 and later delegated acts under Art. 29b), assurance (Art. 34
of Directive 2013/34/EU, Directive 2006/43/EC), corporate sustainability due diligence (Directive (EU) 2024/1760, CSDDD),
or EU Taxonomy disclosures (Art. 8 of Regulation (EU) 2020/852 and Delegated Regulation (EU) 2021/2178).
