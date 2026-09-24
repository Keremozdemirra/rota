# awesome-vitals

**Checks the GitHub repositories linked from a Markdown list (an awesome list, a
README, docs) and reports which entries are archived, abandoned, gone, renamed or
unlicensed, with the line of each one.**

## Why

Curated lists keep entries long after anyone maintains them. The
[agent-vitals](https://github.com/Keremozdemirra/agent-vitals) census of
2026-09-23 counted 39,963 repositories in the agent-tooling ecosystem: 2,385 not
archived and with no push in over a year, 636 archived, and 6,664 with no licence
file.

The lists that point people at those repositories grow by pull request. On the
same day, the most-starred MCP list in the census,
[punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers),
had 2,217 open issues and pull requests (GitHub's `open_issues_count`; its REST
API "considers every pull request an issue",
[docs](https://docs.github.com/en/rest/issues/issues), checked 2026-09-24). On
2026-09-24 awesome-vitals counted 4,319 repositories linked from its README.

awesome-vitals makes the check a job: over the whole list on a schedule, for the
maintainer, and over the lines a pull request adds, before the entry goes in.

## Example

Real output, 2026-09-24, for the agent-vitals README (a checkout at commit
`32c031a`), which links 71 repositories. It ran in a sandbox where the GitHub API
refused every repository (the 403 on the last line), so **every fact below came
from the census of 2026-09-23**: this is the fallback path. With GitHub reachable,
the source column reads `GitHub API`. Trimmed where marked `...`.

```
$ awesome-vitals README.md --census "file://$PWD/data/servers.json"
awesome-vitals · README.md · all entries · 2026-09-24
86 links to 71 repositories

  line      repository                                     last push         licence       source             note
  --------  ---------------------------------------------  ----------------  ------------  -----------------  ----
archived (10)
  137       bytebot-ai/bytebot                             2025-09-12  377d  Apache-2.0    census 2026-09-23
  140       airweave-ai/airweave                           2026-06-05  111d  MIT           census 2026-09-23
  ...
abandoned (20)
  107, 136  TransformerOptimus/SuperAGI                    2025-01-22  610d  MIT           census 2026-09-23
  108, 138  RayVentura/ShortGPT                            2025-02-10  591d  MIT           census 2026-09-23
  ...
no licence file (3)
  80        anthropics/skills                              2026-09-22    2d  none          census 2026-09-23
  ...
non-standard licence (7)
  77        n8n-io/n8n                                     2026-09-23    1d  non-standard  census 2026-09-23
  ...
not checked (1)
  18        Keremozdemirra/mcp-vitals                                                                         GitHub API answered 403; not in the census

71 repositories · 10 archived · 20 abandoned · 3 no licence file · 7 non-standard licence · 1 not checked · 34 with no finding
Facts: 70 from the agent-vitals census of 2026-09-23, 1 not checked.
GitHub API answered 403 for 71 repositories.
```

Pull-request mode on the same checkout, for the commit that added the mcp-vitals
link on line 18. These are the arguments the action's `pr` mode passes, and the job
summary it wrote (real, 2026-09-24, same sandbox). The entry could not be checked
there, so the step failed with exit code 2:

```
$ awesome-vitals --markdown --diff b25b498...HEAD --fail-on archived,gone -- README.md
### awesome-vitals: README.md, lines added in b25b498...HEAD, 2026-09-24

1 link to 1 repository · 1 not checked · 0 with no finding.

This check fails on an entry that is archived or gone, or one that could not be checked: 0 matched, 1 not checked.

#### Not checked (1)

| Line | Repository | Last push | Licence | Source | Note |
| --- | --- | --- | --- | --- | --- |
| 18 | [Keremozdemirra/mcp-vitals](https://github.com/Keremozdemirra/mcp-vitals) |  |  |  | GitHub API answered 403; not in the census |

Facts: 1 not checked. GitHub API answered 403 for 1 repository.

<sub>Checked with [awesome-vitals](https://github.com/Keremozdemirra/awesome-vitals) 0.1.0. Dates, flags and licence identifiers from public repository metadata, not a verdict on anyone's work.</sub>
```

## Install

```bash
uvx awesome-vitals README.md
pipx run awesome-vitals README.md
```

Nothing installed, standard library only (Python 3.9 or later):

```bash
curl -sL https://raw.githubusercontent.com/Keremozdemirra/awesome-vitals/main/awesome_vitals.py | python3 - README.md
```

A personal access token in `GITHUB_TOKEN` (or `GH_TOKEN`) raises GitHub's limit from
60 requests an hour to 5,000.

## Options

| Option | What it does |
| --- | --- |
| `FILE ...` | One or more Markdown files. A repository linked from several files or lines is checked once and listed with every line. |
| `--markdown` | A Markdown report, for an issue or a job summary. |
| `--json` | Everything, per repository: lines, status, findings, last push, licence, source. |
| `--strict` | Exit 1 if an entry has a finding named in `--fail-on`; otherwise exit 2 if an entry could not be checked. |
| `--fail-on LIST` | Comma-separated findings for `--strict` (default `archived,gone`); implies `--strict`. `none` alone reports without failing; with `--strict`, only entries that could not be checked fail. |
| `--diff BASE...HEAD` | Pull-request mode: only entries on lines added in that range. Runs `git diff --unified=0` and reads the hunks. The second revision should be what is checked out, because the files are read from disk. |
| `--only-lines FILE:START-END,...` | Only entries on these lines, e.g. `README.md:40-52,README.md:97`. A range without `FILE:` applies to every file. |
| `--source auto\|github\|census` | `auto` (default) asks GitHub and falls back to the census; `github` never uses the census; `census` sends nothing to the GitHub API (the census itself comes from `raw.githubusercontent.com` unless `--census` names another place). |
| `--census URL` | Another census index: `https://`, `file://` or a plain path. |

Exit codes: `0` clean (always, without `--strict`); `1` a `--fail-on` finding under
`--strict`; `2` could not check: under `--strict` an entry that neither GitHub nor
the census could answer for, and in any mode a file that cannot be read, an unknown
option or finding, or a failed `git diff`. A missing file is an error, never "no
links found".

## GitHub Action

For list maintainers, the whole list once a week:

```yaml
# .github/workflows/awesome-vitals.yml
name: awesome-vitals
on:
  schedule:
    - cron: "23 6 * * 1"   # Mondays, 06:23 UTC
  workflow_dispatch:
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
      - uses: Keremozdemirra/awesome-vitals@v0.1.0
        with:
          path: README.md
          mode: full
          fail-on: archived,gone
```

For contributors, only the lines a pull request adds or changes:

```yaml
# .github/workflows/awesome-vitals-pr.yml
name: awesome-vitals (pull request)
on:
  pull_request:
    paths: ["README.md"]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          fetch-depth: 0   # the diff needs the base commit
      - uses: Keremozdemirra/awesome-vitals@v0.1.0
        with:
          mode: pr
          fail-on: archived,gone,renamed
```

| Input | Default | What it does |
| --- | --- | --- |
| `path` | `README.md` | Markdown file to check. Several go one per line. |
| `mode` | `full` | `full` checks every entry. `pr` checks entries on lines added in the pull request: `git diff <base>...HEAD`, where `HEAD` is what the workflow checked out (for `pull_request`, the merge commit by default), so line numbers match the files on disk. |
| `fail-on` | `archived,gone` | Findings that fail the step, as for `--fail-on`. The step also fails when an entry could not be checked. `none` to report without failing. |
| `token` | `${{ github.token }}` | Token for the GitHub API. |

The report goes to the job summary (`$GITHUB_STEP_SUMMARY`) and the log. The action
posts no comments and needs only `contents: read`. The step needs `bash` and
`python3` on `PATH`; this repository's own CI runs the action on `ubuntu-24.04`.

The workflow token allows 1,000 requests an hour per repository (see the table
below). A list with more entries than that, or a token other jobs are spending,
gets the rest from the census and says so. For a list the size of the one above
(4,319 repositories), store a personal access token as a secret and pass it as
`token` (5,000 an hour).

## What the findings mean

| Finding | `--fail-on` key | Meaning |
| --- | --- | --- |
| archived | `archived` | The owner archived the repository. It is read-only. |
| gone | `gone` | GitHub answers 404: deleted, or private. GitHub "uses a 404 Not Found response instead of a 403 Forbidden response to avoid confirming the existence of private repositories" ([docs](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api), checked 2026-09-24). |
| renamed | `renamed` | GitHub answers 301, "Moved permanently" ([docs](https://docs.github.com/en/rest/repos/repos#get-a-repository), checked 2026-09-24): renamed or transferred. The old link still redirects; the report gives the new name. |
| abandoned | `abandoned` | No push in over 365 days. |
| stale | `stale` | Last push 91 to 365 days ago. |
| no licence file | `no-licence` | GitHub found no licence file. "without a license, the default copyright laws apply, meaning that you retain all rights to your source code and no one may reproduce, distribute, or create derivative works from your work" ([docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository), checked 2026-09-24). |
| non-standard licence | `non-standard-licence` | A licence file exists, but GitHub cannot match it to a standard identifier (`NOASSERTION`). It is licensed; read the licence. |
| not checked | (exit 2) | GitHub could not answer and the census does not have the repository. The note says why. Not a `--fail-on` key: under `--strict` it always gives exit code 2. |

`no-license` and `non-standard-license` are accepted too.

Status comes from the last push and uses the census's thresholds: `active` up to
30 days, `slowing` 31 to 90, `stale` 91 to 365, `abandoned` over 365, `archived`
whatever the date. These are a design choice of the agent-vitals census
(`bucket()` in its `collect.py`), not a standard; this tool uses them so an entry
reads the same in both. Licences follow the census too: `none` (no licence file)
and `non-standard` (`NOASSERTION`) are different findings, because the second
group did license its work.

## Which links count

Counted, and reduced to `owner/repo`:

- Markdown links, reference definitions (`[id]: https://...`), autolinks
  (`<https://...>`), bare URLs with or without `https://` or `www.`, and HTML
  `href` values.
- Any page of a repository: `/tree/...`, `/blob/...`, `/releases`, `/issues`,
  `/security`, `#readme`, `?tab=...`, a `.git` suffix.
- The server pages of the GitHub MCP Registry: `github.com/mcp/github/github-mcp-server`
  is `github/github-mcp-server`.
- In a bare URL, trailing `?`, `!`, `.`, `,`, `:`, `*`, `_` and `~` end the sentence
  or the emphasis, not the name, as in GitHub's own rendering: `_https://github.com/o/r_`
  is `o/r`. A link destination (`[x](...)`, `<...>`, `href`) is taken as written.
- The same repository under another letter case: GitHub names are
  case-insensitive, so it is one entry with all its lines.

Not counted, and tallied on the last line of the report:

- Profiles and organisations (`github.com/octocat`), and github.com pages that are
  not repositories: any path that starts with a name GitHub reserves (`topics`,
  `orgs`, `sponsors`, `marketplace`, `apps`, `github-copilot`, `mcp` and some 300
  more, from [github-reserved-names](https://github.com/Mottie/github-reserved-names)
  2.2.0, MIT licence, checked 2026-09-24), plus `models`, `password_reset`,
  `premium-support` and `solutions`. That list says it is not complete; a page it misses would show as
  `gone`.
- A link to one issue, pull request, discussion, commit, comparison or security
  advisory of a repository (`/issues/42`, `/pull/7`, `/commit/1a2b3c4`,
  `/security/advisories/GHSA-...`). Such a link cites one item inside an entry's
  description; the entry is the repository, linked on its own.
- Images and badges: the target of `![...](...)`, a reference definition used only
  as an image (`[![CI][badge]][runs]` with `[badge]: https://...`), and every
  `src` or `srcset` value, in any tag and on any line of it. A CI badge hosted on
  github.com is not an entry (the link around it is). `img.shields.io`,
  `gist.github.com`, `raw.githubusercontent.com` and `*.github.io` are other hosts.
- Anything in a fenced code block (backticks or tildes, at any indentation), in
  inline code, or in an HTML comment: a commented-out entry is not on the list. As
  on GitHub, a comment ends at the first `-->` (backticks or not), `<!-->` is a
  whole comment, and a fence inside a list item ends with the item.
- A GitHub URL nested in another URL's path, such as a `web.archive.org` snapshot.

A code fence or comment that is never closed hides the rest of the file, on GitHub
as here. The report names its line in a warning.

Indented code blocks are not recognised, because in a list four spaces of
indentation also mark a nested item.

## Rate limits and the census fallback

| Who asks | GitHub REST API limit | Source |
| --- | --- | --- |
| No token | 60 requests an hour | [Rate limits for the REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api), checked 2026-09-24 |
| A personal access token in `GITHUB_TOKEN` | 5,000 requests an hour | same page |
| The GitHub Actions workflow token (the action's default) | 1,000 requests an hour per repository | same page |

A repository costs one request, a renamed one two, and a retry (below) one more.
Requests go one at a time:
GitHub asks clients to "make requests serially instead of concurrently" to stay
under its secondary limits
([best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api),
checked 2026-09-24).

A request that gets no answer or a 5xx is asked once more after a second. A
secondary rate limit is asked once more after its `retry-after`, or after a minute
when it names none: "If the retry-after response header is present, you should not
retry your request until after that many seconds has elapsed", and "Otherwise,
wait for at least one minute before retrying" (rate limits page above). The tool
waits at most 60 seconds, its own choice; a longer wait, or a primary limit
(`x-ratelimit-remaining: 0`, which resets within the hour), is not waited for.

When the retry gets no answer either or meets the rate limit again, or GitHub
answers 403 with `x-ratelimit-remaining: 0`, the rest of the run uses the
agent-vitals census index instead. Past either its primary or its secondary limit,
"you will receive a 403 or 429 response" (rate limits page above). Any other
refusal (a 5xx that outlasts its retry, or for example an organisation's IP allow
list) falls back for that repository only. The census is downloaded once per run
and only when needed: one file of about 26 MB, some 40,000 repositories of agent
tooling (MCP servers, agent frameworks, skills). A repository outside it is
reported as `not checked`. Census rows cannot show `gone` or `renamed`; the source
column says which rows came from where, and the lines under the table say why.

## Data sources and their terms

- **GitHub REST API**, `GET /repos/{owner}/{repo}`, public repository metadata:
  archived flag, last push, licence identifier, full name. Use is governed by
  section H, API Terms, of the
  [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#h-api-terms)
  (checked 2026-09-24): "Abuse or excessively frequent requests to GitHub via the
  API may result in the temporary or permanent suspension of your Account's access
  to the API" and "You may not share API tokens to exceed GitHub's rate
  limitations." The report states facts from that metadata and links each
  repository.
- **The agent-vitals census**,
  [`data/servers.json`](https://github.com/Keremozdemirra/agent-vitals#use-the-data),
  only when GitHub cannot answer. Its compilation is CC0 1.0:
  "Take it, chart it, fork it, no attribution required"
  ([licence](https://github.com/Keremozdemirra/agent-vitals#licence), checked
  2026-09-24). awesome-vitals reads `full_name`, `archived`, `pushed_at`,
  `license`, `license_state` and `stars` from it, and never the `description`
  field, which belongs to each repository's author and is outside that grant.

## What it reads, what it sends

- **Reads:** the Markdown files you name and, with `--diff`, the output of
  `git diff` for them. Nothing else on disk.
- **Sends:** `owner/repo` names to `api.github.com`, and only names that match
  GitHub's form (letters, digits, `-`, `_`, `.`; nothing else reaches a URL), with
  `GITHUB_TOKEN` or `GH_TOKEN` when set and shaped like a token (printable ASCII, no
  spaces; anything else is not sent, and the report says so without printing it).
  The token goes to the API host only: a redirect to any other host is not followed. When GitHub cannot answer, one
  download of the census index, without the token. `--source census` sends nothing
  to the GitHub API.
- **Prints:** repository names, dates and licence identifiers, each checked against
  its expected form first, since they come from GitHub or from a census file you may
  point anywhere; a value that does not fit is dropped. Credentials and query strings
  in a `--census` URL are masked.
- **Writes:** standard output only. The action appends the same report to the job
  summary.
- **Runs:** `git diff`, with `--diff` only. Nothing from the list is fetched,
  installed or executed.

## Licence

MIT.

## What this is not

- **Not a link checker.** Only links to GitHub repositories are looked at; every
  other URL in the file is left alone.
- **Not a verdict.** The findings are dates, flags and licence identifiers from
  public metadata. A finished, correct tool can go a year without a push, and an
  archived repository can still be the right thing to link.
- **Not a licence review.** `non-standard` means read the file; an SPDX
  identifier does not mean the licence fits your use.
- **Not an editor.** It changes nothing in the list and posts no comments.
