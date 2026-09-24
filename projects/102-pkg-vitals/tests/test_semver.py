"""npm range resolution, against answers recorded from node-semver itself. No network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Case, load, pkg_vitals as pv  # noqa: E402


class AgainstNodeSemver(Case):
    def test_every_recorded_range(self):
        ref = load("semver-node.json")
        versions = {v: {} for v in ref["versions"]}
        for rng, expected in ref["expected"].items():
            with self.subTest(range=rng):
                sets = pv.parse_range(rng)
                self.assertIsNotNone(sets)
                self.assertEqual(pv.max_satisfying(versions, sets), expected)


class Picking(Case):
    VERSIONS = {"1.0.0": {}, "1.1.0": {}, "1.2.0": {"deprecated": "broken"}, "2.0.0": {}}

    def test_latest_tag_wins_when_it_matches(self):
        # npm prefers the version tagged latest when the range allows it, even over a higher match
        self.assertEqual(pv.max_satisfying(self.VERSIONS, pv.parse_range("*"), latest="1.1.0"), "1.1.0")

    def test_deprecated_versions_are_avoided_when_possible(self):
        self.assertEqual(pv.max_satisfying(self.VERSIONS, pv.parse_range("^1.0.0")), "1.1.0")
        self.assertEqual(pv.max_satisfying(self.VERSIONS, pv.parse_range("1.2.0")), "1.2.0")

    def test_not_a_range(self):
        for spec in ("latest", "next", "^", ">=", "1.2.3.4", "not a range", "=>1"):
            self.assertIsNone(pv.parse_range(spec), spec)

    def test_versions_that_are_not_semver_are_ignored(self):
        self.assertEqual(pv.max_satisfying({"1.0": {}, "banana": {}, "1.0.1": {}}, pv.parse_range("^1")), "1.0.1")


if __name__ == "__main__":
    unittest.main()
