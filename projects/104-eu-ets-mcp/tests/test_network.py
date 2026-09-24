"""The listing and the downloads against a loopback server that fails in the ways the registry does."""
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import FILES, Isolated, Registry, eu_ets, no_sleep  # noqa: E402


class ListingTest(unittest.TestCase):
    def setUp(self):
        self.env = Isolated().__enter__()
        self.reg = Registry().__enter__()
        self.waits = []

    def tearDown(self):
        self.reg.__exit__()
        self.env.__exit__()

    def fetch(self, **kw):
        return eu_ets.fetch_listing(self.reg.listing_url, timeout=kw.pop("timeout", 5), sleep=self.waits.append, **kw)

    def test_ok(self):
        files = eu_ets.resolve_files(self.fetch(), self.reg.listing_url)
        self.assertEqual(eu_ets.file_name(files["operators"]), "operators_daily.csv.gz")

    def test_404_says_the_endpoint_may_have_moved(self):
        self.reg.faults["listing"] = [("status", 404)]
        with self.assertRaisesRegex(eu_ets.FetchError, "HTTP 404.*undocumented"):
            self.fetch()
        self.assertEqual(len(self.reg.requests), 1)  # no retry on 404

    def test_429_honours_retry_after_then_succeeds(self):
        self.reg.faults["listing"] = [("status", 429, {"Retry-After": "7"}), ("ok",)]
        self.assertTrue(self.fetch())
        self.assertEqual(self.waits, [7.0])

    def test_429_with_a_long_retry_after_gives_up_at_once(self):
        self.reg.faults["listing"] = [("status", 429, {"Retry-After": "3600"})]
        with self.assertRaisesRegex(eu_ets.FetchError, "HTTP 429"):
            self.fetch()
        self.assertEqual(self.waits, [])

    def test_server_errors_are_retried_then_reported(self):
        self.reg.faults["listing"] = [("status", 503)]
        with self.assertRaisesRegex(eu_ets.FetchError, "HTTP 503"):
            self.fetch()
        self.assertEqual(len(self.reg.requests), 3)

    def test_bodies_that_are_not_a_file_list(self):
        for body, msg in ((b"", "empty body"), (b"null", "not a list"), (b'{"files": []}', "not a list"),
                          (b"\xff\xfe\x00{", "not valid JSON"), (b"<html>maintenance</html>", "not valid JSON")):
            with self.subTest(body=body):
                self.reg.requests.clear()
                self.reg.faults["listing"] = [("body", body)]
                with self.assertRaisesRegex(eu_ets.FetchError, msg):
                    self.fetch()
        self.reg.faults["listing"] = [("body", b"[1, 2, 3]")]
        with self.assertRaisesRegex(eu_ets.FetchError, "no longer offers"):
            eu_ets.resolve_files(self.fetch(), self.reg.listing_url)

    def test_timeout(self):
        self.reg.faults["listing"] = [("sleep", 1.5)]
        with self.assertRaisesRegex(eu_ets.FetchError, "timed out"):
            self.fetch(timeout=0.3, attempts=2)

    def test_network_down(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens there now
        with self.assertRaisesRegex(eu_ets.FetchError, "could not reach"):
            eu_ets.fetch_listing(f"http://127.0.0.1:{port}/api/data-download", timeout=2, sleep=no_sleep)


class DownloadTest(unittest.TestCase):
    NAME = "operators_daily.csv.gz"

    def setUp(self):
        self.env = Isolated().__enter__()
        self.reg = Registry().__enter__()
        self.url = f"{self.reg.base}/public-data/{self.NAME}"
        self.dest = self.env.path / self.NAME
        self.size = FILES[self.NAME].stat().st_size

    def tearDown(self):
        self.reg.__exit__()
        self.env.__exit__()

    def test_cut_transfer_resumes_with_a_range_request(self):
        self.reg.faults[self.NAME] = [("cut", 500), ("ok",)]
        info = eu_ets.download(self.url, self.dest, timeout=5, sleep=no_sleep)
        self.assertEqual((info["bytes"], info["sha256"]), (self.size, eu_ets.sha256_file(FILES[self.NAME])))
        second = self.reg.paths(self.NAME)[1][1]
        self.assertEqual((second.get("Range"), second.get("If-Range")), ("bytes=500-", '"v1"'))

    def test_server_ignoring_range_restarts_cleanly(self):
        self.reg.faults[self.NAME] = [("cut", 500), ("norange",)]
        info = eu_ets.download(self.url, self.dest, timeout=5, sleep=no_sleep)
        self.assertEqual(info["sha256"], eu_ets.sha256_file(FILES[self.NAME]))

    def test_always_cut_gives_up_and_leaves_nothing(self):
        self.reg.faults[self.NAME] = [("cut", 100)]
        with self.assertRaisesRegex(eu_ets.FetchError, "gave up after 4 attempts"):
            eu_ets.download(self.url, self.dest, timeout=5, sleep=no_sleep)
        self.assertEqual(list(self.env.path.glob(self.NAME + "*")), [])

    def test_404_is_not_retried(self):
        with self.assertRaisesRegex(eu_ets.FetchError, "HTTP 404"):
            eu_ets.download(f"{self.reg.base}/public-data/missing.csv.gz", self.dest, timeout=5, sleep=no_sleep)
        self.assertEqual(len(self.reg.requests), 1)

    def test_429_then_success(self):
        waits = []
        self.reg.faults[self.NAME] = [("status", 429, {"Retry-After": "2"}), ("ok",)]
        eu_ets.download(self.url, self.dest, timeout=5, sleep=waits.append)
        self.assertEqual(waits, [2.0])

    def test_size_limit(self):
        with self.assertRaisesRegex(eu_ets.FetchError, "larger than"):
            eu_ets.download(self.url, self.dest, timeout=5, sleep=no_sleep, max_bytes=100)


if __name__ == "__main__":
    unittest.main()
