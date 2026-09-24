# Batch 2026-09-24: hand-off

Twenty-two projects are staged under `projects/101-*` to `projects/123-*` on the rota branch
`claude/oss-program-setup-cian0f` (121 was dropped; see the backlog). Every directory is self-contained:
`publish.sh` turns one into its own public repository. Nothing here has been published, no repository has
been created, and no token exists anywhere in these files. Thirteen are reviewed and ready; nine are built but
not reviewed and should not be published as they are (see the table).

This branch is a staging area. Do not merge it into rota's `main`.

## Once, before the first project

The branch history was rewritten on 2026-09-24 (see "Notes"). If you fetched it before, fetch again; a
worktree made from the old history must be moved to the new tip.

```bash
cd ~/agents/rota
git fetch origin claude/oss-program-setup-cian0f
git worktree add ../rota-staging origin/claude/oss-program-setup-cian0f   # first time
# or, if ../rota-staging already exists:
#   git -C ../rota-staging checkout --detach origin/claude/oss-program-setup-cian0f
cd ../rota-staging
gh auth status                 # must show Keremozdemirra
```

- A PyPI account with 2FA (pypi.org).
- For MCP servers only: install `mcp-publisher`
  (https://modelcontextprotocol.io/registry/quickstart, "Install mcp-publisher") and run
  `mcp-publisher login github` once.

## Per project, three or four steps

1. `bash projects/publish.sh <directory> <repo>` (for example `bash projects/publish.sh 101-mcp-upkeep mcp-upkeep`).
   It publishes only what is committed (git archive), runs the secret scan, asks you to type the repository
   name, creates the public repository and pushes. It prints steps 2 to 4 with the right values.
2. PyPI trusted publisher, once per project: https://pypi.org/manage/account/publishing/ → "Add a new pending
   publisher" with the PyPI name, owner `Keremozdemirra`, the repository, workflow `release.yml`, environment `pypi`.
3. `gh release create v0.1.0 --repo Keremozdemirra/<repo> --generate-notes`: the release workflow runs the tests,
   checks that the tag matches the version, builds and publishes to PyPI. No token involved.
4. MCP servers only: in a clone of the new repository, once the PyPI release is live, `mcp-publisher publish`
   (the `server.json` and the README's `mcp-name` line are already there).

Claude Code plugins (the "plugin" rows below) need nothing more: `/plugin marketplace add Keremozdemirra/<repo>`
works as soon as the repository is public.
awesome-vitals is also a GitHub Action; listing it on the Marketplace is optional (edit the release on GitHub and
tick "Publish this Action to the GitHub Marketplace").

A suggested order, strongest first: 115 csrd-scope, 107 cbam-mcp, 104 eu-ets-mcp, 101 mcp-upkeep, 102 pkg-vitals,
117 vsme-kit, 110 financed-emissions, 114 eudr-scope-mcp, then the other reviewed ones. Nothing depends on anything else, except
that agent-vitals PR #1 links to mcp-upkeep (merge it after mcp-upkeep is public).

## The projects

Names were checked on 2026-09-24: every repository name is free under Keremozdemirra, and every PyPI name is
free, including PyPI's "too similar to an existing project" rule (checked against the full PyPI index).
"Tests" is the offline unittest count; CI runs them on Python 3.9 and 3.12.

### Reviewed and fixed: publish these

Each was reviewed adversarially by a separate agent (logic with hostile inputs, every README claim, data
licences, packaging from the sdist, CI pins); every finding was fixed with a regression test.

| # | Directory → repository and PyPI name | What it is | Kind | Tests |
|---|---|---|---|---|
| 101 | `101-mcp-upkeep` → `mcp-upkeep` | Check the MCP servers you run: is the repository behind each one still maintained, licensed, pinned? Asks before Claude adds one that is not. | CLI, plugin with hook | 127 |
| 102 | `102-pkg-vitals` → `pkg-vitals` | Check an npm or PyPI package before a coding agent installs it: does the name exist, is it brand new, deprecated or yanked, is its repository archived? | CLI, plugin with hook | 173 |
| 103 | `103-awesome-vitals` → `awesome-vitals` | Check every GitHub repository linked from a Markdown list: archived, gone, renamed, abandoned or unlicensed entries, with line numbers. | CLI, GitHub Action | 90 |
| 104 | `104-eu-ets-mcp` → `eu-ets-mcp` | EU ETS installations from the Union Registry: verified emissions, free allocation and surrendered units by installation, LEI, country or sector. | MCP server, CLI | (fixing) |
| 105 | `105-eu-taxonomy-mcp` → `eu-taxonomy-mcp` | EU Taxonomy activities, NACE codes and technical screening criteria, from a dated snapshot of the EU Taxonomy Navigator. | MCP server, CLI | (fixing) |
| 107 | `107-cbam-mcp` → `cbam-mcp` | EU CBAM scope, default values and CN descriptions from dated official sources. | MCP server, CLI | 135 |
| 108 | `108-xlsx-review` → `xlsx-review` | A pull-request-style review for spreadsheets: formula-level diffs of .xlsx files and the edits that usually break models. | MCP server, CLI, plugin | 84 |
| 110 | `110-financed-emissions` → `financed-emissions` | Financed emissions (Scope 3 category 15) by the PCAF Part A methods, with the arithmetic shown for every position. | MCP server, CLI | 163 |
| 114 | `114-eudr-scope-mcp` → `eudr-scope-mcp` | EU Deforestation Regulation scope and dates: Annex I by CN code, application dates, country risk, with legal sources. | MCP server, CLI | 117 |
| 115 | `115-csrd-scope` → `csrd-scope` | Is an undertaking in scope of the EU CSRD, and from which financial year? Rules with article citations. | MCP server, CLI | 71 |
| 117 | `117-vsme-kit` → `vsme-kit` | The VSME standard's text, and a check of a filled EFRAG Digital Template. | MCP server, CLI, plugin | 77 |
| 119 | `119-destroy-guard` → `destroy-guard` | A Claude Code hook: terraform destroy, kubectl delete, helm uninstall and git push --force wait for a verified backup. | plugin with hook, CLI | (fixing) |
| 120 | `120-credential-reach` → `credential-reach` | What credentials could an AI agent running as you on this machine use? Lists them without printing a secret. | CLI, plugin | (fixing) |

### Built, not reviewed: do not publish as they are

These were built to the same standards and their tests pass, but the adversarial review, which found real
problems in every project it covered, was stopped here on 2026-09-24. Publish one only after it has been
reviewed and fixed: `projects/REVIEW-TEMPLATE.md` (the brief, variant "review AND fix") and
`projects/BUILD-STANDARDS.md` (the checklist) are what the others went through; their paths point to the
sandbox that built them and need adjusting.

| # | Directory | What it is | Kind | Tests | Known before review |
|---|---|---|---|---|---|
| 106 | `106-ghg-factors-mcp` | Greenhouse-gas conversion factors with their provenance (UK DESNZ, Ember, UBA). | MCP server, CLI | 93 | |
| 109 | `109-tieout` | Tie every number in a report or deck back to the source cells in .xlsx or .csv. | MCP server, CLI, plugin | 137 | |
| 111 | `111-climate-trace-mcp` | Climate TRACE emission estimates for assets and countries, with owners, source and licence. | MCP server, CLI | 91 | the name uses "Climate TRACE"; see decisions |
| 112 | `112-eiopa-rfr` | EIOPA's monthly Solvency II risk-free rate term structures as published. | MCP server, CLI | 127 | |
| 113 | `113-firds-mcp` | ISIN → issuer, LEI, parents, trading venues (ESMA FIRDS and GLEIF). | MCP server, CLI | 133 | |
| 116 | `116-esrs-datapoints-mcp` | Query EFRAG's ESRS datapoint list from your own downloaded copy; bundles no EFRAG content. | MCP server, CLI | 65 | licence text cites the commission.europa.eu notice; check against standards point 16 |
| 118 | `118-action-vitals` | Check the GitHub Actions your workflows use: pinning, retired Node runtimes, archived repositories. | CLI, plugin with hook | 67 | |
| 122 | `122-diff-mutants` | Mutation testing on the lines a git change touched. | CLI, plugin | 152 | |
| 123 | `123-hook-harness` | Test and lint Claude Code hooks in CI. | CLI | 83 | README and fixtures still say mcp-vitals (renamed to mcp-upkeep); its README link now lands on agent-vitals |

## Decisions for you

1. **The nine unreviewed projects.** Leave them here (they cost nothing on this branch) and review them one at a
   time when you want them, or delete them. My advice: publish the thirteen reviewed ones first and see which get
   used before spending on the rest.
2. **climate-trace-mcp's name** (only if you review and publish 111). "Climate TRACE" is the coalition's name. Its
   data is CC BY 4.0, which grants no trademark rights. Keep the name with a clear "unofficial, not affiliated"
   line, or rename (for example `ctrace-mcp`) — a lawyer's question if you want certainty.
3. **Old rota commits that held personal data (optional, recommended).** See the first note below. To have GitHub
   drop the unreferenced commits, open a request at https://support.github.com/contact naming the repository
   `Keremozdemirra/rota` and the old commits `65ba043` to `9946a12` (46 commits of the old history of this branch).
   GitHub's guide: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
4. **agent-vitals PR #1** (https://github.com/Keremozdemirra/agent-vitals/pull/1) links to mcp-upkeep. Merge it
   after mcp-upkeep is public; until then its links return 404.

## Not built, and why

| Idea | Reason |
|---|---|
| ECB / Eurostat / GLEIF / sanctions / EUR-Lex servers | already covered in the MCP Registry (2–15 servers each) |
| escb-rates (€STR, policy rates, Bund) | weak gap; ECB yield curves include third-party data the ESCB policy excludes |
| eu-finreg-tracker (Level 2 acts under CRR/MiCA/DORA) | weak gap vs existing EUR-Lex servers; CELLAR reuse terms say "contact us" |
| ESEF/ESRS facts via filings.xbrl.org | no data licence; EFRAG taxonomy all rights reserved; 0 German filings |
| OpenSanctions | CC BY-NC; compliance screening is commercial use |
| NGFS scenario queries | licence forbids reproducing a substantial portion |
| IPCC EFDB, SBTi, TPI, PCAF database, PRIMAP v2.7, IEA-EDGAR CO2 | licences forbid redistribution or commercial use |
| Unternehmensregister / Handelsregister / BaFin | terms of service, or scraping |
| bash-undo | four young tools already; contributing beats a fifth |
| 121 deny-probe (testing permission-bypass techniques) | dropped: publishing a catalogue of bypass techniques is too sensitive; the built-in sandbox is the real fix |
| eu-accounts (Companies House, Brreg, Bolagsverket) | thin evidence |
| command blockers, done-claim gates, slop triage, MCP pinning, skill scanners, cost trackers | crowded |

## Notes on how this batch was made

- **Personal data, 104.** On 2026-09-24 the first data snapshot of eu-ets-mcp carried names of natural persons
  (sole traders and ship partnerships are account holders in the EU ETS Union Registry, and some installations
  are named after them). It was committed to this public branch in `65ba043`. The review caught it the same day;
  the file was removed from every commit of the branch by a history rewrite and a force-push (old tip `9946a12`,
  new tip `259b5a5`), the tool now withholds any name that may be a natural person's, and the data file is
  regenerated without them. The old commits are off every branch but stay reachable by SHA on GitHub until
  purged (decision 3).
- **Rename.** 101 was built as `mcp-vitals`. PyPI would refuse that name: it normalises to the same name as the
  existing project `mcpvitals` (ContextJet.ai, 2026-07-05, "Vital signs for your MCP servers"), and PyPI rejects
  names "too similar to an existing project". `github.com/Keremozdemirra/mcp-vitals` is also agent-vitals' former
  name and still redirects there. 103's README keeps one recorded example that mentions `Keremozdemirra/mcp-vitals`
  (the output of a real run on an agent-vitals commit); it is correct as a record.
- **How it was made.** Research (demand signals, EU finance and climate data sources with their licences, the
  agent-vitals census of 2026-09-23, an MCP Registry name search) → 22 builds by separate agents to
  `BUILD-STANDARDS.md` → adversarial review and fixes for thirteen. Standard library only everywhere; every
  published figure, threshold and legal statement carries its primary source and date; every data licence was
  checked (OGL v3, CC BY 4.0, CC0, the EUR-Lex notice with Decision 2011/833/EU; sources whose terms forbid
  redistribution or commercial use were left out, see the backlog).
- **Things agents did outside their brief**, reported so nothing is hidden: the 103 builder read the README of
  `punkpeye/awesome-mcp-servers` on GitHub to test against a real list; the 118 builder fetched the `action.yml`
  of `actions/checkout` and `actions/setup-python` once; the 120 builder, testing, sent three made-up tokens (no
  real credential) to api.github.com directly instead of through the sandbox proxy. Reviewers ran the Claude Code
  CLI against a local mock API with a placeholder key to verify hook behaviour. All read-only or fake; none of it
  is in the shipped code.
