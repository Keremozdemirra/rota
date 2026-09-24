"""The five tools against the fake EIOPA website: dates, currencies, cache, offline, failures."""
from __future__ import annotations

import datetime as dt
import json
from unittest import mock

from tests.support import REAL_HTTP_GET, E, FakeWeb, Isolated, fixture, listing_urls

class GetRate(Isolated):
    def test_eur_ten_years_with_and_without_va(self):
        noon = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)
        with mock.patch.object(E, "_now", return_value=noon):
            r = E.get_rate("EUR", 10, "2026-08")
        self.assertEqual(r["reference_date"], "2026-08-31")
        self.assertEqual((r["no_va"]["rate"], r["no_va"]["rate_percent"], r["no_va"]["cell"]),
                         (0.03268, 3.268, "RFR_spot_no_VA!C20"))
        self.assertEqual((r["with_va"]["rate"], r["with_va"]["rate_percent"], r["with_va"]["cell"]),
                         (0.03408, 3.408, "RFR_spot_with_VA!C20"))
        self.assertFalse(r["no_va"]["beyond_last_liquid_point"])
        self.assertEqual(r["with_va"]["parameters"]["va_bp"], 14)
        self.assertEqual(r["curve"], {"code": "EUR", "name": "Euro", "curve_id": "EUR_31_08_2026_SWP_LLP_20_EXT_40_UFR_3.30",
                                      "instrument": "SWP"})
        self.assertIn("resolved to reference date 2026-08-31", r["date"]["note"])
        self.assertEqual(r["attribution"],
                         "Source: EIOPA - European Insurance and Occupational Pensions Authority, https://eiopa.europa.eu/, "
                         "risk-free interest rate term structures, EIOPA_RFR_20260831.zip, retrieved 2026-09-24")
        self.assertIn("d491908e-9c02-427a-90ec-9dbd7b881ffe", r["source"]["url"])
        self.assertEqual(r["source"]["workbook"], "EIOPA_RFR_20260831_Term_Structures.xlsx")
        self.assertRegex(r["source"]["sha256"], r"^[0-9a-f]{64}$")
        json.dumps(r)  # the whole answer is plain JSON

    def test_usd_thirty_years_and_the_last_liquid_point(self):
        r = E.get_rate("USD", 30, "2026-08-31", "no_va")
        self.assertEqual(r["curve"]["code"], "US")
        self.assertEqual(r["no_va"]["cell"], "RFR_spot_no_VA!AQ40")
        self.assertFalse(r["no_va"]["beyond_last_liquid_point"])  # LLP is 30 years
        self.assertNotIn("with_va", r)
        self.assertTrue(E.get_rate("USD", 31, "2026-08", "no_va")["no_va"]["beyond_last_liquid_point"])

    def test_latest_is_the_newest_release_on_the_page(self):
        r = E.get_rate("EUR", 1, "latest", "no_va")
        self.assertEqual(r["reference_date"], "2026-08-31")
        self.assertIn("newest release on EIOPA's pages", r["date"]["note"])
        self.assertEqual(r["no_va"]["rate"], 0.02916)

    def test_date_forms_resolve_to_the_month_end(self):
        notes = {}
        for form in ("2026-08", "2026-8", "2026-08-31", "2026-08-15", "20260831"):
            r = E.get_rate("EUR", 10, form, "no_va")
            self.assertEqual(r["reference_date"], "2026-08-31", form)
            notes[form] = r["date"]["note"]
        self.assertEqual(notes["2026-08-31"], "reference date 2026-08-31 as requested")
        self.assertIn("last calendar day of the month", notes["2026-08-15"])

    def test_download_once_then_answer_from_the_cache(self):
        E.get_rate("EUR", 10, "2026-08")
        E.get_rate("EUR", 20, "2026-08")
        E.get_curve("USD", "2026-08")
        self.assertEqual(self.web.count("EIOPA_RFR_20260831.zip"), 1)
        self.assertEqual(self.web.count(E.RFR_PAGE), 1)
        self.assertTrue((self.cache / "releases" / "rfr_20260831.zip").exists())

    def test_listing_reused_within_six_hours_and_refreshed_after(self):
        E.list_releases()
        E.get_rate("EUR", 10, "latest")
        self.assertEqual(self.web.count(E.RFR_PAGE), 1)
        later = E._now() + dt.timedelta(hours=7)
        with mock.patch.object(E, "_now", return_value=later):
            E.get_rate("EUR", 10, "latest")
        self.assertEqual(self.web.count(E.RFR_PAGE), 2)
        E.list_releases(refresh=True)
        self.assertEqual(self.web.count(E.RFR_PAGE), 3)


