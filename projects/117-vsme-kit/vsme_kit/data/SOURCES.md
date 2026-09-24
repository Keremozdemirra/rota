# Sources of the bundled snapshots

Both files are built by `vsme-kit refresh` (or `python3 vsme-kit.py refresh --out DIR`) from
the Official Journal as served by CELLAR, the Publications Office's repository behind EUR-Lex.
The request is `GET https://publications.europa.eu/resource/celex/<CELEX>` with
`Accept: application/xhtml+xml` and `Accept-Language: eng`; CELLAR answers 303 to the English
XHTML manifestation. The build is deterministic for a given response: same bytes, same JSON
(apart from the retrieval date).

| File | Act | CELEX | Official Journal | Retrieved | Raw XHTML | SHA-256 of the raw XHTML | Content |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `standard-2026.json` | Commission Delegated Regulation (EU) 2026/1560 of 3 July 2026, Annex I (voluntary standard) and Annex II (value chain cap) | 32026R1560 | OJ L, 2026/1560, 21.9.2026, http://data.europa.eu/eli/reg_del/2026/1560/oj | 2026-09-24 | 363,434 bytes, ETag "Con-20260921031243000" | `2a1d369e351eb4eb77779bb8fcff5e786b550bda9e8a9c18f1d87bc2daec3653` | 64 numbered paragraphs of Annex I, 23 value chain cap rows, Article 4 and recital 5 |
| `standard-2025.json` | Commission Recommendation (EU) 2025/1710 of 30 July 2025, Annex I (VSME) and Annex II (guidance) | 32025H1710 | OJ L, 2025/1710, 5.8.2025, http://data.europa.eu/eli/reco/2025/1710/oj | 2026-09-24 | 1,564,229 bytes, ETag "Con-20250805031145000" | `4e5afeb8ac4a510a2f58b141d3f0ff4f6cfa36e67774f75fe792b08009650e48` | 65 numbered paragraphs of Annex I, 180 of Annex II |

Dates, as read from the acts and cross-checked against CELLAR's metadata on 2026-09-24:
Regulation 2026/1560 was published on 21 September 2026 and enters into force "on the third
day following that of its publication" (Article 4), i.e. 24 September 2026; CELLAR lists the
dates of entry into force as 2026-09-24 and 2027-01-01 (Article 3, the value chain cap, applies
"from the financial years beginning on or after 1 January 2027"). Its recital 5 states that from
that date Recommendation (EU) 2025/1710 "should be considered as no longer producing any legal
effects". The Recommendation was published on 5 August 2025.

## Licence

These are acts as published in the Official Journal. They are re-used under the EUR-Lex legal
notice and Commission Decision 2011/833/EU, not under CC BY 4.0.

EUR-Lex legal notice, https://eur-lex.europa.eu/content/legal-notice/legal-notice.html (archived
copy https://web.archive.org/web/20260922160312/https://eur-lex.europa.eu/content/legal-notice/legal-notice.html):
"Unless otherwise specified, you can re-use the legal documents published in EUR-Lex for commercial
or non-commercial purposes." The same notice grants CC BY 4.0 only to "the editorial content of
this website, the summaries of EU legislation and the consolidated texts". Wording as recorded in
the build standards of this project on 2026-09-24 from the archived copy; neither the live page
(an AWS WAF JavaScript challenge, HTTP 202) nor the archive (connection reset, HTTP 429) could be
read from this environment on 2026-09-24.

Commission Decision 2011/833/EU on the reuse of Commission documents, http://data.europa.eu/eli/dec/2011/833/oj,
read from CELLAR (CELEX 32011D0833) on 2026-09-24. Article 2(1)(a): it applies to public documents
produced by the Commission "which have been published by the Commission or by the Publications
Office on its behalf through publications, websites or dissemination tools". Article 4: "All
documents shall be available for reuse: (a) for commercial or non-commercial purposes under the
conditions laid down in Article 6". Article 6(2): those conditions may include "the obligation for
the reuser to acknowledge the source of the documents", "the obligation not to distort the original
meaning or message of the documents" and "the non-liability of the Commission for any consequence
stemming from the reuse".

Neither act's English XHTML carries an individual copyright notice (no "©" or "copyright" in
either text). The Commission's own legal notice (https://commission.europa.eu/legal-notice_en)
covers the content of that website only and is not the basis for these texts. The Publications
Office's copyright notice
(https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright,
read 2026-09-24) refers to the EUR-Lex notice for EUR-Lex content.

## Attribution and changes

Every answer that quotes the text carries:
`Source: <act>, <OJ reference>, <ELI>; © European Union, https://eur-lex.europa.eu; re-used under
the EUR-Lex legal notice and Commission Decision 2011/833/EU (Articles 4 and 6); retrieved
2026-09-24 from CELLAR.` and the changes: text extracted from the English XHTML; whitespace
normalised; tables flattened (cells joined by " | "); footnotes, the appendices of Annex I and the
table of contents left out, while footnote markers such as "(5)" stay in the text; formulas and
figures, which the Official Journal shows as images, replaced by
"[image in the Official Journal, not reproduced]". Words are not changed, so the meaning is not
distorted (Article 6(2)(b)).

No personal data: the acts name no natural persons other than the signatory, and the snapshot
keeps only the annexes, Article 4 and recital 5.
