"""The parsers on trimmed real files, and on the broken files a download can produce."""
import io
import json
import re
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbam_test_support import fixture  # noqa: E402
from cbam_mcp import parsers  # noqa: E402
from cbam_mcp.parsers import ParseError  # noqa: E402


class Regulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = parsers.parse_regulation_xhtml(fixture("consolidated_trimmed.xhtml"))

    def line(self, code):
        return next(e for e in self.doc["annex_i"] if e["code"] == code)

    def test_annex_i_lines_and_categories(self):
        self.assertEqual(len(self.doc["annex_i"]), 42)
        self.assertEqual({e["category"] for e in self.doc["annex_i"]},
                         {"Cement", "Electricity", "Fertilisers", "Iron and steel", "Aluminium", "Chemicals"})

    def test_ex_line_keeps_its_marker_and_amendment(self):
        e = self.line("25070080")
        self.assertTrue(e["ex"])
        self.assertEqual(e["description"], "Other kaolinic clays except non-calcined kaolinic clays")
        self.assertEqual(e["amended_by"], ["32025R2083"])
        self.assertFalse(self.line("25231000")["ex"])

    def test_exceptions_of_chapter_72(self):
        e = self.line("72")
        codes = [x["code"] for x in e["except"]]
        self.assertEqual(codes[0], "72022")
        self.assertIn("7204", codes)
        self.assertTrue(next(x for x in e["except"] if x["code"] == "720299")["heading_only"])
        self.assertEqual([x["code"] for x in self.line("3105")["except"]], ["31056000"])

    def test_gases(self):
        self.assertEqual(self.line("28080000")["greenhouse_gases"], "Carbon dioxide and nitrous oxide")
        self.assertEqual(self.line("7601")["greenhouse_gases"], "Carbon dioxide and perfluorocarbons")
        self.assertEqual(self.line("28041000")["category"], "Chemicals")

    def test_annex_ii_iii_and_quotes(self):
        self.assertEqual([e["code"] for e in self.doc["annex_ii"]], ["72", "7601", "28041000", "27160000"])
        self.assertEqual(self.doc["annex_iii_point_1"]["countries"], ["Iceland", "Liechtenstein", "Norway", "Switzerland"])
        self.assertIn("Büsingen", self.doc["annex_iii_point_1"]["territories"])
        q = self.doc["quotes"]
        self.assertEqual(q["annex_vii_1"], "The single mass-based threshold referred to in Article 2a shall be set at 50 tonnes of net mass.")
        self.assertEqual(q["article_2a_4"], "This Article shall not apply to imports of electricity or hydrogen.")
        self.assertTrue(q["article_7_1"].endswith("For goods listed in Annex II only direct emissions shall be calculated and taken into account."))
        self.assertEqual(self.doc["amendments"], {"M1": "32025R2083"})
        self.assertTrue(self.doc["disclaimer"].startswith("This text is meant purely as a documentation tool"))

    def test_broken_documents(self):
        cases = {
            b"": "empty",
            b"   \n": "empty",
            b"<html><body>": "not well-formed",
            b"<html xmlns='http://www.w3.org/1999/xhtml'><body><p>Service unavailable</p></body></html>": "no Annex I",
            b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><x>&a;</x>": "entities",
            "<html><body>café</body></html>".encode("latin-1"): "not well-formed",
        }
        for raw, expected in cases.items():
            with self.assertRaises(ParseError, msg=raw[:40]) as cm:
                parsers.parse_regulation_xhtml(raw)
            self.assertIn(expected, str(cm.exception))

    def test_deep_nesting_is_a_parse_error_not_a_crash(self):
        # Review: a RecursionError used to escape from refresh.
        deep = (b'<html xmlns="http://www.w3.org/1999/xhtml"><body><div id="anx_I">' + b"<div>" * 3000 + b"x"
                + b"</div>" * 3000 + b'</div><div id="anx_II"/></body></html>')
        with self.assertRaises(ParseError):
            parsers.parse_regulation_xhtml(deep)
        cell = (b'<html xmlns="http://www.w3.org/1999/xhtml"><body><table><tr><td colspan="6">India</td></tr>'
                b"<tr><td>" + b"<span>" * 3000 + b"7601" + b"</span>" * 3000 + b"</td></tr></table></body></html>")
        with self.assertRaises(ParseError):
            parsers.parse_oj_default_values(cell)

    def test_layout_change_is_caught_by_the_floor(self):
        raw = fixture("consolidated_trimmed.xhtml").replace(b'id="anx_I"', b'id="anx_I_old"', 1)
        with self.assertRaises(ParseError):
            parsers.parse_regulation_xhtml(raw)
        # Annex I reduced to its first table: the parser must refuse rather than ship a shrunken scope.
        raw = fixture("consolidated_trimmed.xhtml")
        start = raw.index(b'id="anx_I"')
        cut = raw.index(b"</table>", start) + len(b"</table>")
        end = raw.index(b'<div id="anx_II"')
        with self.assertRaises(ParseError) as cm:
            parsers.parse_regulation_xhtml(raw[:cut] + b"</div></div>" + raw[end:])
        self.assertIn("layout changed", str(cm.exception))


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class Spreadsheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = fixture("default_values_trimmed.xlsx")
        cls.doc = parsers.parse_default_values_xlsx(cls.raw)

    def test_version_and_disclaimer(self):
        self.assertEqual(self.doc["versions"][-1]["version"], "2")
        self.assertEqual(self.doc["versions"][-1]["date"], "2026-08-06")
        self.assertIn("not legally binding", self.doc["disclaimer"])

    def test_tables(self):
        t = self.doc["tables"]
        self.assertEqual(t["India"]["7601"], ["1,870", "N/A", "1,870", "(K)"])
        self.assertEqual(t["Türkiye"]["25232100"], ["-", "-", "-", ""])
        self.assertNotIn("7601", t["Albania"])
        self.assertEqual(self.doc["other_table"], "Other Countries and Territories")
        self.assertEqual(self.doc["annex_iv"]["7601"], ["3,198", "(K)"])
        self.assertEqual(self.doc["lines"]["2507008080"]["display"], "2507 00 80 80")
        self.assertEqual(self.doc["lines"]["28041000"]["category"], "Hydrogen")
        self.assertEqual(self.doc["order"][0], "2507008080")

    def test_values(self):
        self.assertEqual(parsers.parse_value("1,870"), (1.87, "value"))
        self.assertEqual(parsers.parse_value("0,000"), (0.0, "value"))
        self.assertEqual(parsers.parse_value("2.5"), (2.5, "value"))
        self.assertEqual(parsers.parse_value("-")[1], "dash")
        self.assertEqual(parsers.parse_value("–")[1], "dash")
        self.assertEqual(parsers.parse_value("N/A")[1], "not_applicable")
        self.assertEqual(parsers.parse_value("see below")[1], "see_below")
        self.assertEqual(parsers.parse_value("")[1], "empty")
        self.assertEqual(parsers.parse_value("approx. 2")[1], "unrecognised")

    def test_broken_files(self):
        cases = {
            b"": "empty",
            b"<html>404 Not Found</html>": "not an xlsx",
            self.raw[: len(self.raw) // 2]: "",
            make_zip({"xl/sharedStrings.xml": "<sst/>"}): "xl/workbook.xml is missing",
        }
        for raw, expected in cases.items():
            with self.assertRaises(ParseError, msg=raw[:20]) as cm:
                parsers.parse_default_values_xlsx(raw)
            self.assertIn(expected, str(cm.exception))

    def test_missing_column_and_bad_shared_string(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        broken = dict(files)
        broken["xl/sharedStrings.xml"] = files["xl/sharedStrings.xml"].replace(b"Description", b"Label")
        with self.assertRaises(ParseError) as cm:
            parsers.parse_default_values_xlsx(make_zip(broken))
        self.assertIn("no column for description", str(cm.exception))
        broken = dict(files)
        broken["xl/worksheets/sheet3.xml"] = re.sub(rb't="s"><v>\d+</v>', b't="s"><v>99999</v>',
                                                   files["xl/worksheets/sheet3.xml"], count=1)
        self.assertNotEqual(broken["xl/worksheets/sheet3.xml"], files["xl/worksheets/sheet3.xml"])
        with self.assertRaises(ParseError) as cm:
            parsers.parse_default_values_xlsx(make_zip(broken))
        self.assertIn("missing shared string", str(cm.exception))

    def test_zip_bomb_guard(self):
        with mock.patch.object(parsers, "MAX_XLSX_UNPACKED", 1000):
            with self.assertRaises(ParseError) as cm:
                parsers.parse_default_values_xlsx(self.raw)
        self.assertIn("unpacks to more than", str(cm.exception))


class Sparql(unittest.TestCase):
    def test_cn_rows(self):
        rows = parsers.sparql_rows(fixture("sparql_cn2026_trimmed.json"), "cn")
        cn = parsers.parse_cn_rows(rows)
        self.assertEqual(cn["720851200080"][:3], ["72085120", "Of a thickness exceeding 15 mm", 3])
        self.assertEqual(cn["271600000080"][1], "Electrical energy")
        mid = cn["720851910010"]
        self.assertEqual(mid[0], "")  # an unnumbered line of the CN
        self.assertEqual(mid[4], "720851000080")

    def test_bad_answers(self):
        cases = {b"": "empty", b"\xff\xfe{\x00": "not UTF-8", b"<html>502</html>": "not JSON",
                 b"null": "not a SPARQL", b'{"results": {"bindings": 5}}': "not a SPARQL", b'{"head": {}}': "not a SPARQL"}
        for raw, expected in cases.items():
            with self.assertRaises(ParseError) as cm:
                parsers.sparql_rows(raw, "q")
            self.assertIn(expected, str(cm.exception))

    def test_empty_result_and_odd_rows(self):
        self.assertEqual(parsers.sparql_rows(b'{"results": {"bindings": []}}', "q"), [])
        rows = [{"id": "not-an-id"}, {"id": "720851200080", "label": "--- X", "depth": "seven"}, "junk"]
        cn = parsers.parse_cn_rows([r for r in rows if isinstance(r, dict)])
        self.assertEqual(list(cn), ["720851200080"])
        self.assertEqual(cn["720851200080"][5], 0)
        doc = json.dumps({"results": {"bindings": ["junk", {"id": {"value": "1"}}]}}).encode()
        self.assertEqual(parsers.sparql_rows(doc, "q"), [{"id": "1"}])


class OfficialJournal(unittest.TestCase):
    def test_tables_and_text(self):
        oj = parsers.parse_oj_default_values(fixture("oj_1740_trimmed.xhtml"))
        self.assertEqual(oj["tables"]["India"]["7601"], ["1,870", "N/A", "1,870", "(K)"])
        self.assertEqual(oj["annex_iv"]["7601"], ["3,198", "(K)"])
        self.assertIn("needs to be selected", oj["text"])

    def test_no_tables(self):
        with self.assertRaises(ParseError):
            parsers.parse_oj_default_values(b"<html xmlns='http://www.w3.org/1999/xhtml'><body/></html>")


if __name__ == "__main__":
    unittest.main()
