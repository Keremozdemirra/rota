#!/usr/bin/env bash
# publish.sh — moves one staged project out of projects/ into its own public
# GitHub repository.
#
#   bash projects/publish.sh <project-dirname> <repo-name>
#   bash projects/publish.sh 101-mcp-vitals mcp-vitals
#
# Deterministic, like ship.sh: same secret scan, nothing forced, and it asks
# before it creates anything public. The project directory is copied, never
# moved, so rota keeps its copy until you delete it on purpose.
set -euo pipefail

DIRNAME="${1:?usage: publish.sh <project-dirname> <repo-name>}"
REPO="${2:?usage: publish.sh <project-dirname> <repo-name>}"
OWNER="${PUBLISH_OWNER:-Keremozdemirra}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/projects/$DIRNAME"

[ -d "$SRC" ] || { echo "publish: $SRC does not exist" >&2; exit 1; }
command -v gh >/dev/null || { echo "publish: gh is not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "publish: run 'gh auth login' first" >&2; exit 1; }
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "publish: $OWNER/$REPO already exists; nothing done" >&2
  exit 1
fi

# --- secret scan (the patterns ship.sh uses) -----------------------------
PATTERNS='sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}'
if grep -rEIl "$PATTERNS" "$SRC" 2>/dev/null | grep -q .; then
  echo "publish: ABORT — possible credential in $SRC:" >&2
  grep -rEIl "$PATTERNS" "$SRC" >&2
  exit 3
fi

# The description GitHub shows is the one pyproject already carries.
DESC="$(sed -n 's/^description = "\(.*\)"$/\1/p' "$SRC/pyproject.toml" 2>/dev/null | head -1)"

echo "About to create a PUBLIC repository $OWNER/$REPO from projects/$DIRNAME"
echo "  description: ${DESC:-<none>}"
read -r -p "Type the repository name to confirm: " ANSWER
[ "$ANSWER" = "$REPO" ] || { echo "publish: not confirmed; nothing done"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R "$SRC/." "$WORK/"
rm -f "$WORK"/.rota-*.md
find "$WORK" -name __pycache__ -type d -prune -exec rm -rf {} +

cd "$WORK"
git init --quiet -b main
git add -A
git commit --quiet -m "Initial import from rota/projects/$DIRNAME"
gh repo create "$OWNER/$REPO" --public --source . --push --description "$DESC"

cat <<EOF

Created https://github.com/$OWNER/$REPO

To publish on PyPI (once per project, no token involved):
  1. https://pypi.org/manage/account/publishing/ → "Add a new pending publisher"
     PyPI project name: $(sed -n 's/^name = "\(.*\)"$/\1/p' "$SRC/pyproject.toml" | head -1)
     Owner: $OWNER   Repository: $REPO   Workflow: release.yml   Environment: pypi
  2. gh release create v$(sed -n 's/^version = "\(.*\)"$/\1/p' "$SRC/pyproject.toml" | head -1) --repo $OWNER/$REPO --generate-notes
EOF
