"""End to end: the copy, the test runs, isolation, timeouts, exit codes and what gets printed."""
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import (CALC_BASE, CALC_CHANGE, CALC_THOROUGH_TESTS, PY, ROOT, UNITTEST, Isolated,  # noqa: E402
                     snapshot)

import diff_mutants as dm  # noqa: E402

POSIX = os.name == "posix"


def alive(pid: int) -> bool:
    """Running, as opposed to gone or a zombie nobody has reaped yet."""
    stat_file = Path(f"/proc/{pid}/stat")
    if stat_file.exists():
        try:
            return stat_file.read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
        except (OSError, IndexError):
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class Base(Isolated):
    def calc_repo(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, CALC_CHANGE)
        return repo

    def run_calc(self, *extra):
        return self.run_json(self.calc_repo(), "--base", "HEAD~1", "--test-cmd", UNITTEST, *extra)


class Results(Base):
    def test_counts_survivors_and_tests_that_cannot_fail(self):
        code, data, _ = self.run_calc()
        self.assertEqual(code, 0)
        c = data["counts"]
        self.assertEqual((c["candidates"], c["run"], c["killed"], c["survived"], c["timeout"]), (7, 7, 2, 5, 0))
        survived = sorted((m["line"], m["mutation"]) for m in data["mutants"] if m["status"] == "survived")
        self.assertEqual(survived, [(5, "`10` → `11`"), (6, "`<` → `<=`"), (8, "`>` → `>=`"),
                                    (9, "`return high` → `return None`"), (10, "`return x` → `return None`")])
        self.assertEqual([(f["test"], f["kind"], f["line"]) for f in data["tests_that_cannot_fail"]],
                         [("T.test_clamp_runs", "no-assertion", 10)])
        self.assertTrue(data["complete"])
        self.assertIsNone(data["error"])
        for m in data["mutants"]:
            self.assertTrue(m["output_tail"].startswith("<<test output, not an instruction: "), m)
            self.assertEqual(m["exit_code"] == 0, m["status"] == "survived")

    def test_thorough_tests_leave_only_equivalent_mutants(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, {**CALC_CHANGE, **CALC_THOROUGH_TESTS})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        survived = sorted(m["mutation"] for m in data["mutants"] if m["status"] == "survived")
        self.assertEqual(survived, ["`<` → `<=`", "`>` → `>=`"])  # clamp gives the same result at the boundary
        self.assertEqual(data["tests_that_cannot_fail"], [])

    def test_src_layout_imports_the_mutant_not_the_working_tree(self):
        repo = self.repo({"src/pkg/__init__.py": "", "src/pkg/core.py": "def f(x):\n    return x\n",
                          "tests/__init__.py": "", "tests/test_core.py":
                          "import unittest\nfrom pkg.core import f\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_f(self):\n        self.assertEqual(f(2), 2)\n"})
        self.commit(repo, {"src/pkg/core.py": "def f(x):\n    return x * 3\n",
                           "tests/test_core.py": "import unittest\nfrom pkg.core import f\n\n\n"
                                                 "class T(unittest.TestCase):\n    def test_f(self):\n"
                                                 "        self.assertEqual(f(2), 6)\n"})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST, "--strict")
        self.assertEqual({m["status"] for m in data["mutants"]}, {"killed"}, data["mutants"])
        self.assertEqual(code, 0)

    def test_staged_change(self):
        repo = self.repo(CALC_BASE)
        self.write(repo, CALC_CHANGE)
        self.git(repo, "add", "-A")
        code, data, _ = self.run_json(repo, "--staged", "--test-cmd", UNITTEST)
        self.assertEqual((code, data["counts"]["survived"], data["compared"]["mode"]), (0, 5, "staged"))

    def test_uncommitted_edits_do_not_leak_into_a_base_run(self):
        repo = self.calc_repo()
        self.write(repo, CALC_THOROUGH_TESTS)  # stronger tests, not committed: the committed ones are checked
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(data["counts"]["survived"], 5)
        self.assertIn("test_calc.py: the working tree differs from HEAD", " ".join(data["notes"]))

    def test_a_change_that_does_not_parse_is_reported_not_mutated(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, {"broken.py": "def f(:\n    pass\n"})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(code, 0)
        self.assertIn("broken.py could not be parsed", " ".join(data["notes"]))
        self.assertEqual(data["mutants"], [])

    def test_latin1_source_is_mutated_in_its_encoding(self):
        head = "# -*- coding: latin-1 -*-\n"
        repo = self.repo({"m.py": (head + "NAME = 'café'\n").encode("latin-1"),
                          "test_m.py": "import unittest\nimport m\n\n\nclass T(unittest.TestCase):\n"
                                       "    def test_n(self):\n        self.assertEqual(m.NAME, 'caf\\xe9')\n"
                                       "        self.assertEqual(m.twice(2), 4)\n"})
        self.commit(repo, {"m.py": (head + "NAME = 'café'\n\n\ndef twice(x):\n    return x * 2\n").encode("latin-1")})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual({m["status"] for m in data["mutants"]}, {"killed"}, data["mutants"])

    def test_unicode_file_name_and_line(self):
        repo = self.repo({"größe.py": "LABEL = 'ö'\n", "test_g.py": "import unittest\nimport importlib\n"
                          "g = importlib.import_module('größe')\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_g(self):\n        self.assertEqual(g.LABEL, 'ö')\n"})
        self.commit(repo, {"größe.py": "LABEL = 'ö'\nSIZE = 3  # Größe\n"})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        (m,) = data["mutants"]
        self.assertEqual((m["file"], m["status"], m["after"]), ("größe.py", "survived", "SIZE = 4  # Größe"))
        code, out, _ = self.run_main(["-C", repo, "--base", "HEAD~1", "--test-cmd", UNITTEST])
        self.assertIn("größe.py:2", out)

    def test_nothing_changed(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, {"README.txt": "docs\n"})
        code, out, _ = self.run_main(["-C", repo, "--base", "HEAD~1", "--strict"])
        self.assertEqual(code, 0)
        self.assertIn("No changed Python lines.", out)

    def test_dry_run_runs_nothing(self):
        repo = self.calc_repo()
        with mock.patch("diff_mutants.run_command", side_effect=AssertionError("ran a test")):
            code, out, _ = self.run_main(["-C", repo, "--base", "HEAD~1", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("Mutants that would run (7):", out)
        self.assertIn("T.test_clamp_runs: no assertion", out)
        self.assertEqual(self.leftovers(), [])

    def test_max_mutants_spreads_over_lines(self):
        code, data, _ = self.run_calc("--max-mutants", "3")
        self.assertEqual(len({m["line"] for m in data["mutants"]}), 3)
        self.assertEqual(data["counts"]["not_run"], 4)
        self.assertIn("4 more mutants were not run (--max-mutants 3)", " ".join(data["notes"]))


class Isolation(Base):
    def test_working_tree_index_and_git_dir_are_untouched(self):
        repo = self.calc_repo()
        (repo / "untracked.txt").write_text("keep me\n", encoding="utf-8")
        before = snapshot(repo)
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(data["counts"]["run"], 7)
        self.assertEqual(snapshot(repo), before)
        self.assertEqual(self.leftovers(), [])

    def test_tests_that_write_files_write_them_in_the_copy(self):
        repo = self.repo(CALC_BASE)
        change = dict(CALC_CHANGE)
        change["test_calc.py"] += "\n\nopen('written-by-tests.txt', 'w').close()\n"
        self.commit(repo, change)
        before = snapshot(repo)
        self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(snapshot(repo), before)

    def test_an_unexpected_error_mid_run_still_cleans_up(self):
        repo = self.calc_repo()
        before = snapshot(repo)
        real, calls = dm.run_command, []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("injected")
            return real(*a, **kw)

        with mock.patch("diff_mutants.run_command", flaky):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.run_main(["-C", repo, "--base", "HEAD~1", "--test-cmd", UNITTEST])
        self.assertEqual(snapshot(repo), before)
        self.assertEqual(self.leftovers(), [])

    def test_ctrl_c_mid_run_reports_what_it_has_and_cleans_up(self):
        repo = self.calc_repo()
        before = snapshot(repo)
        real, calls = dm.run_command, []

        def interrupted(*a, **kw):
            calls.append(1)
            if len(calls) == 4:  # the baseline, two mutants, then Ctrl-C
                raise KeyboardInterrupt
            return real(*a, **kw)

        with mock.patch("diff_mutants.run_command", interrupted):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(code, 2)
        self.assertEqual(data["error"], "interrupted after 2 of 7 mutants")
        self.assertEqual(data["counts"]["run"], 2)
        self.assertFalse(data["complete"])
        self.assertEqual(snapshot(repo), before)
        self.assertEqual(self.leftovers(), [])

    def test_a_write_error_is_a_clean_stop(self):
        repo = self.calc_repo()
        real, calls = dm.write_inside, []

        def failing(root, rel, data):
            calls.append(rel)
            if len(calls) > 2:
                raise OSError(28, "No space left on device")
            return real(root, rel, data)

        with mock.patch("diff_mutants.write_inside", failing):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(code, 2)
        self.assertIn("No space left on device", data["error"])
        self.assertEqual(self.leftovers(), [])

    def test_writes_never_leave_the_copy(self):
        copy, outside = self.tmp / "copy", self.tmp / "outside"
        copy.mkdir()
        outside.mkdir()
        (copy / "pkg").symlink_to(outside, target_is_directory=True)
        for rel in ("pkg/x.py", "../x.py", "/etc/x.py"):
            with self.assertRaises(dm.Stop, msg=rel):
                dm.write_inside(copy, rel, b"x = 1\n")
        self.assertEqual(list(outside.iterdir()), [])

    def test_the_copy_leaves_out_git_environments_and_caches(self):
        src = self.tmp / "src"
        self.write(src, {"a.py": "x\n", ".git/config": "", ".venv/pyvenv.cfg": "", "env2/pyvenv.cfg": "",
                         "node_modules/m/index.js": "", "pkg/__pycache__/a.cpython-311.pyc": "",
                         ".pytest_cache/v": "", "data/keep.txt": "k\n"})
        (src / "inside").symlink_to("data/keep.txt")
        (src / "outside").symlink_to(self.home)
        notes = []
        dm.copy_tree(src, self.tmp / "dst", notes)
        got = sorted(p.relative_to(self.tmp / "dst").as_posix() for p in (self.tmp / "dst").rglob("*"))
        self.assertEqual(got, ["a.py", "data", "data/keep.txt", "inside", "outside", "pkg"])
        self.assertEqual(os.readlink(self.tmp / "dst" / "inside"), "data/keep.txt")
        self.assertEqual(os.readlink(self.tmp / "dst" / "outside"), str(self.home))
        self.assertEqual(notes, [])

    @unittest.skipUnless(POSIX, "signals and process groups")
    def test_real_sigint_and_sigterm(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig.name):
                self._signal_run(sig)

    def _signal_run(self, sig):
        repo = self.calc_repo() if not (self.tmp / "project").exists() else self.tmp / "project"
        started = self.tmp / f"started-{sig.name}"
        script = self.tmp / "slow_tests.py"
        # The first run (the baseline) passes and leaves a marker in the copy; the next one sleeps.
        script.write_text("import os, sys, time\n"
                          "if os.path.exists('marker.tmp'):\n"
                          f"    open({str(started)!r}, 'w').write(str(os.getpid()))\n"
                          "    time.sleep(60)\n"
                          "open('marker.tmp', 'w').close()\n", encoding="utf-8")
        before = snapshot(repo)
        env = dict(os.environ)
        proc = subprocess.Popen([PY, str(ROOT / "diff_mutants.py"), "-C", str(repo), "--base", "HEAD~1", "--json",
                                 "--test-cmd", f'"{PY}" "{script}"'], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env)
        deadline = time.monotonic() + 30
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists(), "the slow test run never started")
        time.sleep(0.2)
        child = int(started.read_text() or 0)
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 2, err)
        data = json.loads(out)
        self.assertEqual(data["error"], "interrupted after 0 of 7 mutants")
        for _ in range(50):
            if not alive(child):
                break
            time.sleep(0.1)
        self.assertFalse(alive(child), "the test process outlived diff-mutants")
        self.assertEqual(snapshot(repo), before)
        self.assertEqual(self.leftovers(), [])


