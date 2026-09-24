"""Tests that cannot fail: no assertion, assertions on constants, a swallowed assertion, an unconditional skip."""
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401

import diff_mutants as dm  # noqa: E402


def check(code: str, changed=None):
    code = textwrap.dedent(code)
    if changed is None:
        changed = set(range(1, code.count("\n") + 2))
    return dm.cannot_fail("tests/test_x.py", code, set(changed))


def kinds(code, changed=None):
    return {f["test"]: f["kind"] for f in check(code, changed)}


class NoAssertion(unittest.TestCase):
    def test_a_call_without_assertion(self):
        found = check("""
            def test_runs():
                result = compute(3)
        """)
        self.assertEqual([(f["test"], f["kind"], f["line"]) for f in found], [("test_runs", "no-assertion", 2)])
        self.assertIn("fails only if the code it calls raises", found[0]["detail"])

    def test_methods_of_test_classes(self):
        self.assertEqual(kinds("""
            import unittest
            class TestThing(unittest.TestCase):
                def test_nothing(self):
                    Thing().go()
                def test_something(self):
                    self.assertEqual(Thing().go(), 1)
                def helper(self):
                    pass
        """), {"TestThing.test_nothing": "no-assertion"})

    def test_things_that_count_as_assertions(self):
        for body in ("assert f() == 1", "self.assertEqual(f(), 1)", "m.assert_called_once_with(1)",
                     "np.testing.assert_allclose(f(), 1.0)", "subprocess.check_call(['x'])",
                     "expect(f()).to_equal(1)", "verify(f())", "self.fail('no')", "pytest.fail('no')",
                     "raise AssertionError('no')", "assert_that(f()).is_equal_to(1)", "check.equal(f(), 1)"):
            code = f"def test_x():\n    {body}\n"
            self.assertEqual(kinds(code), {}, body)

    def test_context_managers_that_assert(self):
        for code in ("def test_x():\n    with pytest.raises(ValueError):\n        f()\n",
                     "def test_x(self):\n    with self.assertRaises(ValueError):\n        f()\n",
                     "def test_x():\n    with pytest.warns(UserWarning):\n        f()\n",
                     "def test_x(self):\n    with self.assertLogs() as cm:\n        f()\n"):
            self.assertEqual(kinds(code), {}, code)

    def test_names_that_merely_start_like_assertion_helpers(self):
        # `checkout` and `expected` are not check/expect calls
        self.assertEqual(kinds("def test_x():\n    repo.checkout('main')\n    expected()\n"),
                         {"test_x": "no-assertion"})

    def test_local_helpers_are_followed(self):
        self.assertEqual(kinds("""
            def _check(v):
                assert v == 1
            def _noop(v):
                return v
            def test_helper():
                _check(f())
            def test_noop_helper():
                _noop(f())
            class TestC:
                def _verify_all(self, v):
                    assert v
                def _run(self, v):
                    self._verify_all(v)
                def test_method_helper(self):
                    self._run(f())
        """), {"test_noop_helper": "no-assertion"})

    def test_recursive_helpers_terminate(self):
        self.assertEqual(kinds("def loop(v):\n    return loop(v)\ndef test_x():\n    loop(1)\n"),
                         {"test_x": "no-assertion"})


class ConstantAssertions(unittest.TestCase):
    def test_classic_forms(self):
        for body, why in (("assert True", "the constant True"),
                          ("assert 'ok'", "the constant 'ok'"),
                          ("assert (f() == 1, 'message')", "non-empty tuple"),
                          ("result = f()\n    assert result == result", "an expression with itself"),
                          ("assert 1 == 1", "two constants"),
                          ("assert True or f() == 1", "`or` with a part that is always true"),
                          ("assert not None", "always true"),
                          ("self.assertTrue(True)", "assertTrue() on something that is always true"),
                          ("self.assertFalse(0)", "assertFalse() on something that is always false"),
                          ("r = f()\n    self.assertEqual(r, r)", "assertEqual() compares an expression with itself"),
                          ("self.assertEqual(2, 2)", "two equal constants"),
                          ("self.assertNotEqual(1, 2)", "two different constants"),
                          ("self.assertIsNotNone(3)", "assertIsNotNone() on a constant")):
            found = check(f"def test_x(self):\n    {body}\n")
            self.assertEqual([f["kind"] for f in found], ["constant-assertion"], body)
            self.assertIn(why, found[0]["detail"], body)

    def test_the_hacker_news_example(self):
        # "assert(true || expectedResult == actualResult)" in Python
        found = check("def test_x():\n    assert True or expected_result == actual_result\n")
        self.assertEqual(found[0]["kind"], "constant-assertion")

    def test_real_comparisons_are_live(self):
        for body in ("assert f() == f()", "assert x == y", "self.assertEqual(f(), 2)", "assert (x == 1)",
                     "assert [] == f()", "self.assertTrue(x)", "self.assertEqual(r[0], r[1])"):
            self.assertEqual(kinds(f"def test_x(self):\n    {body}\n"), {}, body)

    def test_one_live_assertion_is_enough(self):
        self.assertEqual(kinds("def test_x():\n    assert True\n    assert f() == 2\n"), {})