class Currencies(Isolated):
    def test_unknown_currency_names_what_is_available(self):
        with self.assertRaises(E.NotFound) as ctx:
            E.get_rate("XYZ", 10, "2026-08")
        message = str(ctx.exception)
        self.assertIn("XYZ is not among the 7 curves of EIOPA_RFR_20260831.zip", message)
        self.assertIn("currencies EUR, CZK, CHF, GBP, COP, USD", message)
        self.assertIn("country columns DE", message)

    def test_currency_that_eiopa_no_longer_publishes(self):
        with self.assertRaises(E.NotFound):
            E.get_rate("RUB", 10, "2026-08")
        self.assertEqual(E.get_rate("RUB", 10, "2022-12", "no_va")["curve"]["code"], "RU")

    def test_united_kingdom_was_gb_and_is_now_uk(self):
        for currency, date, code in (("GBP", "2026-08", "UK"), ("GBP", "2022-12", "GB"), ("GB", "2026-08", "UK"),
                                     ("uk", "2022-12", "GB")):
            self.assertEqual(E.get_rate(currency, 10, date, "no_va")["curve"]["code"], code, (currency, date))

    def test_country_column(self):
        r = E.get_rate("de", 10, "2026-08")
        self.assertEqual((r["curve"]["code"], r["curve"]["name"]), ("DE", "Germany"))
        self.assertEqual(r["no_va"]["cell"], "RFR_spot_no_VA!N20")

    def test_malformed_inputs(self):
        for kwargs in ({"currency": "EURO"}, {"currency": ""}, {"currency": "E1"}, {"maturity_years": 0},
                       {"maturity_years": 10.5}, {"maturity_years": "ten"}, {"maturity_years": True},
                       {"maturity_years": -3}, {"date": "Aug 2026"}, {"date": "2026-13"}, {"date": "2026-02-30"},
                       {"variant": "shock_up"}):
            args = dict({"currency": "EUR", "maturity_years": 10, "date": "2026-08", "variant": "both"}, **kwargs)
            with self.assertRaises(E.NotFound, msg=kwargs):
                E.get_rate(**args)

    def test_maturity_given_as_text_or_whole_float(self):
        self.assertEqual(E.get_rate("EUR", "10", "2026-08")["maturity_years"], 10)
        self.assertEqual(E.get_rate("EUR", 10.0, "2026-08")["maturity_years"], 10)
        with self.assertRaises(E.NotFound):
            E.get_rate("EUR", 151, "2026-08")


class MissingMonth(Isolated):
    def test_month_not_published(self):
        with self.assertRaises(E.NotFound) as ctx:
            E.get_rate("EUR", 10, "2026-09")
        message = str(ctx.exception)
        self.assertIn("no EIOPA release for reference date 2026-09-30", message)
        self.assertIn("from 2015-12-31 to 2026-08-31", message)
        self.assertEqual(self.web.count("EIOPA_RFR_"), 0)

    def test_listed_file_that_is_gone(self):
        with self.assertRaises(E.FetchError) as ctx:
            E.get_rate("EUR", 10, "2023-01")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertFalse((self.cache / "listing.json").exists())  # EIOPA's pages are read again next time


class Curve(Isolated):
    def test_whole_curve_as_published(self):
        r = E.get_curve("EUR", "2026-08", "both")
        rates = r["no_va"]["rates"]
        self.assertEqual(len(rates), 150)
        self.assertEqual(rates[0], {"maturity_years": 1, "rate": 0.02916})
        self.assertEqual(rates[9]["rate"], 0.03268)
        self.assertEqual(rates[149], {"maturity_years": 150, "rate": 0.03338})
        self.assertEqual(r["with_va"]["rates"][9]["rate"], 0.03408)
        self.assertEqual((r["no_va"]["sheet"], r["no_va"]["column"]), ("RFR_spot_no_VA", "C"))
        self.assertIn("does not compute, interpolate or extrapolate", r["note"])

    def test_default_variant_is_without_va(self):
        r = E.get_curve("CHF", "2026-08")
        self.assertIn("no_va", r)
        self.assertNotIn("with_va", r)


