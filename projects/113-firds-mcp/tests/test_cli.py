"""The command line: exit codes 0 answered, 1 not found, 2 invalid input or source failure."""
import contextlib
import io
import json
import urllib.error

import fakenet
import support
from support import fm


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fm.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Cli(support.OfflineTest):
    def test_group_text(self):
        code, out, err = run("group", "DE0005140008")
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], "DE0005140008  DEUTSCHE BANK AG NAMENS-AKTIEN O.N.")
        self.assertIn("Issuer (GLEIF): DEUTSCHE BANK AKTIENGESELLSCHAFT (7LTWFZYICNSX8D621K86, DE, GENERAL, "
                      "entity ACTIVE, registration ISSUED)", lines)
        self.assertIn("Ultimate parent: none reported; reporting exception NO_KNOWN_PERSON", lines)
        self.assertIn("  not terminated: CEUX JBUL RFQN XETA", lines)
        self.assertIn(fm.REMOTE_NOTE, lines)
        self.assertEqual(lines[-1], fm.ESMA_DISCLAIMER)
        self.assertNotIn("<<remote text", out)

    def test_group_json_is_the_mcp_answer(self):
        code, out, _ = run("group", "XS1910948592", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["ultimate_parent"]["entity"]["lei"], "529900NNUPAGGOMPXZ31")
        self.assertEqual(data, fm.isin_to_group("XS1910948592"))

    def test_isin_all_venues(self):
        code, out, _ = run("isin", "DE0005140008", "--all-venues")
        self.assertEqual(code, 0)
        self.assertIn("Venues (FIRDS, as of 2026-09-24): 4 not terminated, 2 terminated, 2 cancelled", out)
        self.assertIn("  XTXM  terminated     first trade/admission 2018-07-04T08:30:00Z, termination "
                      "2020-12-31T22:59:59Z, status Terminated", out.splitlines())

    def test_not_found_exits_1(self):
        self.assertEqual(run("isin", "XS0000000009")[0], 1)
        self.assertEqual(run("lei", "529900ZZZZZZZZZZZZ46")[0], 1)

    def test_invalid_input_exits_2_and_sends_nothing(self):
        code, out, err = run("isin", "DE0005140009")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Nothing was sent", err)
        code, _, err = run("children", "7LTWFZYICNSX8D621K86", "--limit", "9999")
        self.assertEqual(code, 2)
        self.assertNoNetwork()

    def test_source_down_exits_2(self):
        down = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        self.net.script("firds/DE0005140008", down, down)
        code, out, err = run("isin", "DE0005140008")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("ESMA could not answer: cannot connect", err)

    def test_partial_answer_exits_2(self):
        down = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        self.net.script("gleif/7LTWFZYICNSX8D621K86", down, down)
        code, out, _ = run("group", "DE0005140008")
        self.assertEqual(code, 2)
        self.assertIn("GLEIF part missing: GLEIF: cannot connect", out)
        self.assertIn("DE0005140008  DEUTSCHE BANK AG NAMENS-AKTIEN O.N.", out)

    def test_children_and_parents(self):
        fm.GLEIF_PAGE_MAX = 2
        code, out, _ = run("children", "7LTWFZYICNSX8D621K86", "--limit", "3")
        self.assertEqual(code, 0)
        self.assertIn("7LTWFZYICNSX8D621K86: 327 direct children in GLEIF; 3 shown", out)
        code, out, _ = run("parents", "5299004PWNHKYTR23649")
        self.assertIn("Direct parent: VOLKSWAGEN AKTIENGESELLSCHAFT (529900NNUPAGGOMPXZ31, DE, GENERAL, "
                      "entity ACTIVE, registration ISSUED)", out)

    def test_lei_text_strips_terminal_escapes(self):
        payload = fakenet.fixture_json("gleif/5493006W3QUS5LMH6R84")
        payload["data"]["attributes"]["entity"]["otherNames"][0]["name"] = "Toyota\x1b]0;owned\x07\x1b[2J Motor"
        self.net.script("gleif/5493006W3QUS5LMH6R84", (200, payload, {}))
        code, out, _ = run("lei", "5493006W3QUS5LMH6R84")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertIn("トヨタ自動車株式会社 (5493006W3QUS5LMH6R84, JP", out)

    def test_sources_offline(self):
        code, out, _ = run("sources")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["sources"][1]["licence"], "CC0 1.0")
        self.assertNoNetwork()

    def test_version(self):
        with self.assertRaises(SystemExit) as cm:
            run("--version")
        self.assertEqual(cm.exception.code, 0)

    def test_unexpected_failure_is_one_line(self):
        original = fm.isin_to_group
        self.addCleanup(setattr, fm, "isin_to_group", original)
        fm.isin_to_group = lambda isin: {}["boom"]
        code, out, err = run("group", "DE0005140008")
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), "firds-mcp: unexpected KeyError: 'boom'")


if __name__ == "__main__":
    import unittest
    unittest.main()