class Swallowed(unittest.TestCase):
    def test_except_that_does_not_reraise(self):
        for handler in ("except AssertionError:\n        pass", "except Exception:\n        pass",
                        "except:\n        pass", "except BaseException as e:\n        print(e)",
                        "except (ValueError, AssertionError):\n        return"):
            code = f"def test_x():\n    try:\n        assert f() == 2\n    {handler}\n"
            found = check(code)
            self.assertEqual([f["kind"] for f in found], ["swallowed-assertion"], handler)
            self.assertIn("line 3 inside the `try`/`with` at line 2", found[0]["detail"])

    def test_handlers_that_fail_the_test(self):
        for handler in ("except AssertionError:\n        raise", "except Exception as e:\n        self.fail(str(e))",
                        "except Exception:\n        pytest.fail('x')", "except ValueError:\n        pass",
                        "except Exception:\n        assert False"):
            code = f"def test_x(self):\n    try:\n        assert f() == 2\n    {handler}\n"
            self.assertEqual(kinds(code), {}, handler)

    def test_else_and_finally_are_not_protected(self):
        code = "def test_x():\n    try:\n        g()\n    except Exception:\n        pass\n    else:\n        assert f()\n"
        self.assertEqual(kinds(code), {})

    def test_suppress(self):
        code = "def test_x():\n    with contextlib.suppress(AssertionError):\n        assert f() == 1\n"
        self.assertEqual(kinds(code), {"test_x": "swallowed-assertion"})
        code = "def test_x():\n    with suppress(KeyError):\n        assert f() == 1\n"
        self.assertEqual(kinds(code), {})

    def test_pytest_outcomes_pass_through_except_exception(self):
        # pytest.raises/fail raise exceptions derived from BaseException
        code = "def test_x():\n    try:\n        with pytest.raises(ValueError):\n            f()\n" \
               "    except Exception:\n        pass\n"
        self.assertEqual(kinds(code), {})
        code = code.replace("except Exception", "except BaseException")
        self.assertEqual(kinds(code), {"test_x": "swallowed-assertion"})

    def test_self_fail_is_an_assertion_error(self):
        code = "def test_x(self):\n    try:\n        self.fail('x')\n    except Exception:\n        pass\n"
        self.assertEqual(kinds(code), {"test_x": "swallowed-assertion"})

    def test_nested_function_assertions_count(self):
        code = "def test_x():\n    def cb(v):\n        assert v == 1\n    run(cb)\n"
        self.assertEqual(kinds(code), {})


class Skipped(unittest.TestCase):
    def test_unconditional_skips(self):
        self.assertEqual(kinds("""
            import pytest, unittest
            @pytest.mark.skip
            def test_a():
                assert f()
            @pytest.mark.skip(reason="flaky")
            def test_b():
                assert f()
            @unittest.skip("later")
            def test_c():
                assert f()
            def test_d():
                pytest.skip("not now")
                assert f()
            class TestE(unittest.TestCase):
                def test_e(self):
                    self.skipTest("x")
                    self.assertTrue(f())
            @pytest.mark.xfail
            def test_f():
                assert f()
            @pytest.mark.xfail(reason="bug 12")
            def test_g():
                assert f()
        """), {n: "skipped" for n in ("test_a", "test_b", "test_c", "test_d", "TestE.test_e", "test_f", "test_g")})

    def test_conditional_skips_and_strict_xfail_are_left_alone(self):
        self.assertEqual(kinds("""
            @pytest.mark.skipif(sys.platform == "win32", reason="posix")
            def test_a():
                assert f()
            @unittest.skipIf(True, "x")
            def test_b():
                assert f()
            @pytest.mark.xfail(strict=True)
            def test_c():
                assert f()
            @pytest.mark.xfail(sys.version_info < (3, 10), reason="old")
            def test_d():
                assert f()
            def test_e():
                if fast:
                    pytest.skip("slow")
                assert f()
        """), {})

    def test_a_skipped_class(self):
        found = check("""
            @unittest.skip("broken")
            class TestK(unittest.TestCase):
                def test_k(self):
                    self.assertEqual(f(), 1)
        """)
        self.assertEqual(found[0]["kind"], "skipped")
        self.assertIn("its class TestK", found[0]["detail"])


class Scope(unittest.TestCase):
    CODE = "def test_old():\n    f()\n\n\ndef test_new():\n    g()\n"

    def test_only_tests_the_change_touched(self):
        self.assertEqual(kinds(self.CODE, {6}), {"test_new": "no-assertion"})
        self.assertEqual(kinds(self.CODE, {3, 4}), {})

    def test_a_decorator_line_counts_as_the_test(self):
        code = "import pytest\n\n@pytest.mark.skip\ndef test_x():\n    assert f()\n"
        self.assertEqual(kinds(code, {3}), {"test_x": "skipped"})

    def test_functions_not_named_test_are_ignored(self):
        self.assertEqual(kinds("def helper():\n    f()\n\n\ndef check_x():\n    f()\n"), {})

    def test_async_tests(self):
        self.assertEqual(kinds("async def test_x():\n    await f()\n"), {"test_x": "no-assertion"})


if __name__ == "__main__":
    unittest.main()
