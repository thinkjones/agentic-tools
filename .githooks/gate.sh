#!/usr/bin/env bash
#
# The repository gate, shared by .githooks/pre-commit and .githooks/pre-push.
#
#   .githooks/gate.sh              check the staged tree
#   .githooks/gate.sh --staged     check the staged tree, but only when a
#                                  gated path is staged
#   .githooks/gate.sh --tree <sha> check the tree at <sha>
#
# The gate runs scripts/build.py against a scratch copy of the tree it is
# checking, so the working tree is never written to, and refuses when the
# generated files in that tree disagree with the generator. It then runs the
# unit tests and the visibility check, both against the same scratch copy,
# so every check sees exactly the tree that is about to be committed or
# pushed.
#
# Every check fails closed. A check that could not run refuses the commit
# rather than passing it: a gate that passes because it was skipped is
# worse than no gate, because it looks like evidence.
#
# Nothing is piped through head, grep or a captured variable: each script's
# output reaches the terminal exactly as it would from a manual run.

set -uo pipefail

LABEL="${GATE_LABEL:-gate}"
MODE="index"
TARGET=""
SCRATCH=""

refuse() {
  printf '\n%s: %s\n' "$LABEL" "$1" >&2
  exit 1
}

cleanup() {
  if [ -n "$SCRATCH" ] && [ -d "$SCRATCH" ]; then
    rm -rf "$SCRATCH"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

while [ $# -gt 0 ]; do
  case "$1" in
    --staged)
      MODE="staged"
      ;;
    --tree)
      MODE="tree"
      TARGET="${2:-}"
      shift
      ;;
    *)
      refuse "unknown option: $1"
      ;;
  esac
  shift
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$ROOT" ] || [ ! -d "$ROOT" ]; then
  refuse "not inside a git working tree."
fi
cd "$ROOT" || refuse "cannot enter the repository root at $ROOT."

if ! command -v python3 >/dev/null 2>&1; then
  refuse "python3 is not on PATH."
fi
if [ ! -f scripts/gated_paths.py ]; then
  # A tree from before the gate had its own configuration has nothing to
  # gate against. Say so and let it through; CI still checks everything.
  printf '%s: this tree has no gate configuration (scripts/gated_paths.py is missing); skipping the gate.\n' "$LABEL"
  exit 0
fi

# --- 1. Decide whether the gate fires. ---------------------------------------

if [ "$MODE" = "staged" ]; then
  GATED=""
  if ! GATED="$(git diff --cached --name-only | python3 scripts/gated_paths.py --filter)"; then
    refuse "scripts/gated_paths.py failed to read the staged paths."
  fi
  if [ -z "$GATED" ]; then
    exit 0
  fi
fi

# --- 2. Refuse a half-staged CSV before running anything. --------------------
#
# The gate checks the CSV that is staged. The rebuild it suggests on failure
# runs against the working tree, so the two have to be the same file: if they
# differ, the remedy rebuilds from a different CSV and the gate refuses
# again, which is a worse failure than refusing up front.

if [ "$MODE" != "tree" ]; then
  git diff --quiet -- starred_repos.csv
  CSV_STATUS=$?
  if [ "$CSV_STATUS" -eq 1 ]; then
    printf '\n%s: starred_repos.csv has unstaged changes.\n\n' "$LABEL" >&2
    printf 'The gate checks the CSV that is staged, and the rebuild it suggests runs\n' >&2
    printf 'against the working tree, so the two have to be the same file. Stage the\n' >&2
    printf 'whole file or stash the rest, then try again:\n\n' >&2
    printf '  git add starred_repos.csv\n\n' >&2
    exit 1
  fi
  if [ "$CSV_STATUS" -gt 1 ]; then
    refuse "git diff failed on starred_repos.csv."
  fi
fi

# --- 3. Materialise the tree under test into a scratch copy. -----------------

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/agentic-tools-gate.XXXXXX")" \
  || refuse "cannot create a scratch directory."

