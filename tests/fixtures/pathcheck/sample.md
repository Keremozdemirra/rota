Good: ~/agents/rota/tools/pathcheck.py
Good with trailing period: ~/agents/rota/tools/pathcheck.py.
Good in backticks: `~/agents/rota/tools/pathcheck.py`
Bad: ~/definitely/not/here.md
Bad in parens (~/also/not/here.md)
Dangling: ~/agents/rota/tests/fixtures/pathcheck/dangling-link
Glob ok: ~/agents/rota/tools/*.py
Glob bad: ~/nowhere/at/all/*.py
Not a path: 3/4 of the way, and/or maybe
URL is not a path: https://github.com/Keremozdemirra/x
Template, not a claim: ~/.claude/orkestra/leads/<title>.md
Brace template: ~/agents/{concepts,ideas}
