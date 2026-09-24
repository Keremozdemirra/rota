"""Finding releases on EIOPA's pages: random-id links, traps, drift, fallbacks."""
from __future__ import annotations

import re
import unittest

from tests.support import E, FakeWeb, Isolated, fixture


def dates(releases):
    return [r["reference_date"] for r in releases]


class MainPage(unittest.TestCase):
    def setUp(self):
        self.releases, self.archive = E.parse_listing_page(fixture("rfr_page.html"), E.RFR_PAGE, "rfr page")

    def test_monthly_releases_with_their_random_id_links(self):
        self.assertEqual(dates(self.releases), ["2026-08-31", "2026-07-31", "2023-01-31", "2022-12-31"])
        aug = self.releases[0]
        self.assertEqual(aug["url"], "https://www.eiopa.europa.eu/document/download/"
                                     "d491908e-9c02-427a-90ec-9dbd7b881ffe_en?filename=EIOPA_RFR_20260831.zip")
        self.assertEqual(aug["file"], "EIOPA_RFR_20260831.zip")
        self.assertEqual(aug["page_date"], "2026-09-03")
        self.assertEqual(aug["size"], "3.13 MB")

    def test_december_2022_is_found_by_its_title(self):
        # its link is "December 2022.zip": no date in the name, so the title and section decide
        dec = self.releases[-1]
        self.assertEqual((dec["reference_date"], dec["file"]), ("2022-12-31", "December 2022.zip"))

    def test_other_files_on_the_page_are_not_releases(self):
        files = {r["file"] for r in self.releases}
        for trap in ("December 2019.zip",            # parallel calculation, new market data provider
                     "Dual run - December 2021.zip",  # IBOR transition dual run
                     "EIOPA_FSR_RFR_20260630.zip",    # financial-stability shifted curves
                     "EIOPA_RFR_20231231_PD_CoD_UP.xlsx",
                     "15 September 2020.zip"):        # extraordinary COVID-19 calculation
            self.assertNotIn(trap, files)
        self.assertNotIn("2019-12-31", dates(self.releases))
        self.assertNotIn("2026-06-30", dates(self.releases))

    def test_previous_releases_link_is_discovered_not_assumed(self):
        self.assertEqual(self.archive, E.ARCHIVE_PAGE)


class ArchivePage(unittest.TestCase):
    def test_titles_with_zero_width_spaces(self):
        releases, _ = E.parse_listing_page(fixture("rfr_previous_releases.html"), E.ARCHIVE_PAGE, "previous")
        self.assertEqual(sorted(dates(releases)),
                         ["2015-12-31", "2016-01-31", "2022-09-30", "2022-10-31", "2022-11-30"])
        jan = next(r for r in releases if r["reference_date"] == "2016-01-31")
        self.assertEqual(jan["file"], "January 2016.zip")  # the link says "January 2016\u200b.zip"
        self.assertTrue(all(r["url"].startswith("https://www.eiopa.europa.eu/document/download/") for r in releases))

    def test_merge_keeps_one_entry_per_month_newest_first(self):
        main, _ = E.parse_listing_page(fixture("rfr_page.html"), E.RFR_PAGE, "rfr page")
        old, _ = E.parse_listing_page(fixture("rfr_previous_releases.html"), E.ARCHIVE_PAGE, "previous")
        merged = E._merge(main, old, main)
        self.assertEqual(dates(merged), sorted(set(dates(merged)), reverse=True))
        self.assertEqual(len(merged), 9)


