"""vsme-kit: the EU voluntary sustainability reporting standard for SMEs, as text and as a template check.

Two editions of the standard are bundled, both as published in the Official Journal:

- "2026": Annex I (and the Annex II value chain cap list) of Commission Delegated
  Regulation (EU) 2026/1560, in force since 24 September 2026;
- "2025": Annex I (and the Annex II guidance) of Commission Recommendation (EU) 2025/1710,
  the text that EFRAG's VSME Digital Template up to version 1.3.0 implements.

The template check reads a filled copy of EFRAG's Digital Template (xlsx) with the
standard library only. Nothing is sent anywhere, except by `vsme-kit refresh`, which
downloads the two acts from the Publications Office.
"""

VERSION = "0.1.0"
__version__ = VERSION
