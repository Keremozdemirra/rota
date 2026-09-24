# Test fixtures

`cellar-32025H1710-trimmed.xhtml` and `cellar-32026R1560-trimmed.xhtml` are real CELLAR responses
(English XHTML of Commission Recommendation (EU) 2025/1710 and Commission Delegated Regulation
(EU) 2026/1560, retrieved 2026-09-24), trimmed for size: most numbered paragraphs of the annexes,
the appendices of Annex I and most recitals and articles were removed, and embedded images were
replaced by an empty `data:` URI. Structure, markup and the remaining text are unchanged.
© European Union, CC BY 4.0 (Commission reuse policy, Decision 2011/833/EU).

There are no workbook fixtures on disk: `tests/xlsxgen.py` generates synthetic VSME-like
workbooks at test time, with invented values.
