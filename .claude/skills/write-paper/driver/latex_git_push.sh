#!/usr/bin/env bash
# latex_git_push.sh — push a produced paper to a LaTeX git repository.
#
#   bash latex_git_push.sh <paper.tex> ["commit message"]
#
# Works with any git remote that serves the paper repo over HTTPS with token
# (HTTP Basic) auth — e.g. Overleaf, GitHub, GitLab. Outward action: the main
# agent confirms with the operator before calling this (red line: anything that
# leaves the machine). Credentials are read from a gitignored secrets file (NEVER
# committed). Default: <repo>/config/latex-git.env, override with LATEX_GIT_ENV_FILE.
# It must define (chmod 600):
#     LATEX_GIT_URL=https://git.example.com/<project>     # e.g. Overleaf: https://git.overleaf.com/<project-id>
#     LATEX_GIT_TOKEN=<git access token>
#     # optional: LATEX_GIT_AUTHOR_NAME / LATEX_GIT_AUTHOR_EMAIL for the commit
#
# If the file or a value is missing, this exits non-zero with a clear message so
# the main agent can ask the operator, store the values, and retry. Commit
# messages are plain — NO AI co-author trailer (this is an academic paper repo).
set -u

TEX="${1:-}"
MSG="${2:-Update paper}"
[ -n "$TEX" ] && [ -f "$TEX" ] || { echo "latex_git_push: no such .tex: '$TEX'" >&2; exit 2; }

# repo root = .../.claude/skills/write-paper/driver/latex_git_push.sh -> parents[4]
_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SECRETS="${LATEX_GIT_ENV_FILE:-$_REPO/config/latex-git.env}"
if [ ! -f "$SECRETS" ]; then
  echo "latex_git_push: missing $SECRETS — ask the operator for the paper repo URL + git token" >&2
  echo "  (e.g. an Overleaf project's git URL + token), write them there (chmod 600), then retry. NEVER commit this file." >&2
  exit 4
fi
# shellcheck disable=SC1090
source "$SECRETS"
: "${LATEX_GIT_URL:?latex_git_push: LATEX_GIT_URL not set in $SECRETS}"
: "${LATEX_GIT_TOKEN:?latex_git_push: LATEX_GIT_TOKEN not set in $SECRETS}"

# Authenticate via an HTTP Basic header (username "git", token as password) so the
# token never enters the URL — avoids sed-delimiter/metachar mangling and keeps the
# live credential out of the cloned repo's .git/config remote URL.
_AUTH_HEADER="Authorization: Basic $(printf 'git:%s' "$LATEX_GIT_TOKEN" | base64 | tr -d '\n')"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/latex_git_XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
echo "latex_git_push: cloning ${LATEX_GIT_URL} ..."
git -c http.extraHeader="$_AUTH_HEADER" clone --quiet --depth 1 "$LATEX_GIT_URL" "$WORK/repo" || { echo "latex_git_push: clone failed (check URL/token)" >&2; exit 1; }

cp "$TEX" "$WORK/repo/$(basename "$TEX")"
PDF="${TEX%.tex}.pdf"
[ -f "$PDF" ] && cp "$PDF" "$WORK/repo/$(basename "$PDF")"

cd "$WORK/repo" || exit 1
git config user.name  "${LATEX_GIT_AUTHOR_NAME:-$(git config user.name  || echo paper)}"
git config user.email "${LATEX_GIT_AUTHOR_EMAIL:-$(git config user.email || echo paper@local)}"
git add -A
if git diff --cached --quiet; then
  echo "latex_git_push: no changes to push"
  exit 0
fi
git commit --quiet -m "$MSG"
git -c http.extraHeader="$_AUTH_HEADER" push --quiet origin HEAD && echo "latex_git_push: pushed $(basename "$TEX") to ${LATEX_GIT_URL}"
