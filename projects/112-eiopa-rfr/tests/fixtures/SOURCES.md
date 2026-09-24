# Test fixtures: where they come from

Every fixture is a trimmed copy of a file served by EIOPA's website on
2026-09-24. Cell values, links, titles and dates are copied verbatim; only
rows, columns, sheets and page sections were left out. `tests/build_fixtures.py`
rebuilds them byte for byte from the raw files:

```
python3 tests/build_fixtures.py --release-2026-08 EIOPA_RFR_20260831.zip \
    --release-2026-07 EIOPA_RFR_20260731.zip --release-2022-12 "December 2022.zip" \
    --page rfr_page.html --archive-page previous_releases.html --rss rss_en.xml \
    --throttled throttled_429.html --out tests/fixtures
```

## Licence and attribution

Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/

EIOPA legal notice, https://www.eiopa.europa.eu/legal-notice_en (checked 2026-09-24):
"Reproduction of information and documents from the Authority's website is
authorised without prior permission, provided that the user acknowledges the
Authority as the source". Because these copies are trimmed, the notice's
disclaimer for transformed material applies: this material has been drafted
using material downloaded from EIOPA website. EIOPA does not endorse this
publication and in no way is liable for copyright or other intellectual
property rights infringements nor for any damages caused to third-parties
through this publication.

The files contain no personal data: curve identifiers, country names, rates,
curve parameters, file names and publication dates.

## Raw files (retrieved 2026-09-24)

| Raw file | Bytes | SHA-256 | URL |
| --- | ---: | --- | --- |
| EIOPA_RFR_20260831.zip | 3,281,015 | `af7bd7a5228fca507f9995287adb6584caee2e681236321582f823faa81f8569` | https://www.eiopa.europa.eu/document/download/d491908e-9c02-427a-90ec-9dbd7b881ffe_en?filename=EIOPA_RFR_20260831.zip |
| EIOPA_RFR_20260731.zip | 3,279,659 | `a5fd221725cf2e8cc6662fc5813bef4208aeb9fba1890d7657e0b2772a1d7161` | https://www.eiopa.europa.eu/document/download/24c6f1b7-3761-4326-9569-91224f9c9697_en?filename=EIOPA_RFR_20260731.zip |
| December 2022.zip | 4,254,450 | `dc31a2128d983585e529098d6460bcfb4460318719c0b8d0189fb64b7c21e01a` | https://www.eiopa.europa.eu/document/download/5119d7b4-79c0-461e-9169-00d62b6bf730_en?filename=December%202022.zip |
| RFR page (HTML) | 260,895 | `d4f4121ea26a1b37123b1f503a3eb8ed6e3c1a70d467c9d925983611cf685289` | https://www.eiopa.europa.eu/tools-and-data/risk-free-interest-rate-term-structures_en |
| Previous releases page (HTML) | 220,385 | `6cdd97a1cf2f76c9529bf6b9fa98c0e6e0b0a62916662dae6f47124bb58f179c` | https://www.eiopa.europa.eu/tools-and-data/risk-free-interest-rate-term-structures/risk-free-rate-previous-releases-and-preparatory-phase_en |
| RSS feed | 39,894 | `f1f243d0e7731505c6fe53fccdd52278bfcfd545b6b3aafac6033452083691c6` | https://www.eiopa.europa.eu/feed/53/rss_en |
| HTTP 429 page | 40,646 | `5289d3d22ee2a67ad63502192d356a740e35fee942103dc153ebe382ca6515ce` | served with status 429 and `retry-after: 10.000` for https://www.eiopa.europa.eu/document/download/91ae1e97-9c4f-424b-830d-3175caee39e8_en?filename=June%202021.zip after several downloads in a row |

The August 2026 zip downloaded by `eiopa-rfr` during the live check
(2026-09-24T09:43Z) had the same SHA-256 as the copy above.

## Trimmed fixtures

| Fixture | Bytes | SHA-256 | What is kept |
| --- | ---: | --- | --- |
| EIOPA_RFR_20260831.zip | 18,573 | `93241b4b803ed85dfbd7a77614993995ece8623e68fb2a975e4ca67284aa5e9f` | Only `EIOPA_RFR_20260831_Term_Structures.xlsx`, with sheets Main_Menu (10 cells), RFR_spot_no_VA (1,264 cells) and RFR_spot_with_VA (1,271 cells): column B (labels, maturities 1 to 150) and the curves EUR, CZ, DE, CH, UK, CO, US in their original columns and rows |
| EIOPA_RFR_20260731.zip | 18,472 | `7169f21b6135fe11a8a2931ed1b4da4411da91dad669f01f11121a97f7ff956f` | Same selection for July 2026 |
| december_2022.zip | 13,503 | `ac74b82fcab139f295c49b665f5c4de04196519ca538037389fea552e514720b` | `EIOPA_RFR_20221231_Term_Structures.xlsx`: Main_Menu (10 cells), RFR_spot_no_VA (790), RFR_spot_with_VA (794), curves EUR, RU, GB, US (the older layout: "GB", Excel exponent notation, `31-12-2022` in Main_Menu) |
| rfr_page.html | 18,509 | `71f104345566d7bcef57c6e0b15644ed017365719c0d675ec54440de5d09ad89` | Title, the paragraph linking the previous releases page, and file entries from seven sections: 2026 (Aug, Jul), 2023 (Jan 2023, December 2022), IBOR dual run, background material, financial-stability files, the 2019 parallel calculation "December 2019.zip", the 2020 extraordinary update |
| rfr_previous_releases.html | 9,262 | `f859dac2b78993aa0d925a40240464e0d700f83ce2df0eaca6e9a778f6d625fd` | File entries: November, October, September 2022; December 2015, January 2016 (its title and link contain a zero-width space); one background document |
| rss.xml | 2,871 | `7a1082a1ccff6a593d52272cb7314ed46b40ed9c4c2f6442ebf04fbd3ce296f3` | Channel header and seven items: two monthly releases, December 2022 (lower-case file name), a dual run, a PDF, a financial-stability zip, the 15 September 2020 extraordinary update |
| throttled_429.html | 428 | `69ad6c5104dbbe024392e59c438aa0b2f5b6cf71608864a59d3885bcb58f1254` | Title, heading and message of the 429 page |

Styles, drawings, images, printer settings and the other sheets and
workbooks (PD_CoD, Qb_SW, VA_portfolios) are not in the trimmed zips.