class Timeouts(Base):
    LOOP_BASE = {"loop.py": "X = 1\n", "test_loop.py": "import unittest\n"}
    LOOP_CHANGE = {
        "loop.py": "X = 1\n\n\ndef countdown(n):\n    steps = 0\n    while n > 0:\n        n -= 1\n"
                   "        steps += 1\n    return steps\n",
        "test_loop.py": "import unittest\nfrom loop import countdown\n\n\nclass T(unittest.TestCase):\n"
                        "    def test_countdown(self):\n        self.assertEqual(countdown(3), 3)\n",
    }

    def test_a_mutant_that_never_ends_times_out_and_the_run_goes_on(self):
        repo = self.repo(self.LOOP_BASE)
        self.commit(repo, self.LOOP_CHANGE)
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST, "--timeout", "2", "--strict")
        timeouts = sorted(m["mutation"] for m in data["mutants"] if m["status"] == "timeout")
        self.assertEqual(timeouts, ["`-=` → `+=`", "`1` → `0`"])
        self.assertEqual(data["counts"]["survived"], 0)
        self.assertEqual(code, 0)  # a timeout counts as caught
        self.assertTrue(all(m["exit_code"] is None for m in data["mutants"] if m["status"] == "timeout"))

    def test_the_baseline_must_finish_within_the_timeout(self):
        repo = self.calc_repo()
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--timeout", "1",
                                      "--test-cmd", f'"{PY}" -c "import time; time.sleep(5)"')
        self.assertEqual(code, 2)
        self.assertIn("did not finish within 1 s on the unmutated code", data["error"])
        self.assertEqual(self.leftovers(), [])

    @unittest.skipUnless(POSIX, "process groups")
    def test_the_whole_process_group_is_ended(self):
        work = self.tmp / "w"
        work.mkdir()
        result = dm.run_command("sleep 30 & echo $! > pid.txt; wait", work, dict(os.environ), 1)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        pid = int((work / "pid.txt").read_text())
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        self.assertFalse(alive(pid), "a grandchild of the test command survived the timeout")

    def test_output_is_bounded(self):
        work = self.tmp / "w"
        work.mkdir()
        cmd = [PY, "-c", "import sys\nfor i in range(200000): sys.stdout.write('x' * 40 + '\\n')\nprint('LAST')"]
        result = dm.run_command(cmd, work, dict(os.environ), 60)
        self.assertEqual(result.exit_code, 0)
        self.assertLessEqual(len(result.tail), 1500)
        self.assertTrue(result.tail.endswith("LAST"))

    def test_a_command_that_does_not_exist(self):
        repo = self.calc_repo()
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", "no-such-test-runner-xyz")
        self.assertEqual(code, 2)
        self.assertIn("the test command fails on the unmutated code", data["error"])