class Parameters(Isolated):
    def test_one_currency(self):
        r = E.get_parameters("EUR", "2026-08")
        self.assertEqual(r["no_va"]["alpha"], 0.074103)
        self.assertEqual(r["with_va"]["alpha"], 0.087579)
        self.assertEqual(r["with_va"]["va_bp"], 14)
        self.assertEqual(r["units"]["cra_bp"], "credit risk adjustment, basis points")

    def test_all_curves(self):
        r = E.get_parameters("all", "2026-08")
        self.assertEqual([c["code"] for c in r["curves"]], ["EUR", "CZ", "DE", "CH", "UK", "CO", "US"])
        co = next(c for c in r["curves"] if c["code"] == "CO")
        self.assertEqual(co["with_va"]["va_bp"], "n/a")
        self.assertEqual(co["no_va"]["cra_bp"], 35)


class Compare(Isolated):
    def test_change_from_july_to_august(self):
        r = E.compare("EUR", 10, "2026-07", "2026-08")
        no_va, with_va = r["no_va"], r["with_va"]
        self.assertEqual((no_va["a"]["rate"], no_va["b"]["rate"]), (0.03159, 0.03268))
        self.assertEqual(no_va["change"], {"decimal": 0.00109, "bp": 10.9})  # exact, no 10.899999...
        self.assertEqual((with_va["a"]["rate"], with_va["b"]["rate"]), (0.03289, 0.03408))
        self.assertEqual(with_va["change"], {"decimal": 0.00119, "bp": 11.9})
        self.assertEqual(with_va["parameters_changed"]["va_bp"], {"a": 13, "b": 14})
        self.assertIn("alpha", no_va["parameters_changed"])
        self.assertEqual((r["a"]["reference_date"], r["b"]["reference_date"]), ("2026-07-31", "2026-08-31"))
        self.assertEqual(len(r["attribution"]), 2)
        self.assertIn("EIOPA_RFR_20260731.zip", r["attribution"][0])
        self.assertIn("EIOPA does not endorse this publication", r["disclaimer"])
        self.assertIn("computed by eiopa-rfr from the two published values", r["derived"])

    def test_same_date_twice_is_no_change(self):
        r = E.compare("USD", 30, "2026-08", "2026-08-31", "no_va")
        self.assertEqual(r["no_va"]["change"], {"decimal": 0, "bp": 0})
        self.assertEqual(r["no_va"]["parameters_changed"], {})

    def test_across_the_uk_code_change(self):
        r = E.compare("GBP", 10, "2022-12", "2026-08", "no_va")
        self.assertEqual((r["curve"]["a"]["code"], r["curve"]["b"]["code"]), ("GB", "UK"))