if [ "$MODE" = "tree" ]; then
  if [ -z "$TARGET" ]; then
    refuse "--tree needs a commit-ish."
  fi
  GATE_INDEX="$SCRATCH/.gate-index"
  rm -f "$GATE_INDEX"
  if ! GIT_INDEX_FILE="$GATE_INDEX" git read-tree "$TARGET"; then
    refuse "cannot read the tree at $TARGET."
  fi
  if ! GIT_INDEX_FILE="$GATE_INDEX" git checkout-index --all --prefix="$SCRATCH/"; then
    refuse "cannot materialise the tree at $TARGET into $SCRATCH."
  fi
  rm -f "$GATE_INDEX"
  BASE_REF="$TARGET:"
else
  if ! git checkout-index --all --prefix="$SCRATCH/"; then
    refuse "cannot materialise the index into $SCRATCH."
  fi
  BASE_REF=":"
fi

# --- 4. Rebuild from the tree under test. ------------------------------------

if ! python3 "$SCRATCH/scripts/build.py"; then
  refuse "scripts/build.py failed on the tree under test. The message above is the generator's own. Your working tree was not touched."
fi

# --- 5. Refuse a generated file that disagrees with the generator. -----------

DERIVED_PATHS=""
if ! DERIVED_PATHS="$(python3 scripts/gated_paths.py --derived)"; then
  refuse "scripts/gated_paths.py failed to list the generated files."
fi

DRIFTED=""
REMEDY_FILES=""
while IFS= read -r DERIVED; do
  [ -n "$DERIVED" ] || continue
  REMEDY_FILES="$REMEDY_FILES $DERIVED"
  if [ ! -f "$SCRATCH/$DERIVED" ]; then
    DRIFTED="$DRIFTED $DERIVED"
    continue
  fi
  if ! cmp -s <(git show "${BASE_REF}${DERIVED}" 2>/dev/null) "$SCRATCH/$DERIVED"; then
    DRIFTED="$DRIFTED $DERIVED"
  fi
done <<EOF
$DERIVED_PATHS
EOF

if [ -n "$DRIFTED" ]; then
  printf '\n%s: the generated files disagree with starred_repos.csv.\n\n' "$LABEL" >&2
  for DERIVED in $DRIFTED; do
    printf '  %s\n' "$DERIVED" >&2
    git diff --no-index --stat <(git show "${BASE_REF}${DERIVED}" 2>/dev/null) "$SCRATCH/$DERIVED" >&2 || true
  done
  if [ "$MODE" = "tree" ]; then
    printf '\nThat commit carries generated files that its own CSV does not produce.\n' >&2
    printf 'Rebuild them from the CSV in that commit, and push the rebuild:\n\n' >&2
    printf '  python3 scripts/build.py && git add%s\n\n' "$REMEDY_FILES" >&2
  else
    printf '\nRegenerate them from the staged CSV, stage the result, and try again:\n\n' >&2
    printf '  python3 scripts/build.py && git add%s\n\n' "$REMEDY_FILES" >&2
  fi
  exit 1
fi

# --- 6. Run the unit tests. --------------------------------------------------

if [ -f "$SCRATCH/scripts/run_tests.py" ]; then
  if ! python3 "$SCRATCH/scripts/run_tests.py"; then
    refuse "the unit tests failed. The output above is the suite's own."
  fi
elif [ "$MODE" != "tree" ] && [ -f scripts/run_tests.py ]; then
  refuse "the tree under test is missing scripts/run_tests.py but the working tree has it. Stage the file, or restore it."
else
  printf '%s: this tree has no test suite; skipping the unit tests.\n' "$LABEL"
fi

# --- 7. Run the visibility check. -------------------------------------------

printf '%s: checking that every repo in starred_repos.csv is public (about 15 seconds)...\n' "$LABEL"
if ! python3 "$SCRATCH/scripts/check_public.py"; then
  refuse "scripts/check_public.py failed: either a repo is not public, or the check could not run. Both refuse to continue."
fi

# --- 8. Exit 0. -------------------------------------------------------------

exit 0