class ExitCodes(Base):
    DOUBLE_BASE = {"d.py": "X = 1\n", "test_d.py": "import unittest\n"}
    DOUBLE_CHANGE = {"d.py": "X = 1\n\n\ndef double(x):\n    return x * 2\n",
                     "test_d.py": "import unittest\nfrom d import double\n\n\nclass T(unittest.TestCase):\n"
                                  "    def test_double(self):\n        self.assertEqual(double(3), 6)\n"}

    def test_strict_is_1_when_a_mutant_survives(self):
        self.assertEqual(self.run_calc("--strict")[0], 1)

    def test_without_strict_findings_exit_0(self):
        self.assertEqual(self.run_calc()[0], 0)

    def test_strict_is_0_when_every_mutant_is_killed(self):
        repo = self.repo(self.DOUBLE_BASE)
        self.commit(repo, self.DOUBLE_CHANGE)
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST, "--strict")
        self.assertEqual((code, data["counts"]["killed"], data["counts"]["run"]), (0, 3, 3))

    def test_strict_is_1_for_a_test_that_cannot_fail_alone(self):
        repo = self.repo(self.DOUBLE_BASE)
        self.commit(repo, {"test_d.py": "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                        "    def test_x(self):\n        self.assertTrue(True)\n"})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--strict")
        self.assertEqual((code, data["counts"]["run"]), (1, 0))
        self.assertEqual(data["tests_that_cannot_fail"][0]["kind"], "constant-assertion")

    def test_2_when_the_tests_fail_before_any_mutation(self):
        repo = self.calc_repo()
        for extra in ([], ["--strict"]):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", f'"{PY}" -c "raise SystemExit(1)"',
                                          *extra)
            self.assertEqual(code, 2)
            self.assertIn("exit 1", data["error"])
        self.assertEqual(self.leftovers(), [])

    def test_2_outside_a_repository_and_for_a_bad_base(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        code, out, _ = self.run_main(["-C", plain])
        self.assertEqual(code, 2)
        self.assertIn("not inside a git working tree", out)
        repo = self.calc_repo()
        self.assertEqual(self.run_main(["-C", repo, "--base", "no-such-branch"])[0], 2)

    def test_usage_errors_exit_2(self):
        for argv in (["--max-mutants", "0"], ["--timeout", "-1"], ["--timeout", "soon"], ["--staged", "--base", "x"],
                     ["--json", "--markdown"], ["--test-cmd", "  "]):
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
                dm.main(argv)
            self.assertEqual(cm.exception.code, 2, argv)


class Output(Base):
    def test_text(self):
        repo = self.calc_repo()
        code, out, _ = self.run_main(["-C", repo, "--base", "HEAD~1", "--test-cmd", UNITTEST])
        self.assertIn("Survived: the tests still pass with each of these 5 changes to the code", out)
        self.assertIn("  calc.py:9  `return high` → `return None`\n      - return high\n      + return None\n", out)
        self.assertIn("Tests that cannot fail\n  test_calc.py:10  T.test_clamp_runs: no assertion", out)
        self.assertIn("7 mutants run: 2 killed, 5 survived, 0 timed out. 1 test cannot fail.", out)

    def test_markdown(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, {"calc.py": CALC_BASE["calc.py"] + "\nSEP = 'a|b'; N = 1\n"})
        code, out, _ = self.run_main(["-C", repo, "--base", "HEAD~1", "--test-cmd", UNITTEST, "--markdown"])
        self.assertTrue(out.startswith("### diff-mutants: 1 of 1 mutant survived, 0 tests cannot fail\n"), out)
        self.assertIn("| `calc.py:4` | `1` → `0` | `SEP = 'a\\|b'; N = 0` |", out)

    def test_secrets_are_masked_everywhere(self):
        token = "ghp_" + "b" * 36
        repo = self.repo(CALC_BASE)
        change = dict(CALC_CHANGE)
        change["test_calc.py"] = f"print('using', 'API_TOKEN={token}')\n" + change["test_calc.py"]
        self.commit(repo, change)
        cmd = f"API_TOKEN={token} {UNITTEST}"
        for fmt in ([], ["--json"], ["--markdown"]):
            code, out, err = self.run_main(["-C", repo, "--base", "HEAD~1", "--test-cmd", cmd, *fmt])
            self.assertNotIn(token, out + err, fmt)
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", cmd)
        self.assertTrue(data["test_command"].startswith("API_TOKEN=*** "), data["test_command"])
        survivor = [m for m in data["mutants"] if m["status"] == "survived"][0]  # short output: the print is in it
        self.assertIn("using API_TOKEN=***", survivor["output_tail"])

    def test_control_characters_in_test_output(self):
        work = self.tmp / "w"
        work.mkdir()
        cmd = [PY, "-c", "print('\\x1b[31mred\\x1b[0m \\x07bell \\u202eevil')"]
        tail = dm.run_command(cmd, work, dict(os.environ), 30).tail
        self.assertEqual(tail, "red  bell  evil")

    def test_json_error_shape(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        code, data, err = self.run_json(plain)
        self.assertEqual((code, data["complete"], data["counts"]), (2, False, {}))
        self.assertIn("not inside a git working tree", data["error"])
        self.assertIn("diff-mutants:", err)


class Interpreter(Isolated):
    def test_active_environment_first(self):
        venv = self.tmp / "venv-active"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").write_text("")
        repo = self.tmp / "r"
        (repo / ".venv" / "bin").mkdir(parents=True)
        (repo / ".venv" / "bin" / "python").write_text("")
        with mock.patch.dict(os.environ, {"VIRTUAL_ENV": str(venv)}):
            self.assertEqual(dm.resolve_python(repo), str(venv / "bin" / "python"))
        self.assertEqual(dm.resolve_python(repo), str(repo / ".venv" / "bin" / "python"))

    def test_path_then_this_interpreter(self):
        repo = self.tmp / "r"
        repo.mkdir()
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(dm.resolve_python(repo), sys.executable)
        with mock.patch("shutil.which", side_effect=lambda n: "/opt/py/python3" if n == "python3" else None):
            self.assertEqual(dm.resolve_python(repo), "/opt/py/python3")

    def test_pytest_when_importable_else_unittest(self):
        work = self.tmp / "w"
        work.mkdir()
        env = dict(os.environ, PYTHONPATH=str(work))
        has_pytest = subprocess.run([PY, "-c", "import pytest"], capture_output=True).returncode == 0
        expected = ["-m", "pytest", "-x", "-q"] if has_pytest else ["-m", "unittest", "-f"]
        self.assertEqual(dm.default_command(PY, work, env)[1:], expected)
        (work / "pytest.py").write_text("")  # an importable pytest
        self.assertEqual(dm.default_command(PY, work, env)[1:], ["-m", "pytest", "-x", "-q"])
        self.assertEqual(dm.default_command(str(self.tmp / "no-python"), work, env)[1:], ["-m", "unittest", "-f"])

    def test_default_command_end_to_end(self):
        repo = self.repo(CALC_BASE)
        self.commit(repo, CALC_CHANGE)
        with mock.patch("diff_mutants.resolve_python", return_value=PY):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1")
        self.assertEqual(code, 0, data["error"])
        self.assertTrue(data["test_command"].endswith(("-m unittest -f", "-m pytest -x -q")), data["test_command"])
        self.assertEqual(data["counts"]["survived"], 5)

    def test_import_probe(self):
        copy, outside = self.tmp / "copy", self.tmp / "outside"
        for d in (copy / "src" / "mypkg", outside / "mypkg"):
            d.mkdir(parents=True)
            (d / "__init__.py").write_text("")
        (copy / "src" / "mypkg" / "core.py").write_text("")
        names = dm.module_names(copy, ["src/mypkg/core.py"])
        self.assertEqual(names, ["mypkg"])
        env = dict(os.environ, PYTHONPATH=str(outside))
        self.assertEqual(dm.probe_imports(PY, copy, env, names), [f"mypkg from {outside / 'mypkg'}"])
        roots = [str(r) for r in dm.import_roots(copy, ["src/mypkg/core.py"])]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(roots + [str(outside)]))
        self.assertEqual(dm.probe_imports(PY, copy, env, names), [])
        self.assertEqual(dm.probe_imports(PY, copy, env, ["os", "json"]), [])  # the standard library is not ours

    def test_a_probe_that_cannot_run_says_nothing(self):
        self.assertEqual(dm.probe_imports(str(self.tmp / "no-python"), self.tmp, dict(os.environ), ["x"]), [])


if __name__ == "__main__":
    unittest.main()


class EmptyRuns(Base):
    PYTEST_STYLE = {"calc.py": "def add(a, b):\n    return a + b\n",
                    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}

    def test_a_baseline_that_runs_no_tests_stops_the_run(self):
        # unittest finds no pytest-style tests: before 3.12 it prints "Ran 0 tests" and exits 0
        repo = self.repo(self.PYTEST_STYLE)
        self.commit(repo, {"calc.py": "def add(a, b):\n    return a + b + 0\n"})
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST, "--strict")
        self.assertEqual(code, 2)
        self.assertIn("the test command ran no tests", data["error"])
        self.assertEqual(data["counts"]["run"], 0)

    def test_the_hint_names_the_missing_pytest(self):
        repo = self.repo(self.PYTEST_STYLE)
        self.commit(repo, {"calc.py": "def add(a, b):\n    return a + b + 0\n"})
        with mock.patch("diff_mutants.resolve_python", return_value=PY), \
                mock.patch("diff_mutants.default_command", return_value=[PY, "-m", "unittest", "-f"]):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1")
        self.assertEqual(code, 2)
        self.assertIn("pytest is not importable by", data["error"])
        self.assertIn("so unittest ran instead", data["error"])

    def test_exit_5_is_an_empty_run(self):
        repo = self.calc_repo()
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", f'"{PY}" -c "raise SystemExit(5)"')
        self.assertEqual(code, 2)
        self.assertIn("ran no tests (exit 5)", data["error"])

    def test_when_every_mutant_survives_there_is_a_note(self):
        repo = self.calc_repo()
        code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", f'"{PY}" -c "print(1)"')
        self.assertEqual(data["counts"]["survived"], 7)
        self.assertIn("every mutant survived", " ".join(data["notes"]))


class SystemErrors(Base):
    def test_no_temporary_directory(self):
        repo = self.calc_repo()
        with mock.patch("tempfile.mkdtemp", side_effect=PermissionError(13, "Permission denied", "/tmp/x")):
            code, data, _ = self.run_json(repo, "--base", "HEAD~1", "--test-cmd", UNITTEST)
        self.assertEqual(code, 2)
        self.assertEqual(data["error"], "Permission denied (/tmp/x)")

    def test_a_file_is_not_a_repository(self):
        f = self.tmp / "file.txt"
        f.write_text("x")
        code, out, _ = self.run_main(["-C", f])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", out)

    @unittest.skipUnless(POSIX, "process groups")
    def test_background_processes_do_not_outlive_a_passing_run(self):
        work = self.tmp / "w"
        work.mkdir()
        result = dm.run_command("sleep 30 & echo $! > pid.txt; exit 0", work, dict(os.environ), 20)
        self.assertEqual(result.exit_code, 0)
        pid = int((work / "pid.txt").read_text())
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        self.assertFalse(alive(pid))
        self.assertLess(result.seconds, 10)
