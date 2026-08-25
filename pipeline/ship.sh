#!/usr/bin/env bash
# ship.sh — the only thing in the pipeline that touches git.
#
#   ship.sh <project-dirname> <pr-body>
#
# Deterministic on purpose. The model produced the files; this decides what
# happens to them. No force push, no history rewrite, no branch deletion, and
# a secret scan that aborts before anything is committed rather than after.
set -euo pipefail

DIRNAME="${1:?usage: ship.sh <project-dirname> <pr-body>}"
BODY="${2:-Automated weekly build.}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="projects/${DIRNAME}"
BRANCH="weekly/${DIRNAME}"

cd "$ROOT"

[ -d "$TARGET" ] || { echo "ship: $TARGET does not exist" >&2; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "ship: not a git repository" >&2; exit 1; }

# --- secret scan --------------------------------------------------------
# Cheap, deliberately noisy. A false positive costs one manual look; a false
# negative costs a key rotation and a public repository with a live token in it.
PATTERNS='sk-ant-[A-Za-z0-9_-]{20}|sk-[A-Za-z0-9]{32}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|r8_[A-Za-z0-9]{32}'
if grep -rEIl --exclude-dir=.git "$PATTERNS" "$TARGET" 2>/dev/null | grep -q .; then
  echo "ship: ABORT — possible credential in $TARGET:" >&2
  grep -rEIl --exclude-dir=.git "$PATTERNS" "$TARGET" >&2
  exit 3
fi

# Working notes from the phases are for the reviewer, not the repository.
rm -f "$TARGET"/.rota-*.md 2>/dev/null || true

# --- branch -------------------------------------------------------------
DEFAULT_BRANCH="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|origin/||' || echo main)"
git fetch --quiet origin "$DEFAULT_BRANCH" 2>/dev/null || true
git checkout --quiet -B "$BRANCH"

git add -- "$TARGET" BACKLOG.md
if git diff --cached --quiet; then
  echo "ship: nothing to commit" >&2
  exit 4
fi

git -c user.name="rota weekly" -c user.email="noreply@localhost" \
    commit --quiet -m "$(printf '%s\n\n%s\n' "${DIRNAME}: weekly autonomous build" "$BODY")"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "ship: committed to $BRANCH (no remote configured)"
  exit 0
fi

git push --quiet --set-upstream origin "$BRANCH"

if command -v gh >/dev/null 2>&1; then
  gh pr create --base "$DEFAULT_BRANCH" --head "$BRANCH" \
     --title "${DIRNAME}: weekly autonomous build" --body "$BODY" \
     || echo "ship: pushed, but gh pr create failed — open the PR by hand" >&2
else
  echo "ship: pushed $BRANCH — gh not installed, open the PR by hand"
fi
