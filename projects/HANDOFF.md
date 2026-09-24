# Batch 2026-09-24: hand-off

Twenty-two projects are staged under `projects/101-*` to `projects/123-*` on the rota branch
`claude/oss-program-setup-cian0f` (121 was dropped; see the backlog). Every directory is self-contained:
`publish.sh` turns one into its own public repository. Nothing here has been published, no repository has
been created, and no token exists anywhere in these files.

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
117 vsme-kit, 110 financed-emissions, 114 eudr-scope-mcp, then the rest. Nothing depends on anything else, except
that agent-vitals PR #1 links to mcp-upkeep (merge it after mcp-upkeep is public).

## The projects

Names were checked on 2026-09-24: every repository name is free under Keremozdemirra, and every PyPI name is
free, including PyPI's "too similar to an existing project" rule (checked against the full PyPI index).
"Tests" is the offline unittest count; CI runs them on Python 3.9 and 3.12.

STATUS_TABLE

## Decisions for you

DECISIONS

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

NOTES