class CacheAndOffline(Isolated):
    def test_offline_answers_from_the_cache_only(self):
        E.get_rate("EUR", 10, "2026-08")
        self.use_web(FakeWeb({}))  # any request would now fail
        self.go_offline()
        self.assertEqual(E.get_rate("EUR", 10, "2026-08")["no_va"]["rate"], 0.03268)
        latest = E.get_rate("EUR", 10, "latest")
        self.assertIn("offline mode", latest["date"]["note"])
        with self.assertRaises(E.FetchError) as ctx:
            E.get_rate("EUR", 10, "2026-07")
        self.assertIn("not in the local cache", str(ctx.exception))
        self.assertEqual(self.web.calls, [])
        self.assertIn("offline mode", " ".join(E.list_releases()["warnings"]))

    def test_offline_with_an_empty_cache(self):
        self.go_offline()
        with self.assertRaises(E.FetchError):
            E.get_rate("EUR", 10, "latest")

    def test_network_down_falls_back_to_the_last_release_list(self):
        E.list_releases()
        E.get_rate("EUR", 10, "2026-08")
        self.use_web(FakeWeb({E.RFR_PAGE: E.FetchError("could not reach www.eiopa.europa.eu: timed out",
                                                       network=True)}))
        later = E._now() + dt.timedelta(days=2)
        with mock.patch.object(E, "_now", return_value=later):
            r = E.get_rate("EUR", 10, "latest")
        self.assertEqual(r["reference_date"], "2026-08-31")
        self.assertTrue(any("could not reach" in w for w in r["warnings"]))

    def test_network_down_and_nothing_cached(self):
        self.use_web(FakeWeb({E.RFR_PAGE: E.FetchError("could not reach www.eiopa.europa.eu: refused",
                                                       network=True)}))
        with self.assertRaises(E.FetchError):
            E.get_rate("EUR", 10, "latest")

    def test_corrupted_download_is_not_cached(self):
        url = listing_urls()["2026-07-31"]
        self.web.routes[url] = fixture("EIOPA_RFR_20260731.zip")[:4000]
        with self.assertRaises(E.LayoutError):
            E.get_rate("EUR", 10, "2026-07")
        self.assertEqual(list((self.cache / "releases").glob("rfr_20260731*")), [])
        self.assertFalse((self.cache / "listing.json").exists())

    def test_a_changed_link_means_eiopa_republished(self):
        E.get_rate("EUR", 10, "2026-08")
        page = fixture("rfr_page.html").replace(b"d491908e-9c02-427a-90ec-9dbd7b881ffe", b"0000aaaa-9c02-427a-90ec-9dbd7b881ffe")
        new_url = listing_urls()["2026-08-31"].replace("d491908e", "0000aaaa")
        self.web.routes[E.RFR_PAGE] = page
        self.web.routes[new_url] = fixture("EIOPA_RFR_20260831.zip")
        E.list_releases(refresh=True)
        r = E.get_rate("EUR", 10, "2026-08")
        self.assertEqual(self.web.count("0000aaaa"), 1)
        self.assertIn("0000aaaa", r["source"]["url"])
        self.assertNotIn("warnings", r)  # same bytes: nothing to report

    def test_republished_file_with_different_content_is_reported(self):
        E.get_rate("EUR", 10, "2026-08")
        page = fixture("rfr_page.html").replace(b"d491908e", b"1111bbbb")
        new_url = listing_urls()["2026-08-31"].replace("d491908e", "1111bbbb")
        self.web.routes[E.RFR_PAGE] = page
        self.web.routes[new_url] = fixture("EIOPA_RFR_20260831.zip") + b"\0"  # other bytes, same content
        E.list_releases(refresh=True)
        r = E.get_rate("EUR", 10, "2026-08")
        self.assertTrue(any("differs from the copy retrieved" in w for w in r["warnings"]))

    def test_cache_written_by_another_parser_version_is_reparsed(self):
        E.get_rate("EUR", 10, "2026-08")
        path = self.cache / "releases" / "rfr_20260831.json"
        data = json.loads(path.read_text())
        data["format"] = 0
        data["curves"] = {}
        path.write_text(json.dumps(data))
        self.use_web(FakeWeb({}))
        r = E.get_rate("EUR", 10, "2026-08")
        self.assertEqual(r["no_va"]["rate"], 0.03268)
        self.assertEqual(json.loads(path.read_text())["format"], E.PARSER_VERSION)

    def test_damaged_parsed_release_is_read_again_from_the_zip(self):
        E.get_rate("EUR", 10, "2026-08")
        path = self.cache / "releases" / "rfr_20260831.json"
        data = json.loads(path.read_text())
        data["curves"]["no_va"] = {"sheet": "RFR_spot_no_VA"}  # right version, wrong shape
        path.write_text(json.dumps(data))
        self.use_web(FakeWeb({}))
        self.assertEqual(E.get_rate("EUR", 10, "2026-08")["no_va"]["rate"], 0.03268)

    def test_unwritable_cache_still_answers(self):
        import os
        blocker = self.tmp / "not-a-directory"
        blocker.write_text("x")
        os.environ["EIOPA_RFR_CACHE"] = str(blocker / "cache")
        r = E.get_rate("EUR", 10, "2026-08")
        self.assertEqual(r["no_va"]["rate"], 0.03268)
        self.assertTrue(any(w.startswith("not cached: cannot write") for w in r["warnings"]), r["warnings"])
        self.assertTrue(any("release list not cached" in w for w in r["warnings"]), r["warnings"])

    def test_tampered_release_list_entries_are_dropped(self):
        E.list_releases()
        path = self.cache / "listing.json"
        data = json.loads(path.read_text())
        data["releases"].insert(0, {"reference_date": "2099-12-31", "file": 42, "url": "https://evil.example/x.zip"})
        data["releases"].insert(0, "junk")
        data["releases"].append({"reference_date": "2030-01-31", "file": "x.zip", "url": "https://evil.example/x.zip"})
        path.write_text(json.dumps(data))
        self.assertEqual(E.list_releases()["latest"], "2030-01-31")  # well-formed, so kept and sorted first
        opened = []

        class NoNetwork:
            def open(self, request, timeout=None):
                opened.append(request.full_url)
                raise AssertionError("the network was used")

        with mock.patch.object(E, "http_get", REAL_HTTP_GET), mock.patch.object(E, "_OPENER", NoNetwork()):
            with self.assertRaises(E.FetchError) as ctx:
                E.get_rate("EUR", 10, "2030-01")  # its link is refused before any request
        self.assertIn("outside https://www.eiopa.europa.eu/", str(ctx.exception))
        self.assertEqual(opened, [])

    def test_garbage_in_the_cache_is_ignored(self):
        (self.cache / "releases").mkdir(parents=True)
        (self.cache / "releases" / "rfr_20260831.json").write_text("[1, 2]")
        (self.cache / "listing.json").write_bytes(b"\xff\xfe not json")
        self.assertEqual(E.get_rate("EUR", 10, "2026-08")["no_va"]["rate"], 0.03268)

    def test_import_a_release_downloaded_by_hand(self):
        path = self.tmp / "EIOPA_RFR_20260731.zip"
        path.write_bytes(fixture("EIOPA_RFR_20260731.zip"))
        rel = E.import_release(str(path))
        self.assertEqual((rel["reference_date"], rel["source"]["origin"]), ("2026-07-31", "import"))
        self.use_web(FakeWeb({}))
        r = E.get_rate("EUR", 10, "2026-07")
        self.assertEqual(r["no_va"]["rate"], 0.03159)
        self.assertIn("imported from a local copy", r["attribution"])

    def test_import_of_a_file_that_is_not_a_release(self):
        path = self.tmp / "page.html"
        path.write_bytes(fixture("throttled_429.html"))
        with self.assertRaises(E.FetchError):
            E.import_release(str(path))
        with self.assertRaises(E.NotFound):
            E.import_release(str(self.tmp / "missing.zip"))
        self.assertEqual(E._cached_dates(), [])

    def test_default_cache_location_is_under_the_isolated_home(self):
        import os
        del os.environ["EIOPA_RFR_CACHE"]
        del os.environ["XDG_CACHE_HOME"]
        path = E.cache_dir()
        self.assertTrue(str(path).startswith(str(self.home)), path)
        os.environ["XDG_CACHE_HOME"] = str(self.tmp / "xdg")
        if E.sys.platform not in ("win32", "darwin"):
            self.assertEqual(E.cache_dir(), self.tmp / "xdg" / "eiopa-rfr")


class Releases(Isolated):
    def test_list(self):
        r = E.list_releases()
        self.assertEqual(r["count"], 9)
        self.assertEqual((r["latest"], r["earliest"]), ("2026-08-31", "2015-12-31"))
        first = r["releases"][0]
        self.assertEqual({k: first[k] for k in ("reference_date", "label", "file", "page_date", "size", "cached")},
                         {"reference_date": "2026-08-31", "label": "August 2026", "file": "EIOPA_RFR_20260831.zip",
                          "page_date": "2026-09-03", "size": "3.13 MB", "cached": False})
        self.assertIn("release list, retrieved", r["attribution"])
        E.get_rate("EUR", 10, "2026-08")
        self.assertTrue(E.list_releases()["releases"][0]["cached"])
