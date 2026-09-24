"""The README says what the code does: licence page, withheld names, data the tool leaves out."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import ROOT, eu_ets  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")


class Readme(unittest.TestCase):
    def test_licence_page_is_the_one_the_registry_links(self):
        self.assertIn(eu_ets.TERMS_URL, README)
        self.assertEqual(eu_ets.TERMS_URL, "https://european-union.europa.eu/legal-notice_en")
        self.assertIn("identifiable private individuals", README)

    def test_withheld_names_and_their_rule_are_described(self):
        self.assertIn(eu_ets.WITHHELD, README)
        for reason in ("personal identifier", "sole-trader or partnership marker", "holder's name in the installation name",
                       "person-shaped name without site or company words", "no account holder in the registry"):
            self.assertIn(reason, README)

    def test_allocation_the_daily_file_does_not_carry_is_named(self):
        self.assertIn("ALLOCATION_BYICELAND", README)

    def test_mcp_registry_ownership_line(self):
        self.assertIn("<!-- mcp-name: io.github.Keremozdemirra/eu-ets-mcp -->", README)


if __name__ == "__main__":
    unittest.main()
