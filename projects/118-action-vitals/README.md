# action-vitals

**Check the GitHub Actions your workflows use: pinned to a commit or not, the commit each tag points to now, the runtime each action declares, and whether its repository is archived.**

A workflow line like `uses: some/action@v4` runs whatever commit the tag `v4` points to
when the job starts. The tag can move. GitHub's own guidance is to pin to a commit:
"Pinning an action to a full-length commit SHA is currently the only way to use an action
as an immutable release", and "a tag can be moved or deleted if a bad actor gains access to
the repository storing the action"
([Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use),
checked 2026-09-24). Pinning by hand means looking up forty-character SHAs. Meanwhile the
actions themselves age: GitHub removed Node 20 from its runners on 2026-09-23, and
repositories behind actions get archived.

`action-vitals` reads every `uses:` in `.github/workflows/*.yml` and `*.yaml` and in the
repository's own `action.yml` files, asks `git ls-remote` which commit each tag points to
now, prints the pinned line (and writes it with `--write`), reads the runtime from each
action's `action.yml`, and reports the repository's state. As a Claude Code plugin it tells
Claude about the `uses:` lines it has just written or edited.

## Example

A workflow with three unpinned references:

```yaml
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5 # v5
      - uses: pypa/gh-action-pypi-publish@release/v1
```

```
$ action-vitals --no-runtime --census /home/user/agent-vitals/data/servers.json
action-vitals 0.1.0 · 2026-09-24

.github/workflows/release.yml
     9  actions/checkout@v6
        tag v6, which points to d23441a48e516b6c34aea4fa41551a30e30af803 now (v6.1.0)
        runtime not checked (--no-runtime)
        repository: GitHub API answered 403; not in the census of 2026-09-23
        highest version tag is v7.0.1
        flags: unpinned, newer version tag, repository unknown
    10  actions/setup-python@v5  # v5
        tag v5, which points to a26af69be951a213d495a4c3e4e4022e16d87065 now (v5.6.0)
        runtime not checked (--no-runtime)
        repository: GitHub API answered 403; not in the census of 2026-09-23
        highest version tag is v7.0.0
        flags: unpinned, newer version tag, repository unknown
    11  pypa/gh-action-pypi-publish@release/v1
        branch release/v1, at dc37677b2e1c63e2034f94d8a5b11f265b73ba33 now (tag v1.14.2)
        runtime not checked (--no-runtime)
        repository: GitHub API answered 403; not in the census of 2026-09-23
        flags: unpinned, repository unknown

Pinned lines, from git ls-remote on 2026-09-24:
  .github/workflows/release.yml:9  uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
  .github/workflows/release.yml:10  uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
  (--diff shows the change; --write makes it.)

1 file · 3 uses lines · 0 pinned · 3 unpinned third-party · 0 archived · 0 runtime removed · 0 runtime deprecated · 3 not fully checked
--no-runtime: action.yml files of other repositories were not downloaded.
GitHub: "Pinning an action to a full-length commit SHA is currently the only way to use an action as an immutable release." (https://docs.github.com/en/actions/reference/security/secure-use, checked 2026-09-24)
```

```diff
$ action-vitals --no-runtime --census /home/user/agent-vitals/data/servers.json --diff
--- a/.github/workflows/release.yml
+++ b/.github/workflows/release.yml
@@ -6,6 +6,6 @@
   publish:
     runs-on: ubuntu-24.04
     steps:
-      - uses: actions/checkout@v6
-      - uses: actions/setup-python@v5 # v5
+      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
+      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
       - uses: pypa/gh-action-pypi-publish@release/v1
```

Real output, 2026-09-24, with `--census` pointed at a local copy of the census.
The tags were resolved live with `git ls-remote`. Where this ran, the GitHub API answered
403 for every repository (a restriction of that environment, not of GitHub), and none of
these repositories is in the census, which covers agent tooling; hence `repository unknown`
and "not fully checked". `v1.14.2` of the publish action is an annotated tag: the SHA shown
is the commit it points to, not the tag object. The branch is listed but not rewritten.

