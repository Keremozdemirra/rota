#!/usr/bin/env bash
# publish.sh — moves one staged project out of projects/ into its own public
# GitHub repository.
#
#   bash projects/publish.sh <project-dirname> <repo-name>
#   bash projects/publish.sh 101-mcp-upkeep mcp-upkeep
#
# Deterministic, like ship.sh: same secret scan, nothing forced, and it asks
# before it creates anything public. Only what is committed on this branch is
# published (git archive), so stray local files — a test run's __pycache__, a
# build/ directory, a .env you put there — never leave the machine. The
# project directory is copied, never moved, so rota keeps its copy until you
# delete it on purpose.
set -euo pipefail

DIRNAME="${1:?usage: publish.sh <project-dirname> <repo-name>}"
REPO="${2:?usage: publish.sh <project-dirname> <repo-name>}"
DIRNAME="${DIRNAME%/}"
OWNER="${PUBLISH_OWNER:-Keremozdemirra}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/projects/$DIRNAME"

[ -d "$SRC" ] || { echo "publish: $SRC does not exist" >&2; exit 1; }
if [ -n "$(git -C "$ROOT" status --porcelain -- "projects/$DIRNAME")" ]; then
  echo "publish: projects/$DIRNAME has uncommitted changes; commit or discard them first" >&2
  echo "         (only committed files are published)" >&2
  exit 1
fi
command -v gh >/dev/null || { echo "publish: gh is not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "publish: run 'gh auth login' first" >&2; exit 1; }
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "publish: $OWNER/$REPO already exists; nothing done" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git -C "$ROOT" archive --format=tar HEAD "projects/$DIRNAME" | tar -x -C "$WORK" --strip-components=2
rm -f "$WORK"/.rota-*.md
[ -f "$WORK/pyproject.toml" ] || { echo "publish: projects/$DIRNAME has no committed pyproject.toml" >&2; exit 1; }

# --- secret scan (the patterns ship.sh uses) -----------------------------
PATTERNS='sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}'
if grep -rEIl "$PATTERNS" "$WORK" 2>/dev/null | grep -q .; then
  echo "publish: ABORT — possible credential in projects/$DIRNAME:" >&2
  grep -rEIl "$PATTERNS" "$WORK" | sed "s|^$WORK/|  |" >&2
  exit 3
fi

# The description GitHub shows is the one pyproject already carries.
DESC="$(sed -n 's/^description = "\(.*\)"$/\1/p' "$WORK/pyproject.toml" | head -1)"
NAME="$(sed -n 's/^name = "\(.*\)"$/\1/p' "$WORK/pyproject.toml" | head -1)"
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$WORK/pyproject.toml" | head -1)"

echo "About to create a PUBLIC repository $OWNER/$REPO from projects/$DIRNAME"
echo "  description: ${DESC:-<none>}"
echo "  files:       $(find "$WORK" -type f | wc -l | tr -d ' ') (committed tree of $(git -C "$ROOT" rev-parse --short HEAD))"
read -r -p "Type the repository name to confirm: " ANSWER
[ "$ANSWER" = "$REPO" ] || { echo "publish: not confirmed; nothing done"; exit 1; }

cd "$WORK"
git init --quiet -b main
git add -A
git commit --quiet -m "Initial import from rota/projects/$DIRNAME"
gh repo create "$OWNER/$REPO" --public --source . --push --description "$DESC"

cat <<EOF

Created https://github.com/$OWNER/$REPO

To publish on PyPI (once per project, no token involved):
  1. https://pypi.org/manage/account/publishing/ → "Add a new pending publisher"
     PyPI project name: $NAME
     Owner: $OWNER   Repository: $REPO   Workflow: release.yml   Environment: pypi
  2. gh release create v$VERSION --repo $OWNER/$REPO --generate-notes
EOF
if [ -f "$WORK/server.json" ]; then
  cat <<EOF
  3. MCP server: once https://pypi.org/project/$NAME/$VERSION/ is live, from a clone of
     $OWNER/$REPO run: mcp-publisher publish
EOF
fi
