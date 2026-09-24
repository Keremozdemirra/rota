# Batch 2026-09-24: hand-off

Twenty-two projects are staged under `projects/101-*` to `projects/123-*` on the rota branch
`claude/oss-program-setup-cian0f` (121 was dropped; see the backlog). Every directory is self-contained:
`publish.sh` turns one into its own public repository. Nothing here has been published, no repository has
been created, and no token exists anywhere in these files.

This branch is a staging area. Do not merge it into rota's `main`.

## Once, before the first project

```bash
cd ~/agents/rota
git fetch origin claude/oss-program-setup-cian0f
git worktree add ../rota-staging origin/claude/oss-program-setup-cian0f
cd ../rota-staging
gh auth status                 # must show Keremozdemirra
```

- A PyPI account with 2FA (pypi.org).
- For MCP servers only: install `mcp-publisher`
  (https://modelcontextprotocol.io/registry/quickstart, "Install mcp-publisher") and run
  `mcp-publisher login github` once.

## Per project, three or four steps

1. `bash projects/publish.sh <directory> <repo>`: secret scan, asks you to type the repository name, creates
   the public repository and pushes. It prints steps 2 and 3 with the right values.
2. PyPI trusted publisher, once per project: https://pypi.org/manage/account/publishing/ → "Add a new pending
   publisher" with the PyPI name, owner `Keremozdemirra`, the repository, workflow `release.yml`, environment `pypi`.
3. `gh release create v0.1.0 --repo Keremozdemirra/<repo> --generate-notes`: the release workflow runs the tests,
   checks that the tag matches the version, builds and publishes to PyPI. No token involved.
4. MCP servers only: in a checkout of the new repository, after the PyPI release is live, `mcp-publisher publish`
   (the `server.json` and the README's `mcp-name` line are already there).

## The projects

STATUS_TABLE

## Decisions for you

DECISIONS

## Not built, and why

BACKLOG

## Notes on how this batch was made

NOTES
