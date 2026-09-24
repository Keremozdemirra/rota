"""The YAML subset: where `uses:` is read, quoting, comments, block scalars, flow style, anchors. No network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts the project on sys.path)

import action_vitals as av  # noqa: E402


def uses(text):
    return [(u["line"], u["value"], u["context"]) for u in av.find_uses(av.scan_yaml(text))]


def one(text):
    found = av.find_uses(av.scan_yaml(text))
    assert len(found) == 1, found
    return found[0]


class Places(unittest.TestCase):
    def test_steps_reusable_workflows_and_composite_steps(self):
        text = ("on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: actions/checkout@v6\n"
                "      - name: n\n        uses: o/r/sub@v1\n  b:\n    uses: o/r/.github/workflows/w.yml@main\n"
                "    with:\n      uses: not-an-action\n")
        self.assertEqual(uses(text), [(6, "actions/checkout@v6", "step"), (8, "o/r/sub@v1", "step"),
                                      (10, "o/r/.github/workflows/w.yml@main", "reusable workflow")])
        self.assertEqual(uses("runs:\n  using: composite\n  steps:\n    - uses: o/r@v2\n      shell: bash\n"),
                         [(4, "o/r@v2", "composite step")])

    def test_uses_elsewhere_is_not_an_action(self):
        text = ("jobs:\n  a:\n    steps:\n      - uses: o/r@v1\n        with:\n          uses: o/x@v9\n"
                "        env:\n          uses: o/y@v9\n    env:\n      uses: o/z@v9\nuses: o/top@v9\n")
        self.assertEqual([v for _, v, _ in uses(text)], ["o/r@v1"])

    def test_block_scalars_are_skipped(self):
        text = ("jobs:\n  a:\n    steps:\n      - run: |\n          uses: evil/one@v1\n          - uses: evil/two@v1\n"
                "      - run: >-\n          uses: evil/three@v1\n      - uses: good/one@v1\n")
        self.assertEqual([v for _, v, _ in uses(text)], ["good/one@v1"])

    def test_block_scalar_ends_at_its_key_column(self):
        # content at the key's own column is not content (PyYAML 6.0.2 reads it the same way)
        self.assertEqual(uses("jobs:\n  a:\n    steps:\n    - run: |\n      uses: o/r@v1\n"),
                         [(5, "o/r@v1", "step")])

    def test_sequences_at_their_keys_indentation_and_nested(self):
        text = "jobs:\n  a:\n    steps:\n    - uses: o/r@v1\n    - uses: o/s@v2\n    runs-on: x\n  b:\n    steps:\n    -\n      uses: o/t@v3\n"
        self.assertEqual([v for _, v, _ in uses(text)], ["o/r@v1", "o/s@v2", "o/t@v3"])


class Values(unittest.TestCase):
    def test_quotes_and_escapes(self):
        u = one('jobs:\n  a:\n    steps:\n      - uses: "o/r@v1"\n')
        self.assertEqual((u["value"], u["quote"], u["start"], u["end"]), ("o/r@v1", '"', 14, 22))
        self.assertEqual(one("jobs:\n  a:\n    steps:\n      - uses: 'o/it''s@v1'\n")["value"], "o/it's@v1")
        self.assertEqual(one('jobs:\n  a:\n    steps:\n      - uses: "o/r\\u0040v1"\n')["value"], "o/r@v1")
        self.assertEqual(one('jobs:\n  a:\n    steps:\n      - "uses": o/r@v1\n')["value"], "o/r@v1")

    def test_comments(self):
        u = one("jobs:\n  a:\n    steps:\n      # - uses: commented/out@v1\n      - uses: o/r@v1 # v1.2.3  \n")
        self.assertEqual((u["value"], u["comment"]), ("o/r@v1", "v1.2.3"))
        self.assertEqual(one("jobs:\n  a:\n    steps:\n      - uses: o/r@v1#x\n")["value"], "o/r@v1#x")
        self.assertEqual(one("jobs:\n  a:\n    steps:\n      - uses: 'o/r@v1'# not a comment\n")["comment"], "")

    def test_value_on_the_next_line_and_folded(self):
        self.assertEqual(one("jobs:\n  a:\n    steps:\n      - uses:\n          o/r@v1\n")["value"], "o/r@v1")
        u = one("jobs:\n  a:\n    steps:\n      - uses: o/r\n          @v1\n")
        self.assertEqual((u["value"], u["start"]), ("o/r @v1", None))  # folded: reported, never rewritten

    def test_crlf_bom_and_unicode(self):
        text = "\ufeffname: ci ✓\r\njobs:\r\n  a:\r\n    steps:\r\n      - uses: o/r@v1 # sürüm\r\n"
        u = one(text)
        self.assertEqual((u["line"], u["value"], u["comment"], u["start"]), (5, "o/r@v1", "sürüm", 14))

    def test_flow_style(self):
        text = ("jobs:\n  a:\n    steps:\n      - {name: x, uses: 'o/r@v1', with: {k: v}}\n"
                "  b:\n    steps: [{uses: o/s@v2}, {run: echo}]\n  c:\n    steps:\n      - {uses: o/t@v3,\n         with: {k: v}}\n")
        self.assertEqual(uses(text), [(4, "o/r@v1", "step"), (6, "o/s@v2", "step"), (9, "o/t@v3", "step")])
        line = text.split("\n")[3]
        u = av.find_uses(av.scan_yaml(text))[0]
        self.assertEqual(line[u["start"]:u["end"]], "'o/r@v1'")


class Anchors(unittest.TestCase):
    def test_scalar_anchor_and_alias(self):
        text = "jobs:\n  a:\n    steps:\n      - uses: &co actions/checkout@v6\n  b:\n    steps:\n      - uses: *co\n"
        found = av.find_uses(av.scan_yaml(text))
        self.assertEqual([(u["line"], u["value"], u["via"]) for u in found],
                         [(4, "actions/checkout@v6", None), (7, "actions/checkout@v6", "co")])
        self.assertIsNone(found[1]["start"])  # the text lives on line 4; only that line is rewritten

    def test_aliased_step_and_job_are_not_counted_twice(self):
        text = ("jobs:\n  a:\n    steps:\n      - &step\n        uses: o/r@v1\n  b:\n    steps:\n      - *step\n"
                "  c: &job\n    steps:\n      - uses: o/s@v2\n  d: *job\n")
        self.assertEqual(uses(text), [(5, "o/r@v1", "step"), (11, "o/s@v2", "step")])

    def test_unresolvable_aliases_are_reported(self):
        cases = {
            "jobs:\n  a:\n    steps:\n      - uses: *nowhere\n": "no anchor &nowhere",
            "jobs:\n  a:\n    steps:\n      - *nostep\n": "no anchor &nostep",
            "jobs:\n  a:\n    steps:\n      - <<: *nomerge\n        with: {}\n": "no anchor &nomerge",
            "jobs:\n  a:\n    steps: *nosteps\n": "no anchor &nosteps",
            "x: &m {k: v}\njobs:\n  a:\n    steps:\n      - uses: *m\n": "&m is not a single value",
            "jobs:\n  a:\n    steps:\n      - uses: *late\n  b:\n    steps:\n      - uses: &late o/r@v1\n": "no anchor &late",
        }
        for text, why in cases.items():
            found = [u for u in av.find_uses(av.scan_yaml(text)) if u["unresolved"]]
            self.assertEqual(len(found), 1, text)
            self.assertIn(why, found[0]["unresolved"], text)

    def test_alias_in_with_or_env_is_not_a_uses(self):
        text = "jobs:\n  a:\n    env: *nothing\n    steps:\n      - uses: o/r@v1\n        with: *nope\n"
        self.assertEqual([u["unresolved"] for u in av.find_uses(av.scan_yaml(text))], [None])

    def test_anchor_on_a_key_in_a_sequence_entry(self):
        # `- &a uses: x` anchors the key "uses", as PyYAML reads it; the step itself is still read
        self.assertEqual(uses("jobs:\n  a:\n    steps:\n      - &a uses: o/r@v1\n"), [(4, "o/r@v1", "step")])


class Robustness(unittest.TestCase):
    def test_tabs_markers_and_garbage(self):
        s = av.scan_yaml("---\njobs:\n\ta: 1\n  b:\n    steps:\n      - uses: o/r@v1\n...\n")
        self.assertEqual(s.issues, [(3, "tab in indentation, line not read")])
        self.assertEqual([u["value"] for u in av.find_uses(s)], ["o/r@v1"])
        for text in ("", "\n\n", "{", "[", "'", '"unterminated\n', "- - - -", ":", "? x", "jobs: [", "a: {b: [c, {d",
                     "jobs:\n  a:\n    steps:\n      - uses: 'o/r@v1\n", "\x00\x01", "- *\n", "&\n", "k: !\n",
                     "jobs:\n  a:\n    steps:\n      - {uses: *}\n"):
            av.find_uses(av.scan_yaml(text))  # no exception

    def test_long_input_is_linear(self):
        import time
        text = "jobs:\n  a:\n    steps:\n" + "      - uses: o/r@v1 # x\n        with: {a: [1, 2, 3]}\n" * 5000
        t = time.monotonic()
        self.assertEqual(len(av.find_uses(av.scan_yaml(text))), 5000)
        self.assertLess(time.monotonic() - t, 10)


if __name__ == "__main__":
    unittest.main()