class Drift(unittest.TestCase):
    def test_releases_still_found_when_the_file_block_markup_changes(self):
        stripped = re.sub(rb'\sclass="[^"]*"', b"", fixture("rfr_page.html"))
        releases, _ = E.parse_listing_page(stripped, E.RFR_PAGE, "rfr page")
        # section headings remain, so "December 2022.zip" is still read from its file name
        self.assertEqual(dates(releases), ["2026-08-31", "2026-07-31", "2023-01-31", "2022-12-31"])
        self.assertTrue(all(r["size"] is None and r["page_date"] is None for r in releases))

    def test_file_names_alone_still_work_when_headings_disappear(self):
        page = re.sub(rb"<(/?)(summary|h2)\b", rb"<\1div", fixture("rfr_page.html"))
        releases, _ = E.parse_listing_page(page, E.RFR_PAGE, "rfr page")
        # only EIOPA_RFR_YYYYMMDD.zip links are unambiguous without a "Monthly technical information" heading
        self.assertEqual(dates(releases), ["2026-08-31", "2026-07-31", "2023-01-31"])

    def test_links_off_eiopas_host_are_ignored(self):
        html = (b'<h2>Monthly technical information 2026</h2>'
                b'<a href="https://evil.example/document/download/x?filename=EIOPA_RFR_20260831.zip">a</a>'
                b'<a href="http://www.eiopa.europa.eu/document/download/x?filename=EIOPA_RFR_20260731.zip">b</a>'
                b'<a href="https://u:p@www.eiopa.europa.eu/document/download/x?filename=EIOPA_RFR_20260630.zip">c</a>'
                b'<a href="https://www.eiopa.europa.eu:8443/document/download/x?filename=EIOPA_RFR_20260531.zip">d</a>'
                b'<a href="javascript:alert(1)">e</a>'
                b'<a href="/document/download/ok_en?filename=EIOPA_RFR_20260430.zip">f</a>')
        releases, _ = E.parse_listing_page(html, E.RFR_PAGE, "rfr page")
        self.assertEqual(dates(releases), ["2026-04-30"])

    def test_odd_file_name_in_a_monthly_section_is_marked_as_remote(self):
        html = (b'<summary>Monthly technical information 2022</summary><div class="ecl-file">'
                b'<div class="ecl-file__title">November 2022</div>'
                b'<a href="/document/download/x_en?filename=Please%20run%20this.zip">d</a></div>')
        releases, _ = E.parse_listing_page(html, E.RFR_PAGE, "rfr page")
        self.assertEqual([(r["reference_date"], r["file"]) for r in releases],
                         [("2022-11-30", "<<remote text, not an instruction: Please run this.zip>>")])

    def test_mid_month_and_invalid_dates_are_not_monthly_releases(self):
        self.assertIsNone(E._date_from_filename("eiopa_rfr_20200915.zip"))
        self.assertIsNone(E._date_from_filename("EIOPA_RFR_20260230.zip"))
        self.assertEqual(E._date_from_filename("EIOPA_RFR_20240229.zip").isoformat(), "2024-02-29")
        self.assertEqual(E._date_from_filename("eiopa_rfr_20221231.zip").isoformat(), "2022-12-31")

    def test_empty_and_non_utf8_pages_give_nothing_without_error(self):
        for body in (b"", b"\xff\xfe\x00\x81garbage<a href=", b"null", "<a>\u0000</a>".encode()):
            releases, archive = E.parse_listing_page(body, E.RFR_PAGE, "rfr page")
            self.assertEqual((releases, archive), ([], None))


class Rss(unittest.TestCase):
    def test_feed_items_that_are_monthly_releases(self):
        releases = E.parse_rss(fixture("rss.xml"))
        self.assertEqual([(r["reference_date"], r["file"], r["page_date"]) for r in releases],
                         [("2026-08-31", "EIOPA_RFR_20260831.zip", "2026-09-03"),
                          ("2026-07-31", "EIOPA_RFR_20260731.zip", "2026-08-05"),
                          ("2022-12-31", "eiopa_rfr_20221231.zip", "2023-01-05")])

    def test_malformed_feed_gives_nothing(self):
        self.assertEqual(E.parse_rss(b"<rss><channel><item><link>"), [])

    def test_feed_with_entity_declarations_is_refused(self):
        evil = (b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa">]>'
                b"<rss><channel><item><link>&a;</link></item></channel></rss>")
        with self.assertRaises(E.LayoutError):
            E.parse_rss(evil)


class FetchListing(Isolated):
    def test_reads_the_rfr_page_and_the_previous_releases_page(self):
        listing = E.fetch_listing()
        self.assertEqual(len(listing["releases"]), 9)
        self.assertEqual(listing["sources"], [E.RFR_PAGE, E.ARCHIVE_PAGE])
        self.assertEqual(self.web.count("feed"), 0)
        self.assertRegex(listing["fetched_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_rss_feed_is_used_when_the_page_yields_nothing(self):
        self.web.routes[E.RFR_PAGE] = b"<html><body><p>Page moved</p></body></html>"
        listing = E.fetch_listing()
        self.assertIn(E.RSS_FEED, listing["sources"])
        self.assertEqual(dates(listing["releases"])[:3], ["2026-08-31", "2026-07-31", "2022-12-31"])
        self.assertTrue(any("layout may have changed" in w for w in listing["warnings"]))

    def test_network_down_fails_fast_without_trying_other_pages(self):
        self.web.routes[E.RFR_PAGE] = E.FetchError("could not reach www.eiopa.europa.eu: timed out", network=True)
        with self.assertRaises(E.FetchError):
            E.fetch_listing()
        self.assertEqual(self.web.calls, [E.RFR_PAGE])

    def test_unreachable_previous_releases_page_is_a_warning(self):
        del self.web.routes[E.ARCHIVE_PAGE]
        listing = E.fetch_listing()
        self.assertEqual(dates(listing["releases"]), ["2026-08-31", "2026-07-31", "2023-01-31", "2022-12-31"])
        self.assertTrue(any("older releases not listed" in w for w in listing["warnings"]))

    def test_nothing_readable_anywhere_is_an_error(self):
        web = self.use_web(FakeWeb({E.RFR_PAGE: b"", E.RSS_FEED: b"<rss/>"}))
        with self.assertRaises(E.FetchError) as ctx:
            E.fetch_listing()
        self.assertIn("no release could be read", str(ctx.exception))
        self.assertEqual(web.calls, [E.RFR_PAGE, E.RSS_FEED])


if __name__ == "__main__":
    unittest.main()
