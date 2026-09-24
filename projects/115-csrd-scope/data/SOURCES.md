# Sources

Everything in `data/` was rebuilt from CELLAR, the Publications Office repository behind EUR-Lex, on 2026-09-24
by `csrd-scope refresh` (standard library only). `csrd-scope verify-sources` compares the live
CELLAR metadata with this snapshot.

## Licence and attribution

- Commission legal notice, https://commission.europa.eu/legal-notice_en (checked 2026-09-24):
  "Unless otherwise indicated (e.g. in individual copyright notices), content owned by the EU on this
  website is licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) licence.
  This means that reuse is allowed, provided appropriate credit is given and changes are indicated."
- Commission Decision 2011/833/EU on the reuse of Commission documents, Article 4: "All documents shall
  be available for reuse: (a) for commercial or non-commercial purposes [...]". The Publications Office
  copyright page refers EUR-Lex content to the EUR-Lex notice and says, for the conditions of reuse of
  CELLAR content, "please contact us at op-copyright@publications.europa.eu".
- The EUR-Lex legal notice (https://eur-lex.europa.eu/content/legal-notice/legal-notice.html) answered
  HTTP 202 with an empty body from the build environment on 2026-09-24 and could not be read.
- Attribution used in every answer: `Source: EUR-Lex / CELLAR (Publications Office of the European Union),
  © European Union. Reuse: Commission Decision 2011/833/EU, Art. 4; Commission content is licensed CC BY 4.0
  [...] Derived: csrd-scope's encoding of the provisions cited, not the text itself.`
- What is bundled: identifiers, dates, titles, short verbatim quotations of the provisions the rules
  encode, the legal-form lists of Annexes I and II, and national-measure metadata. No personal data.

## Endpoints

- SPARQL: https://publications.europa.eu/webapi/rdf/sparql (queries in `csrd_scope_cellar.py`: `Q_ACTS`, `Q_CONSOLIDATED`, `Q_AMENDING`, `Q_AFTER`, `Q_LANGS`, `Q_NIM`, `Q_EU_COUNTRIES`)
- Documents: https://publications.europa.eu/resource/celex/<CELEX> with `Accept: application/xhtml+xml` and `Accept-Language: eng`

## Acts

| CELEX | Date | In force | Title |
| --- | --- | --- | --- |
| 32013L0034 | 2013-06-26 | yes | Directive 2013/34/EU of the European Parliament and of the Council of 26 June 2013 on the annual financial statements, consolidated financial statements and rel |
| 32022L2464 | 2022-12-14 | yes | Directive (EU) 2022/2464 of the European Parliament and of the Council of 14 December 2022 amending Regulation (EU) No 537/2014, Directive 2004/109/EC, Directiv |
| 32025L0794 | 2025-04-14 | yes | Directive (EU) 2025/794 of the European Parliament and of the Council of 14 April 2025 amending Directives (EU) 2022/2464 and (EU) 2024/1760 as regards the date |
| 32026L0470 | 2026-02-24 | yes | Directive (EU) 2026/470 of the European Parliament and of the Council of 24 February 2026 amending Directives 2006/43/EC, 2013/34/EU, (EU) 2022/2464 and (EU) 20 |
| 32023L2775 | 2023-10-17 | yes | Commission Delegated Directive (EU) 2023/2775 of 17 October 2023 amending Directive 2013/34/EU of the European Parliament and of the Council as regards the adju |
| 32004L0109 | 2004-12-15 | yes | Directive 2004/109/EC of the European Parliament and of the Council of 15 December 2004 on the harmonisation of transparency requirements in relation to informa |
| 32019R2088 | 2019-11-27 | yes | Regulation (EU) 2019/2088 of the European Parliament and of the Council of 27 November 2019 on sustainability‐related disclosures in the financial services sect |
| 52024XC06792 | 2024-11-13 |  | Commission Notice on the interpretation of certain legal provisions in Directive 2013/34/EU (Accounting Directive), Directive 2006/43/EC (Audit Directive), Regu |

## Consolidated versions listed by CELLAR

- 32013L0034: 02013L0034-20270130, 02013L0034-20260318 (used), 02013L0034-20240528, 02013L0034-20240109, 02013L0034-20230105, 02013L0034-20211221, 02013L0034-20141211, 02013L0034-20141205, 02013L0034-20130719
- 32004L0109: 02004L0109-20240109 (used), 02004L0109-20230105, 02004L0109-20210318, 02004L0109-20131126, 02004L0109-20110104, 02004L0109-20080320
- 32019R2088: 02019R2088-20260702 (used), 02019R2088-20240109, 02019R2088-20200712
- 32022L2464: 02022L2464-20260318 (used), 02022L2464-20250417, 02022L2464-20221216

## Acts amending 32013L0034 or 32022L2464 dated 2023-01-01 or later

- 32013L0034 <- 32026L0470 (2026-02-24): Directive (EU) 2026/470 of the European Parliament and of the Council of 24 February 2026 amending Directives 2006/43/EC, 2013/34/EU, (EU) 2022/2464 a
- 32013L0034 <- 32025L0002 (2024-11-27): Directive (EU) 2025/2 of the European Parliament and of the Council of 27 November 2024 amending Directive 2009/138/EC as regards proportionality, qua
- 32013L0034 <- 32024L1306 (2024-04-29): Directive (EU) 2024/1306 of the European Parliament and of the Council of 29 April 2024 amending Directive 2013/34/EU as regards the time limits for t
- 32013L0034 <- 32023L2864 (2023-12-13): Directive (EU) 2023/2864 of the European Parliament and of the Council of 13 December 2023 amending certain Directives as regards the establishment an
- 32013L0034 <- 32023L2775 (2023-10-17): Commission Delegated Directive (EU) 2023/2775 of 17 October 2023 amending Directive 2013/34/EU of the European Parliament and of the Council as regard
- 32022L2464 <- 32026L0470 (2026-02-24): Directive (EU) 2026/470 of the European Parliament and of the Council of 24 February 2026 amending Directives 2006/43/EC, 2013/34/EU, (EU) 2022/2464 a
- 32022L2464 <- 32025L0794 (2025-04-14): Directive (EU) 2025/794 of the European Parliament and of the Council of 14 April 2025 amending Directives (EU) 2022/2464 and (EU) 2024/1760 as regard

## Amendments, corrigenda and consolidations since 2024 (every act relied on)

A consolidated text can lag behind acts that amend or correct it, so each act relied on is checked.
Corrigenda that do not correct the English version (ENG) do not change the text this tool quotes.

| Act | Relation | CELEX | Date | Languages corrected |
| --- | --- | --- | --- | --- |
| 32004L0109 | consolidates | 02004L0109-20240109 | 2024-01-09 |  |
| 32013L0034 | amends | 32024L1306 | 2024-04-29 |  |
| 32013L0034 | amends | 32025L0002 | 2024-11-27 |  |
| 32013L0034 | amends | 32026L0470 | 2026-02-24 |  |
| 32013L0034 | consolidates | 02013L0034-20240109 | 2024-01-09 |  |
| 32013L0034 | consolidates | 02013L0034-20240528 | 2024-05-28 |  |
| 32013L0034 | consolidates | 02013L0034-20260318 | 2026-03-18 |  |
| 32013L0034 | consolidates | 02013L0034-20270130 | 2027-01-30 |  |
| 32013L0034 | corrects | 32013L0034R(07) | 2024-07-24 | SPA |
| 32013L0034 | corrects | 32013L0034R(08) | 2025-10-08 | MLT |
| 32019R2088 | amends | 32024R3005 | 2024-11-27 |  |
| 32019R2088 | consolidates | 02019R2088-20240109 | 2024-01-09 |  |
| 32019R2088 | consolidates | 02019R2088-20260702 | 2026-07-02 |  |
| 32022L2464 | amends | 32025L0794 | 2025-04-14 |  |
| 32022L2464 | amends | 32026L0470 | 2026-02-24 |  |
| 32022L2464 | consolidates | 02022L2464-20250417 | 2025-04-17 |  |
| 32022L2464 | consolidates | 02022L2464-20260318 | 2026-03-18 |  |
| 32022L2464 | corrects | 32022L2464R(04) | 2024-08-16 | LIT |
| 32022L2464 | corrects | 32022L2464R(05) | 2024-11-20 | FRA |
| 32022L2464 | corrects | 32022L2464R(06) | 2025-05-07 | DEU |
| 32022L2464 | corrects | 32022L2464R(07) | 2025-09-11 | GLE |
| 32022L2464 | corrects | 32022L2464R(08) | 2025-10-08 | BUL CES DEU ELL EST FIN HRV HUN ITA LAV MLT NLD POL POR RON SLK SPA |
| 32022L2464 | corrects | 32022L2464R(09) | 2026-07-01 | CES |
| 32026L0470 | corrects | 32026L0470R(01) | 2026-04-22 | LIT |

## Verification notes (2026-09-24, by hand, recorded here because they are not re-derived by refresh)

- 02013L0034-20270130 is dated in the future. A text comparison with 02013L0034-20260318 found no difference
  except the list of amending acts, which adds Directive (EU) 2025/2 (32025L0002). Its Article 2 replaces
  Art. 19a(6) of Directive 2013/34/EU from 30 January 2027; Directive (EU) 2026/470 had already deleted that
  paragraph. The rules use 02013L0034-20260318.
- 02019R2088-20260702 (after amending Regulation (EU) 2024/3005): Art. 2(12) is identical to the original text 32019R2088.
- Directive (EU) 2026/470 was published in OJ L 2026/470 on 26.2.2026 and enters into force on the twentieth day
  following publication (Art. 6), i.e. 18 March 2026, the date of the consolidated versions used.
- The Commission Notice C/2024/6792 predates Directive (EU) 2026/470; it is cited only for points the
  amendment did not change (size timing, employee averaging, Article 40a mechanics) and it is not binding.
- No amending act dated after 2026-03-18 is listed for 32013L0034 or 32022L2464, and no corrigendum since 2024
  corrects the English version of any act relied on (table above). `verify-sources` repeats this check.


## Documents quoted

| CELEX | Bytes | SHA-256 | Retrieved |
| --- | --- | --- | --- |
| 02013L0034-20260318 | 758297 | `20710edfbe1a975cd3dd9f6751442fa597546b48e6410c604d9c11f3b271b31d` | 2026-09-24 |
| 02022L2464-20260318 | 295274 | `27e8029ef340028ce8cc5181e635eb32eeb48b97c366d2177d0551923e857440` | 2026-09-24 |
| 32026L0470 | 388853 | `8eb95f167657537d3a285927bce1f086dba0b1a33426f938da0ef48fe40bb966` | 2026-09-24 |
| 32025L0794 | 33961 | `9b1ae0bd3d5313f7b294a3ec5dd771ffd900666673ffb52431ce07969a5055f2` | 2026-09-24 |
| 32023L2775 | 32111 | `145fef26262d9a267c44594ca79b4e564f6c74fe1b435c8102e13a33d2d6cce9` | 2026-09-24 |
| 02013L0034-20230105 | 692064 | `2af0b26d2f8a93f9eb08b4d3b3783e7a5cc89642dfc8b217eec76d6e85d101cf` | 2026-09-24 |
| 02013L0034-20240528 | 712597 | `67e5bf2f66bed5d63350c75fbba1a028e520306df1114b46b42a97ec766da8a9` | 2026-09-24 |
| 02004L0109-20240109 | 270670 | `6f97a4e64fc1c5e901dcc15446ba8d7581af0a520e5cb4af4469049d49354662` | 2026-09-24 |
| 52024XC06792 | 1474894 | `364d7147140c026df914d784da5d2d0904a0e07e4e417b31b72f6ea52e42adf2` | 2026-09-24 |
| 02019R2088-20260702 | 121157 | `5cb7fc10620a38ce3cad0fb96769c794e78f4b4bb8b4ca2d55d3fc9a51ecce20` | 2026-09-24 |
| 02022L2464-20250417 | 296057 | `a2b916a3c6d5d9fab6ebc87b16e2417314b01d24e5a434e453a81d17f7dfb098` | 2026-09-24 |

66 quotations are stored in `legal_basis.json` under `quotes`.

## National measures

`national_measures.json`: 206 national measures notified for 32022L2464, 32025L0794, 32026L0470 (22 Member States with at least one).
A notified measure does not show that transposition is complete or correct; a missing one does not
show that no national measure exists.

## Member States and legal forms

`member_states.json`: 27 Member States (Publications Office, EU Vocabularies, country authority table, use-context EU_COU).
`legal_forms.json`: Annex I and Annex II entries for 27 Member States from 02013L0034-20260318; skipped because not an EU Member State: annex_i: United Kingdom, annex_ii: United Kingdom.
