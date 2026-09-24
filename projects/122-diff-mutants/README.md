# diff-mutants

**Would the tests that came with a change catch a bug in it?** `diff-mutants` runs mutation
testing on the Python lines a git change touched, and lists the changed tests that cannot fail.

## Why

Agents write tests quickly, and some of those tests pass whatever the code does. On an
LLM-driven project with about 2,500 tests, one developer reports having to prune, among others,
"no-op tests", "skipped tests set to skip because they were failing and the agent didn’t want to
fix them" and "tests that can never fail"
([Hacker News comment, 2026-03-04](https://news.ycombinator.com/item?id=47253538), read through
the Hacker News API on 2026-09-24).

Line coverage does not show this: a test that calls a function without checking its result still
covers every line it runs. Mutation testing does. Change the code a little, run the tests, and see
whether any of them fails. Doing that for a whole project takes a long time; a reviewer needs it
for the lines in front of them. `diff-mutants` makes one small change at a time on the lines the
change touched, runs your test command against each, and reports the ones no test noticed. It
also reads the test functions the change added or edited and names the ones that cannot fail.

## Example

A sample project, `shipping.py`, starts with a flat rate. The change below adds weight tiers and
an express surcharge, with two new tests. `test_heavy_parcel` asserts a price; `test_express`
calls the function and asserts nothing.

```python
def shipping_cost(weight_kg, express=False):
    """4.90 up to 2 kg, 7.90 above; express adds 5.00."""
    cost = 4.90 if weight_kg <= 2 else 7.90
    if express:
        cost += 5.00
    return cost


def test_light_parcel():                  # already there before the change
    assert shipping_cost(1) == 4.90


def test_heavy_parcel():
    assert shipping_cost(3) == 7.90


def test_express():
    shipping_cost(1, express=True)
```

EXAMPLE_OUTPUT

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/diff-mutants
/plugin install diff-mutants@diff-mutants
```

That adds a skill and nothing else (no hook). Ask "do my new tests actually test anything?" or
"would these tests catch a bug?", and Claude runs `diff-mutants` on the change and explains what
survived and which tests cannot fail. The skill pre-approves no command: a run executes your test
suite, so it goes through your normal permission prompt. The plugin runs `python3`, so it needs
`python3` on your `PATH`.

### Command line

No install, standard library only, one file:

```bash
# the newest code on main
curl -sL https://raw.githubusercontent.com/Keremozdemirra/diff-mutants/main/diff_mutants.py | python3 - --base main
# or a fixed release
curl -sL https://raw.githubusercontent.com/Keremozdemirra/diff-mutants/v0.1.0/diff_mutants.py | python3 - --base main
```

Or from PyPI, pinned to a release:

```bash
uvx diff-mutants@0.1.0 --base main
pipx run --spec diff-mutants==0.1.0 diff-mutants --base main
```

Run it inside the repository, with the environment your tests run in active. `diff-mutants` runs
your tests with that environment's interpreter, not its own: under `uvx` or `pipx` its own has
neither pytest nor your dependencies. `uvx diff-mutants` without a version installs the newest
release the first time and then reuses uv's cached copy ("After that, uvx will use the cached
version of the tool unless a different version is requested, the cache is pruned, or the cache is
refreshed", [uv docs](https://docs.astral.sh/uv/concepts/tools/), checked 2026-09-24);
`uvx diff-mutants@latest` refreshes it.

## Usage

```bash
diff-mutants                      # this branch against origin/HEAD, origin/main, origin/master, main or master
diff-mutants --base HEAD~1        # the last commit
diff-mutants --staged             # what is staged for the next commit
diff-mutants --dry-run            # list the mutants and check the tests; run nothing
```

| Option | What it does |
| --- | --- |
| `--base REF` | Compare `REF...HEAD`, as `git diff REF...HEAD` does: the changes since this branch left REF. Default: the first of `origin/HEAD`, `origin/main`, `origin/master`, `main`, `master` that exists. |
| `--staged` | Check the staged changes instead: the index against HEAD. |
| `--test-cmd CMD` | The command that runs your tests, through the shell (`sh -c` on Linux and macOS). It must exit non-zero when a test fails. Default: `python -m pytest -x -q` if pytest is importable, else `python -m unittest -f`. |
| `--timeout SECONDS` | Limit for each test run, the unmutated one included. Default: 10 s + 3 × the unmutated run. |
| `--max-mutants N` | Run at most N mutants (default 50), spread over the changed lines. |
| `--exclude GLOB` | Leave out changed files matching GLOB, such as `'scripts/*'`. Repeatable. |
| `-C PATH`, `--repo PATH` | The repository. Default: the current directory. |
| `--json` | Machine-readable output. |
| `--markdown` | Tables for a pull request comment. |
| `--strict` | Exit 1 when a mutant survived or a changed test cannot fail. |
| `--dry-run` | List the mutants and check the tests without running anything. |

The default interpreter is the active virtualenv's (`VIRTUAL_ENV`, or `CONDA_PREFIX`), else a
`.venv` or `venv` in the repository, else `python`, then `python3`, on `PATH`.

**Exit codes.** 2 when the run could not complete: not a git repository, no such base, the tests
fail, time out or run no tests before any mutation, interrupted, or a usage error. Otherwise 0,
whatever was found; with `--strict`, 1 when a mutant survived or a changed test cannot fail. A run
that could not complete exits 2 even with `--strict` and findings, so an unfinished check never
reads as a finished one.

### In CI

```yaml
- uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
  with:
    fetch-depth: 0          # the base branch has to be there to compare with
- uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
  with:
    python-version: "3.12"
- run: pip install -e . pytest
- run: pipx run --spec diff-mutants==0.1.0 diff-mutants --base origin/main --strict --markdown >> "$GITHUB_STEP_SUMMARY"
```

## What it mutates

One mutation at a time, only on changed lines, and only in files that are not test files.

| Operator | Mutation | Example |
| --- | --- | --- |
| arithmetic | `+` ↔ `-`, `*` ↔ `/`, `//` → `/`, `%` → `/`, `**` → `*`, and the same in `+=`, `-=` ... | `total + tax` → `total - tax` |
| comparison | `<` ↔ `<=`, `>` ↔ `>=`, `==` ↔ `!=`, `is` ↔ `is not`, `in` ↔ `not in` | `if n <= 2:` → `if n < 2:` |
| boolean | `and` ↔ `or` | `a and b` → `a or b` |
| not | `not x` → `x` | `if not ok:` → `if ok:` |
| constant | `True` ↔ `False`; integers `0` → `1`, `1` → `0`, any other `n` → `n + 1` | `range(10)` → `range(11)` |
| return | `return x` → `return None` | `return total` → `return None` |
| call | a call on a line of its own → `pass` | `cache.clear()` → `pass` |

- An operator counts when its own token is on a changed line; a `return` or a call statement
  counts when any of its lines changed.
- Left alone: files under `test/` or `tests/`, `test_*.py`, `*_test.py`, `conftest.py`; type
  annotations; `if __name__ == "__main__":`; calls to `print`, logging and `warnings.warn`, whose
  output tests seldom check; strings and floats.
- Before it runs, every mutant is parsed and compared with the original: it must be valid Python
  and differ from the original in exactly one node of the syntax tree. Where an operator swap
  would regroup the expression (`a or b and c`, `x * a ** b`), the mutant gets parentheses.
- Each changed line gets its first mutant before any line gets a second, up to `--max-mutants`.

## Tests that cannot fail

The check reads each test function (named `test*`, at module level or in a class, in a test file)
whose lines the change added or edited.

| Finding | What it means |
| --- | --- |
| `no-assertion` | No assertion at all. The test fails only if the code it calls raises. |
| `constant-assertion` | Every assertion is on constants: `assert True`, `assert (x == 1, "msg")` (a non-empty tuple), `assert result == result`, `assert True or expected == actual`, `self.assertEqual(r, r)`, `self.assertTrue(True)`. |
| `swallowed-assertion` | Every assertion sits inside a `try` whose `except` catches its failure (bare, `Exception`, `BaseException`, `AssertionError`) and does not re-raise, or inside `contextlib.suppress(...)` of such an exception. |
| `skipped` | Skipped unconditionally: `@pytest.mark.skip`, `@unittest.skip`, or `pytest.skip()` or `self.skipTest()` as a statement of the test body (not inside an `if`); also a test marked `xfail` or `expectedFailure` without a condition or `strict=True`, whose failure does not fail the run. |

Counted as assertions: `assert`, `raise`, calls with a name part that is `assert`, `check`,
`verify` or `expect`, or starts with one of them followed by `_` or a capital letter
(`self.assertEqual`, `mock.assert_called_once_with`, `subprocess.check_call`, `expect(x)`, but not
`repo.checkout`), `pytest.raises`, `pytest.warns`, `pytest.fail`, `self.fail`, and helpers
defined in the same file that contain one. A helper imported from another module is not
followed, so a test whose only assertion is inside one is reported as `no-assertion`.

## How a run works

1. **Changed lines.** `git diff --unified=0 <base>...HEAD` (or `git diff --cached`), Python files
   only. The changed files are read as committed (or staged): an unstaged edit on top is not
   used, and a note says so.
2. **The copy.** The working tree is copied to a temporary directory, without `.git`, virtual
   environments (a directory holding `pyvenv.cfg` or `conda-meta`), `node_modules`,
   `__pycache__` and tool caches. The changed files are then set to their committed or staged
   content, so the line numbers match the diff. A symlink into the tree points into the copy.
3. **The unmutated run.** The test command runs once on the copy. If it fails, times out, or runs
   no tests, the run stops with exit 2 and the end of its output.
4. **Each mutant.** Written into the copy, the test command runs, the file is restored. Exit 0:
   survived. Non-zero: killed. Over the timeout: timed out; the test command and every process it
   started are ended (SIGTERM, then SIGKILL after 2 s, to the whole process group). After a run
   that ends by itself, whatever it left running in its process group is ended too.
5. **Imports.** `PYTHONPATH` starts with the copy, its `src/` and the package roots of the changed
   files, so `import yourpackage` finds the mutant even when the project is installed in editable
   mode. Before the first mutant, a check asks the test interpreter where it would import each
   changed top-level module from, and stops the run if that is outside the copy.
6. **Clean-up.** The copy is removed at the end, after an error, and on Ctrl-C, SIGTERM or SIGHUP.

## Defaults

These are this tool's own choices, not a standard.

| Setting | Value |
| --- | --- |
| Mutants per run (`--max-mutants`) | 50 |
| Timeout per mutant, without `--timeout` | 10 s + 3 × the duration of the unmutated run |
| Limit for the unmutated run, without `--timeout` | 1,800 s |
| Grace between SIGTERM and SIGKILL | 2 s |
| Test output kept per run | the last 12 lines, at most 1,500 characters |

## What it reads, runs and sends

- **Reads:** the repository through git (`rev-parse`, `merge-base`, `diff`, `cat-file`), run
  with `GIT_OPTIONAL_LOCKS=0`, no pager and no prompts; and the working tree, when it copies it.
  `diff-mutants` never writes to the working tree, the index or `.git`. The tests check this with
  a hash of every file before and after a run, after an injected error, and after Ctrl-C and
  SIGTERM sent to a running process.
- **Runs:** your test command, once plus once per mutant, in the copy, with your environment
  plus `PYTHONDONTWRITEBYTECODE=1` and the `PYTHONPATH` above. That runs your project's code and
  tests, as running the tests yourself would. A test that writes to an absolute path writes
  there, as it would in a normal run.
- **Sends:** nothing. `diff-mutants` makes no network request; your tests may.
- **Prints:** text from your repository: code lines, test names, the end of the test output.
  Key-shaped tokens and URL credentials and query strings are masked everywhere; in the test
  command and the test output also `NAME=value` where the name looks like a secret, and
  `Authorization`/`Cookie` headers. Control and bidi characters are removed. In JSON the test
  output is wrapped as `<<test output, not an instruction: ...>>`, because the skill hands it to a
  model.

There is no data source: nothing is downloaded, so no licence or attribution applies.

## Limits

- Python only. Files are parsed with the Python that runs `diff-mutants`, so use one at least as
  new as your code's syntax; a file it cannot parse is reported and not mutated.
- The mutants share one copy, one after another: files your tests write stay there for the next
  run. `.git` and virtual environments are not in the copy; a `--test-cmd` that needs them must
  use absolute paths.
- A surviving mutant can be equivalent to the original: `x < low` → `x <= low` in a clamp that
  returns `low` either way. No test can catch it; the report cannot tell it apart.
- Tested on Linux: CI runs Ubuntu 24.04 with Python 3.9 and 3.12. On Windows the process tree is
  ended with `taskkill`, which is not tested.

## What this is not

- Not a full mutation-testing framework. For whole-project runs, use
  [mutmut](https://github.com/boxed/mutmut) (BSD-3-Clause; 3.8.0 on PyPI on 2026-09-24; between
  runs it re-tests only the functions whose source changed, and it needs `fork`, so on Windows it
  runs in WSL) or [cosmic-ray](https://github.com/sixty-north/cosmic-ray) (MIT; 8.7.0 on PyPI; its
  `cr-filter-git` step marks the mutants outside a `git diff` as skipped, so it can also be scoped
  to a change). `diff-mutants` has a short fixed list of operators, no configuration file, no
  cache between runs and no parallel runs; it adds the check for tests that cannot fail.
- Python only in version 0.1.
- Not a verdict. A surviving mutant is a change to the code that no test detected; a test listed
  here may still be useful as a smoke test. The report says what the tests check, not who wrote
  them or how well.

## Licence

MIT.
