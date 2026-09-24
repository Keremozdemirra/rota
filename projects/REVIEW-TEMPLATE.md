# Adversarial review: how to review a project in this batch

You review one project under `/home/user/rota/projects/<NNN-slug>/` before it is published as a
public repository and a PyPI package. Assume it is wrong somewhere and find where. Read-only:
do not modify any file in the project; write scratch files only under
`/tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/review-<NNN>/`.

## Rules for you

- Never read real user configuration or credential files (`~/.claude.json`, `~/.config`, keychains,
  `.env`). Run the project's code and tests with `HOME` pointed at an empty scratch directory.
- Do not fetch content from github.com / raw.githubusercontent.com repositories other than the
  owner's; GitHub API calls return 403 in this sandbox by design.
- Check external claims against primary sources (legal acts via EUR-Lex/CELLAR, licence pages, API
  docs). Quote the sentence you relied on and the URL.

## What to check

1. The standards in `/tmp/claude-0/-home-user/46610765-d3a5-5dc6-8c0f-75f635a72ba6/scratchpad/BUILD-STANDARDS.md`,
   especially the final "Lessons" section — every point is a checklist item.
2. Correctness of the core logic with adversarial inputs you construct (edge cases, malformed data,
   unicode, huge inputs, network failures via mocked urlopen). Run things; do not only read.
3. Privacy and safety: nothing secret or personal leaves the machine or reaches output; third-party
   text entering an agent's context is wrapped and truncated; no unvalidated string is sent to the
   network; hooks never deny and fail open.
4. Every claim in the README and in tool descriptions: literally true, sourced, dated. Numbers,
   thresholds, legal statements, licence statements, "real output" examples (re-run them).
5. Data licences: the source's terms allow what the project does (bundling, redistribution,
   commercial use); attribution present in outputs; personal data excluded.
6. Packaging and CI: pyproject, MANIFEST.in, sdist contains what tests need (build it in a scratch
   venv: `python3 -m venv`, `pip install build==1.6.1 twine`, run the tests from the unpacked sdist),
   `twine check`, workflow pins (checkout v6.1.0 d23441a…, setup-python v6.3.0 ece7cb0…,
   ubuntu-24.04), release.yml identical to the shared one, server.json schema and `mcp-name` match
   (MCP servers), `claude plugin validate` (plugins).
7. The test suite: run it; judge whether it tests real failure modes or restates the happy path.

## Report (under 500 words)

A verdict line: SHIP / SHIP AFTER FIXES / DO NOT SHIP. Then findings ranked
critical / high / medium / low, each with file:line, a concrete reproducing input or command, observed
vs expected, and a one-line fix. Then "checked and fine" in a few bullets so fixes do not break them.
Do not pad: if something is fine, do not list it as a finding.

## Variant: review AND fix (used for lower-risk projects)

When your brief says "review and fix": do the adversarial review above, then fix every finding yourself inside the
project directory (never outside it; no git; standard library only; standards points 1–18), each fix with a
regression test that fails before and passes after. Then re-run the suite, the sdist test run and `twine check` once,
re-run README examples if output changed (real output only), and run the secret-scan grep. Report (under 400 words):
verdict before fixes, each finding with severity → fixed / not fixed (why), test count before/after, and anything that
still needs a human decision.