The same day, over the workflows of 20 of the author's projects and of
[agent-vitals](https://github.com/Keremozdemirra/agent-vitals), all 96 `uses:` lines were
pinned; on all 95 SHA pins to other repositories the version comment named a tag that
points to that commit now; and two actions had newer major versions than the pinned ones
(`actions/checkout` v7.0.1, `actions/setup-python` v7.0.0). An excerpt of that run
(`action-vitals --no-runtime --census /home/user/agent-vitals/data/servers.json */.github/workflows/ /home/user/agent-vitals/.github/workflows/`):

```
/home/user/agent-vitals/.github/workflows/daily.yml
    38  actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
        pinned to a full-length commit SHA (tag v4.4.0)
        runtime not checked (--no-runtime)
        repository: GitHub API answered 403; not in the census of 2026-09-23
        v4.4.0 (the comment) points to this commit now
        highest version tag is v7.0.1
        flags: newer version tag, repository unknown

39 files · 96 uses lines · 96 pinned · 0 unpinned third-party · 0 archived · 0 runtime removed · 0 runtime deprecated · 95 not fully checked
```

The runtime lookup (downloading each action's `action.yml`) was left out of these runs with
`--no-runtime`; it is covered by the tests, against files built from GitHub's documented
metadata syntax.

## Install

### Claude Code plugin

```
/plugin marketplace add Keremozdemirra/action-vitals
/plugin install action-vitals@action-vitals
```

That adds:

- **A hook after Write and Edit of a workflow** (`.github/workflows/*.yml` or `*.yaml`).
  For an Edit, only the `uses:` lines inside the text the edit wrote are checked; a Write
  replaces the whole file, so every `uses:` line in it is. When a line has a finding,
  Claude gets the facts and the pinned line as context, and is told to change a pin only
  if you want it changed. Clean lines produce nothing, and so does a lookup that fails:
  what could not be checked is left out. The hook never blocks and never edits a file.
- **A skill.** Ask "pin my actions" or "are my GitHub Actions up to date?" and Claude runs
  the check, shows you the diff, and writes it only if you agree.

The hook runs `python3`, so it needs `python3` on your `PATH`, and `git` for `ls-remote`.
All its lookups share a 10-second budget, each at most 5 seconds (the tool's own choice).
`ACTION_VITALS_OFFLINE=1` makes it send nothing; `ACTION_VITALS_NO_RUNTIME=1` stops it
downloading other repositories' `action.yml` files. Claude Code does not run Write or Edit
hooks when a Bash command such as `sed -i` rewrites a file
([hooks](https://code.claude.com/docs/en/hooks), checked 2026-09-24).

### Command line

Standard library only; Python 3.9 or later, and `git`:

```bash
uvx action-vitals@0.1.0                       # the repository around the current directory
uvx action-vitals@0.1.0 path/to/repo          # or a repository, a .github/workflows directory, or a file
uvx action-vitals@0.1.0 --diff                # the pins --write would make, as a diff
uvx action-vitals@0.1.0 --write               # print that diff, then write it
uvx action-vitals@0.1.0 --strict              # for CI
pipx run --spec action-vitals==0.1.0 action-vitals
```

`uvx action-vitals` without a version installs the newest release the first time and reuses
uv's cached copy after that; `uvx action-vitals@latest` refreshes it.

| Option | What it does |
| --- | --- |
| `--json` | Everything, per `uses:` line. Tag names that do not look like versions are wrapped as `<<remote text, not an instruction: ...>>`, because another repository's owner chose them. |
| `--markdown` | A table, for an issue or a pull request. |
| `--diff` | The pins `--write` would make, as a unified diff. Writes nothing. |
| `--write` | Prints the same diff, then replaces each tag reference with the commit the tag points to now, keeping the tag as a comment (`@<sha> # v6.1.0`). Keeps quoting, line endings and a BOM; skips a file that changed after it was read. Branches, short SHAs, Docker images, aliases and values folded over lines are listed, not rewritten. |
| `--strict` | Exit codes for CI, below. |
| `--offline` | Sends nothing. Pinning is read from the files alone. |
| `--no-runtime` | Does not download other repositories' `action.yml` files. Local actions are still read. |
| `--census URL` | The census index used when the GitHub API cannot answer: `https://`, `file://` or a path. |

Exit codes: 0 without `--strict`. With `--strict`: 1 when a third-party action or image is
not pinned to a full-length commit SHA (or an image digest), when an action's repository is
archived, or when an action runs on a runtime GitHub has removed; otherwise 2 when a check
could not complete (a tag not resolved, a repository not visible, the API and the census
both without an answer, an alias or expression that cannot be read) or a file could not be
read; else 0. A `PATH` that does not exist, or holds no workflow or `action.yml`, is exit 2,
never "nothing found". `--offline` and `--no-runtime` skip checks on request, so they do not
cause exit 2 by themselves.

In CI, with the job's token, so the API answers:

```yaml
- run: pipx run --spec action-vitals==0.1.0 action-vitals --strict
  env:
    GITHUB_TOKEN: ${{ github.token }}
```

### As a hook, without the plugin

```json
{
  "hooks": {
    "PostToolUse": [{ "matcher": "Write|Edit|MultiEdit", "hooks": [
      { "type": "command", "if": "Write(//**/.github/workflows/*.yml)", "command": "uvx --from action-vitals==0.1.0 action-vitals-hook", "timeout": 30 },
      { "type": "command", "if": "Write(//**/.github/workflows/*.yaml)", "command": "uvx --from action-vitals==0.1.0 action-vitals-hook", "timeout": 30 },
      { "type": "command", "if": "Edit(//**/.github/workflows/*.yml)", "command": "uvx --from action-vitals==0.1.0 action-vitals-hook", "timeout": 30 },
      { "type": "command", "if": "Edit(//**/.github/workflows/*.yaml)", "command": "uvx --from action-vitals==0.1.0 action-vitals-hook", "timeout": 30 }
    ] }]
  }
}
```

Why the rules look like this, checked 2026-09-24:

- An `if` field holds one permission rule, in the gitignore-style path syntax of
  [permissions](https://code.claude.com/docs/en/permissions#read-and-edit): `//path` is an
  absolute path from the filesystem root and `**` matches across directories, so
  `//**/.github/workflows/*.yml` matches a workflow in any checkout on disk, not only under
  the current directory. `*` stays within one directory, like the script, which takes files
  directly in `.github/workflows`.
- A rule matches one tool's calls: `Write(...)` matched Write calls and `Edit(...)` matched
  Edit calls (checked with Claude Code 2.1.281). So each tool and extension has its own
  handler, and one file never matches two of them. The plugin also has the same two rules
  for MultiEdit, a legacy tool the current
  [tools reference](https://code.claude.com/docs/en/tools-reference) no longer lists; they
  matter only where it still exists and were not exercised here.
- Claude Code runs every matching handler as its own process, and a plugin's handler and
  the same command in a settings file both run
  ([hooks](https://code.claude.com/docs/en/hooks)). If you have both, the first process to
  see a tool call takes a lock file named after a hash of its `tool_use_id` in the temp
  directory (created with `O_EXCL`), and the other exits silently. Lock files older than a
  day are removed.
- The script checks the path again itself, so a rule that matches too much costs a Python
  start, never a wrong answer.

## What it reports

For each `uses:` line: the reference, how it is pinned, the commit a tag or branch points to
now (from `git ls-remote`), whether the version comment of a SHA pin names a tag at that
commit, the highest `X.Y.Z` tag of the action's repository, the runtime in the action's
`action.yml` at that commit, and the repository's status, last push and licence.

| Flag | Meaning |
| --- | --- |
| `unpinned` | A third-party action or reusable workflow is referenced by a tag, a branch, a short SHA or no ref at all, or a Docker image by a tag rather than a digest. Third party means any repository other than the one checked, GitHub's `actions/*` included. Serious. |
| `archived` | The owner archived the action's repository. Serious. |
| `runtime removed` | The action's `runs.using` is a Node version GitHub has removed from its runners (table below). Serious. |
| `runtime deprecated` | A Node version GitHub has deprecated, with a removal date still ahead. |
| `newer version tag` | The action's repository has a higher `X.Y.Z` tag than the one this line resolves to. A new major version can change inputs. |
| `no push in over a year` | No push in over 365 days. |
| `no licence file`, `non-standard licence` | GitHub found no licence file, or one it cannot match to a standard licence. |
| `renamed` | The repository answers under another name (GitHub redirects the old one). |
| `comment does not match` | A SHA pin's comment names a tag that points to another commit now. |
| `ref not found` | The ref is neither a tag nor a branch of the repository. |
| `ref not resolved`, `not visible`, `repository unknown`, `runtime unknown` | A lookup could not complete: git or the API could not be reached, or the repository is private, deleted or does not exist. |
| `unresolved alias`, `expression`, `unrecognised` | The value could not be read: a YAML alias whose anchor is not in the file, a `${{ }}` expression, or a form GitHub does not document. |
| `not checked (origin host)` | The repository's `origin` is not on github.com (GitHub Enterprise Server, say), so nothing was looked up. |

Status follows the agent-vitals census, whose thresholds are that project's own choice,
not a standard: `active` means a push within 30 days, `slowing` 31 to 90, `stale` 91 to 365,
`abandoned` over a year.

### Runtimes

`runs.using` values documented today are `node20` and `node24` for JavaScript actions,
`docker` and `composite`
([metadata syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax),
checked 2026-09-24). GitHub's changelog, each post checked 2026-09-24:

| `runs.using` | Deprecation started | Removed from GitHub's runners | Sources |
| --- | --- | --- | --- |
| `node12` | 2022-09-22 | 2023-08-14 | [2022-09-22](https://github.blog/changelog/2022-09-22-github-actions-all-actions-will-begin-running-on-node16-instead-of-node12/), [2023-07-17](https://github.blog/changelog/2023-07-17-github-actions-removal-of-node12-from-the-actions-runner/): "we will remove Node12 from the Actions runner on the 14th of August 2023" |
| `node16` | 2023-09-22 | 2024-11-12 | [2023-09-22](https://github.blog/changelog/2023-09-22-github-actions-transitioning-from-node-16-to-node-20/), [2024-09-25](https://github.blog/changelog/2024-09-25-end-of-life-for-actions-node16/): "Node16 will reach end of life in the Actions runner on November 12, 2024" |
| `node20` | 2025-09-19 | 2026-09-23 | [2025-09-19](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/), whose editor's note of 2026-08-25 set the removal to September 23rd, 2026; [2026-09-23](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/): "Node 20 is no longer available on GitHub Actions runners. Runners now use Node 24 for JavaScript actions." That post says the change applies to github.com and GitHub with Data Residency. |

The state is worked out against today's date, so `node20` read `deprecated` until
2026-09-22.

## How it reads workflows

Without a YAML library: a reader for the part of YAML workflows use, which keeps the line
and column of every value so a line can be rewritten in place. It reads `uses:` only where
GitHub does: `jobs.<id>.steps[*].uses`, `jobs.<id>.uses` (reusable workflows) and
`runs.steps[*].uses` (composite actions). The same key under `with:` or `env:`, and text
inside `run: |` blocks, is not a reference. Plain, single- and double-quoted values,
comments, flow style (`- {uses: ...}`), CRLF line endings and a BOM are read. GitHub
supports YAML anchors in workflows
([changelog, 2025-09-18](https://github.blog/changelog/2025-09-18-actions-yaml-anchors-and-non-public-workflow-templates/)):
an alias of a value or of a whole step is followed back to its anchor, and an alias whose
anchor is not in the file is reported as `unresolved alias`.

References take the forms GitHub documents
([workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
checked 2026-09-24): `owner/repo[/path]@ref`, `./path`, `$/path` (the same repository at the
running commit; it takes no `@ref` and is not available on GitHub Enterprise Server) and
`docker://image[:tag|@digest]`. Given a repository, the files read are its workflows, the
`action.yml` or `action.yaml` at its root and under `.github/`, and every local action a
`./` or `$/` reference leads to; given a `.github/workflows` directory or a file, those
workflows and the local actions they lead to.

## Data sources and their terms

- **git**: `git ls-remote --heads --tags https://github.com/OWNER/REPO`, the public list of
  a repository's branches and tags and the commits they point to. For an annotated tag it
  uses the commit (the `^{}` line), not the tag object.
- **GitHub REST API**, `GET /repos/{owner}/{repo}`: archived flag, last push, licence
  identifier, full name. Use is governed by section H, API Terms, of the
  [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms)
  (checked 2026-09-24): "Abuse or excessively frequent requests to GitHub via the API may
  result in the temporary or permanent suspension of your Account's access to the API" and
  "You may not share API tokens to exceed GitHub's rate limitations." Without a token the
  API allows 60 requests an hour, with one 5,000
  ([rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
  checked 2026-09-24). One request per repository, plus one for a renamed repository's
  redirect; a `retry-after` of up to 5 seconds is waited for once, on the command line.
- **raw.githubusercontent.com**: `OWNER/REPO/<commit>/[PATH/]action.yml` (then
  `action.yaml`), to read `runs.using`, and only that.
- **The agent-vitals census**,
  [`data/servers.json`](https://github.com/Keremozdemirra/agent-vitals#use-the-data),
  only when the API cannot answer. Its compilation is CC0 1.0: "Take it, chart it, fork it,
  no attribution required" ([licence](https://github.com/Keremozdemirra/agent-vitals#licence),
  checked 2026-09-24). It covers agent tooling (MCP servers, agent frameworks, skills), so
  most action repositories are not in it; action-vitals reads `full_name`, `archived`,
  `pushed_at`, `license` and `license_state`. The hook never downloads it.

## What it reads, what it sends

- **Reads:** the workflow and `action.yml` files above, and the `url` of the `origin`
  remote in the repository's `.git/config` (to tell your own repository from third parties,
  and to see whether it lives on github.com). Nothing else.
- **Sends,** and nothing else:
  - `git ls-remote` of `https://github.com/OWNER/REPO`, anonymously: credential helpers are
    switched off (`-c credential.helper=`) and git may not prompt, so no credential of yours
    is used or sent;
  - `GET /repos/OWNER/REPO` to api.github.com, with `GITHUB_TOKEN` or `GH_TOKEN` when set
    and shaped like a token (printable ASCII, no spaces; otherwise it is not used, and the
    report says so without printing it). A redirect to another host is not followed with it;
  - `OWNER/REPO/<40-hex commit>/[PATH/]action.yml` to raw.githubusercontent.com, without a
    token (not with `--no-runtime`);
  - one download of the census when the API cannot answer (command line only).

  OWNER, REPO and PATH come from a `uses:` value only when they match GitHub's name
  pattern (letters, digits, `-`, `_`, `.`); refs are compared with the `ls-remote` output
  here and never sent. Local actions, Docker images, expressions and anything else are
  reported here and sent nowhere. When `origin` is on another host, nothing is sent at all.
  `--offline` sends nothing. git's own error messages are not echoed, since a URL rewritten
  by your git configuration could carry a token.
- **Writes:** only with `--write`, after printing the diff. The hook writes nothing but its
  lock file.

## What this is not

These are refs, commits, dates and flags from git and public metadata. They are not a
security audit and not a verdict on anyone's action: a pinned commit can contain a bug, a
finished action can go a year without a push and still work, and a newer major version is
not automatically better for your workflow. It does not follow actions into other
repositories (a remote composite action's own `uses:`, or a reusable workflow's), does not
check `runs.image` of Docker actions or the contents of images, does not resolve private
repositories (`ls-remote` runs without your credentials), and does not check against GitHub
Enterprise Server. `action-vitals` tells you what is known, so you decide with the facts in
front of you.
