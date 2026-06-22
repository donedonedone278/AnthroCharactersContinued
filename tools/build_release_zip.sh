#!/usr/bin/env bash
#
# Build the distributable Content Patcher mod zip for Anthro Characters Continued.
#
# This uses an explicit ALLOWLIST of paths (the INCLUDE array below) combined
# with `git archive`. `git archive` only ever packs *tracked* files, so anything
# gitignored or untracked is excluded by construction:
#   - api_keys.txt        (gitignored secret)
#   - CLAUDE.md           (git-excluded local notes)
#   - claude-documentation/ (git-excluded local notes)
#   - .vscode/            (gitignored)
#   - tools/              (not in the allowlist — repo tooling, not mod content)
#   - documentation/      (not in the allowlist — contributor docs, not mod content)
#   - .git/, *:Zone.Identifier, and any other stray junk
#
# To add/remove something from the shipped mod, edit the INCLUDE array — that is
# the single source of truth for what the zip contains.
#
# The zip mirrors the committed HEAD tree, so commit the version bump and any
# pending mod changes BEFORE running this (the release skill does that). The
# script refuses to build if the included paths have uncommitted/untracked
# changes, so the zip can never silently miss your edits.
#
# Usage:
#   tools/build_release_zip.sh [output-zip-path]
# Default output: dist/AnthroCharactersContinued.zip inside the repo (the dist/
# dir is gitignored, so the built zip is never committed).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIP_NAME="AnthroCharactersContinued.zip"
PREFIX="AnthroCharactersContinued/"   # top-level folder inside the zip

# --- Allowlist: exactly what ships in the mod zip --------------------------
INCLUDE=(
  manifest.json
  content.json
  README.md
  assets
  i18n
)
# ---------------------------------------------------------------------------

OUT="${1:-$REPO_DIR/dist/$ZIP_NAME}"

cd "$REPO_DIR"
mkdir -p "$(dirname "$OUT")"

# Guard: included paths must be fully committed, so the zip matches what you
# expect to ship. Catches both modified-tracked and brand-new-untracked files.
if ! git diff --quiet HEAD -- "${INCLUDE[@]}"; then
  echo "ERROR: uncommitted changes in included paths — commit them first." >&2
  git status --short -- "${INCLUDE[@]}" >&2
  exit 1
fi
untracked="$(git ls-files --others --exclude-standard -- "${INCLUDE[@]}")"
if [ -n "$untracked" ]; then
  echo "ERROR: untracked files under included paths — commit (or remove) them first:" >&2
  echo "$untracked" >&2
  exit 1
fi

rm -f "$OUT"
git archive --format=zip --prefix="$PREFIX" -o "$OUT" HEAD "${INCLUDE[@]}"

# --- Verify the result -----------------------------------------------------
echo "Built: $OUT"

# Capture the listing once (grepping a pipe under `pipefail` can SIGPIPE the
# producer and look like a failure).
listing="$(unzip -l "$OUT")"

# Nothing forbidden may appear. (git archive already guarantees this; this is a
# belt-and-suspenders check that fails loudly if the allowlist ever broadens.)
if grep -Ei 'api_keys|Zone\.Identifier|/CLAUDE\.md|claude-documentation|/tools/|/documentation/' <<<"$listing"; then
  echo "PROBLEM: forbidden file found in zip" >&2
  exit 1
fi

# Essentials must be present.
for required in manifest.json content.json assets/ i18n/; do
  if ! grep -q "${PREFIX}${required}" <<<"$listing"; then
    echo "PROBLEM: missing $required in zip" >&2
    exit 1
  fi
done

echo "zip clean"
