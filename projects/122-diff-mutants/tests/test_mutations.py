"""The mutation operators: each makes valid Python that differs from the original in exactly one node."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401  (puts the project root on sys.path)

import diff_mutants as dm  # noqa: E402


def mutate(code: str, changed=None):
    """[(candidate, mutated text)] for every mutant of `code` on `changed` lines (default: all)."""
    if changed is None:
        changed = set(range(1, len(dm.Source(code).starts) + 1))
    m = dm.Mutator("m.py", code, set(changed))
    return [(c, c.apply(code)) for c in m.run()]


def texts(code, changed=None, operator=None):
    return [t for c, t in mutate(code, changed) if operator is None or c.operator == operator]


SAMPLE = '''\
import logging
import warnings

log = logging.getLogger(__name__)


def price(qty: int, unit: float = 2.0, member: bool = False) -> float:
    total = qty * unit + 1 - 0
    total **= 1
    if qty >= 10 and not member or qty < 0:
        total = total / 2 // 1 % 7
    if qty is not None and qty in (1, 2) and qty != 3:
        record(total)
    log.info("total %s", total)
    print(total)
    warnings.warn("x")
    while True:
        break
    return total


async def fetch(client):
    await client.close()
    return None


if __name__ == "__main__":
    price(1)
'''


class EveryOperator(unittest.TestCase):
    def test_all_mutants_parse_and_differ_by_one_node(self):
        tree = ast.parse(SAMPLE)
        found = mutate(SAMPLE)
        self.assertGreater(len(found), 20)
        for cand, text in found:
            diffs = dm.node_differences(tree, ast.parse(text), [])
            self.assertEqual(len(diffs), 1, (cand.description, cand.line, diffs, text))
            self.assertTrue(dm.valid_mutant(tree, text))

    def test_the_list_of_operators_is_the_documented_one(self):
        self.assertEqual({c.operator for c, _ in mutate(SAMPLE)}, set(dm.OPERATORS))

    def test_calls_nobody_asserts_on_are_kept(self):
        removed = [c.description for c, _ in mutate(SAMPLE) if c.operator == "call"]
        self.assertEqual(sorted(removed), ["`await client.close()` removed", "`price(1)` removed",
                                           "`record(total)` removed"])

    def test_main_guard_and_annotations_are_left_alone(self):
        lines = {c.line for c, _ in mutate(SAMPLE) if c.operator == "comparison"}
        self.assertNotIn(27, lines)  # if __name__ == "__main__"
        consts = [c.description for c, _ in mutate(SAMPLE) if c.operator == "constant" and c.line == 7]
        self.assertEqual(consts, ["`False` → `True`"])  # `int`/`float` annotations untouched; 2.0 is a float

    def test_return_none_is_not_mutated(self):
        self.assertNotIn(24, {c.line for c, _ in mutate(SAMPLE) if c.operator == "return"})


class Operators(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(texts("x = a + b\n", operator="arithmetic"), ["x = a - b\n"])
        self.assertEqual(texts("x = a - b\n", operator="arithmetic"), ["x = a + b\n"])
        self.assertEqual(texts("x = a * b\n", operator="arithmetic"), ["x = a / b\n"])
        self.assertEqual(texts("x = a / b\n", operator="arithmetic"), ["x = a * b\n"])
        self.assertEqual(texts("x = a // b\n", operator="arithmetic"), ["x = a / b\n"])
        self.assertEqual(texts("x = a % b\n", operator="arithmetic"), ["x = a / b\n"])
        self.assertEqual(texts("x += y\n", operator="arithmetic"), ["x -= y\n"])
        self.assertEqual(texts("x //= y\n", operator="arithmetic"), ["x /= y\n"])

    def test_power_keeps_its_shape(self):
        # `x * a ** b` -> `x * a * b` would regroup as (x * a) * b
        self.assertEqual(texts("y = x * a ** b\n", operator="arithmetic"), ["y = x / a ** b\n", "y = x * (a * b)\n"])
        self.assertEqual(texts("y = -a ** 2\n", operator="arithmetic"), ["y = -(a * 2)\n"])

    def test_comparison(self):
        self.assertEqual(texts("f(a < b)\n", operator="comparison"), ["f(a <= b)\n"])
        self.assertEqual(texts("f(a >= b)\n", operator="comparison"), ["f(a > b)\n"])
        self.assertEqual(texts("f(a == b)\n", operator="comparison"), ["f(a != b)\n"])
        self.assertEqual(texts("f(a is not None)\n", operator="comparison"), ["f(a is None)\n"])
        self.assertEqual(texts("f(a is None)\n", operator="comparison"), ["f(a is not None)\n"])
        self.assertEqual(texts("f(a not in b)\n", operator="comparison"), ["f(a in b)\n"])
        self.assertEqual(texts("f(a in b)\n", operator="comparison"), ["f(a not in b)\n"])
        self.assertEqual(texts("f(0 < a <= 9)\n", operator="comparison"), ["f(0 <= a <= 9)\n", "f(0 < a < 9)\n"])

    def test_boolean_keeps_its_shape(self):
        self.assertEqual(texts("f(a and b)\n", operator="boolean"), ["f(a or b)\n"])
        # `a or b and c` is Or(a, And(b, c)); plain swaps would flatten it into one BoolOp
        self.assertEqual(texts("f(a or b and c)\n", operator="boolean"), ["f(a and (b and c))\n", "f(a or (b or c))\n"])
        self.assertEqual(texts("f(a and b and c)\n", operator="boolean"), ["f(a or b or c)\n"])

    def test_not_removal(self):
        self.assertEqual(texts("f(not x)\n", operator="not"), ["f(x)\n"])
        self.assertEqual(texts("f(not(x))\n", operator="not"), ["f((x))\n"])
        self.assertEqual(texts("if not a and b:\n    pass\n", operator="not"), ["if a and b:\n    pass\n"])

    def test_constants(self):
        self.assertEqual(texts("x = True\n", operator="constant"), ["x = False\n"])
        self.assertEqual(texts("x = False\n", operator="constant"), ["x = True\n"])
        self.assertEqual(texts("x = 0\n", operator="constant"), ["x = 1\n"])
        self.assertEqual(texts("x = 1\n", operator="constant"), ["x = 0\n"])
        self.assertEqual(texts("x = 41\n", operator="constant"), ["x = 42\n"])
        self.assertEqual(texts("x = -1\n", operator="constant"), ["x = -0\n"])
        self.assertEqual(texts("x = 0x10\n", operator="constant"), ["x = 17\n"])
        self.assertEqual(texts("x = 1_000\n", operator="constant"), ["x = 1001\n"])
        self.assertEqual(texts("x = 'a'; y = 1.5; z = None; w = 2j\n", operator="constant"), [])

    def test_return(self):
        self.assertEqual(texts("def f():\n    return a, b\n", operator="return"), ["def f():\n    return None\n"])
        self.assertEqual(texts("def f():\n    return\n", operator="return"), [])
        self.assertEqual(texts("def f():\n    return None\n", operator="return"), [])
        self.assertEqual(texts("f = lambda: 1\n", operator="return"), [])

    def test_call_statement(self):
        self.assertEqual(texts("def f():\n    save(x)\n", operator="call"), ["def f():\n    pass\n"])
        self.assertEqual(texts("x = save(x)\n", operator="call"), [])  # the value is used: not a statement
        for kept in ("print(x)\n", "logger.info(x)\n", "self.log.debug(x)\n", "logging.warning(x)\n",
                     "warnings.warn(x)\n", "self._logger.exception(x)\n"):
            self.assertEqual(texts(kept, operator="call"), [], kept)
        self.assertEqual(len(texts("catalog.error(x)\n", operator="call")), 1)  # not a logger


class ChangedLinesOnly(unittest.TestCase):
    CODE = "a = 1 + 2\nb = 3 + 4\nc = 5 + 6\n"

    def test_only_the_changed_line(self):
        self.assertEqual({c.line for c, _ in mutate(self.CODE, {2})}, {2})

    def test_operator_on_an_unchanged_line_of_a_multiline_expression(self):
        code = "total = (a +\n         b)\n"
        self.assertEqual(texts(code, {2}, "arithmetic"), [])
        self.assertEqual(texts(code, {1}, "arithmetic"), ["total = (a -\n         b)\n"])

    def test_operator_after_a_comment_on_the_next_line(self):
        code = "total = (a  # first + not this\n         + b)\n"
        self.assertEqual(texts(code, {2}, "arithmetic"), ["total = (a  # first + not this\n         - b)\n"])
        self.assertEqual(texts(code, {1}, "arithmetic"), [])

    def test_statement_mutations_when_any_of_their_lines_changed(self):
        code = "def f():\n    save(\n        x,\n    )\n    return (\n        y\n    )\n"
        found = {c.operator: c.line for c, _ in mutate(code, {3, 6})}
        self.assertEqual(found, {"call": 3, "return": 6})
        self.assertEqual(mutate(code, {1}), [])


class Positions(unittest.TestCase):
    def test_non_ascii_before_the_operator(self):
        # ast columns are UTF-8 bytes; the string before `+` is 2 bytes per character
        code = 's = "ééé"; t = a + b\n'
        self.assertEqual(texts(code, operator="arithmetic"), ['s = "ééé"; t = a - b\n'])

    def test_crlf_and_lone_cr_newlines_are_kept(self):
        self.assertEqual(texts("x = 1\r\ny = a + b\r\n", {2}, "arithmetic"), ["x = 1\r\ny = a - b\r\n"])
        self.assertEqual(texts("x = 1\ry = a + b\r", {2}, "arithmetic"), ["x = 1\ry = a - b\r"])

    def test_tabs(self):
        self.assertEqual(texts("if x:\n\treturn a + b\n", {2}, "arithmetic"), ["if x:\n\treturn a - b\n"])

    def test_fstrings(self):
        found = texts('s = f"{a + 1} + {b}"\n')
        if sys.version_info >= (3, 12):
            self.assertIn('s = f"{a - 1} + {b}"\n', found)
            self.assertNotIn('s = f"{a + 1} - {b}"\n', found)  # the `+` in the literal part is text
        else:
            self.assertEqual(found, [])  # positions inside f-strings are unreliable before 3.12

    def test_latin1_source_round_trip(self):
        data = "# -*- coding: latin-1 -*-\nname = 'café'\nx = a + b\n".encode("latin-1")
        text, encoding = dm.read_source(data)
        self.assertEqual(encoding, "iso-8859-1")
        (cand, mutated), = [(c, t) for c, t in mutate(text, {3}) if c.operator == "arithmetic"]
        self.assertEqual(mutated.encode(encoding), data.replace(b"a + b", b"a - b"))

    def test_bom_round_trip(self):
        data = b"\xef\xbb\xbfx = a + b\n"
        text, encoding = dm.read_source(data)
        (cand, mutated), = mutate(text, {1})
        self.assertEqual(mutated.encode(encoding), b"\xef\xbb\xbfx = a - b\n")

    def test_before_and_after_lines(self):
        code = "def f(x):\n    if x < 3:\n        return 1\n"
        m = dm.Mutator("m.py", code, {2})
        sel, total, skipped = dm.select({"m.py": (m.src, m.tree, m.run())}, 10)
        comparison = [c for c in sel if c.operator == "comparison"][0]
        self.assertEqual((comparison.before, comparison.after), ("if x < 3:", "if x <= 3:"))
        self.assertEqual(comparison.line, 2)

    def test_secrets_on_a_mutated_line_are_masked(self):
        token = "ghp_" + "a" * 36
        code = f"connect(token='{token}', retries=3)\n"
        m = dm.Mutator("m.py", code, {1})
        sel, _, _ = dm.select({"m.py": (m.src, m.tree, m.run())}, 10)
        for c in sel:
            self.assertNotIn(token, c.before + c.after + c.description)


class Selection(unittest.TestCase):
    def build(self, code, changed=None):
        m = dm.Mutator("m.py", code, changed or set(range(1, 20)))
        return {"m.py": (m.src, m.tree, m.run())}

    def test_every_line_gets_a_mutant_before_any_gets_a_second(self):
        files = self.build("a = 1 + 2 - 3\nb = 4 + 5 - 6\nc = 7 + 8 - 9\n")
        sel, total, _ = dm.select(files, 3)
        self.assertEqual(sorted(c.line for c in sel), [1, 2, 3])
        self.assertEqual(total, 15)
        sel, _, _ = dm.select(self.build("a = 1 + 2 - 3\nb = 4 + 5 - 6\nc = 7 + 8 - 9\n"), 5)
        self.assertEqual(sorted(c.line for c in sel), [1, 1, 2, 2, 3])

    def test_identical_mutants_run_once(self):
        # `not` removal and a `return None` can never coincide, but two `+` in one expression give distinct texts;
        # a duplicate needs the same edit twice, which a doubled candidate simulates
        files = self.build("x = a + b\n")
        src, tree, cands = files["m.py"]
        twice = {"m.py": (src, tree, cands + cands)}
        sel, total, skipped = dm.select(twice, 10)
        self.assertEqual((len(sel), total, skipped), (1, 2, 1))

    def test_deep_expressions_do_not_crash(self):
        code = "x = " + " + ".join(["a"] * 1500) + "\n"
        try:
            files = self.build(code, {1})
        except RecursionError:
            self.skipTest("this Python's parser refuses the expression")  # prepare() reports it as unparsable
        sel, total, skipped = dm.select(files, 5)
        self.assertLessEqual(len(sel), 5)


class Differences(unittest.TestCase):
    def test_counts(self):
        a = ast.parse("x = a + b\n")
        self.assertEqual(dm.node_differences(a, ast.parse("x = a + b\n"), []), [])
        self.assertEqual(len(dm.node_differences(a, ast.parse("x = a - b\n"), [])), 1)
        self.assertEqual(len(dm.node_differences(a, ast.parse("y = a - b\n"), [])), 2)
        self.assertEqual(len(dm.node_differences(ast.parse("x = 1\n"), ast.parse("x = True\n"), [])), 1)

    def test_invalid_code_is_not_a_mutant(self):
        self.assertFalse(dm.valid_mutant(ast.parse("x = 1\n"), "x = = 1\n"))
        self.assertFalse(dm.valid_mutant(ast.parse("x = 1\n"), "x = 1\n"))  # no difference at all


if __name__ == "__main__":
    unittest.main()
