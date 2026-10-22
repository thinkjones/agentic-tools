#!/usr/bin/env bash
#
# The repository gate, shared by .githooks/pre-commit and .githooks/pre-push.
#
#   .githooks/gate.sh              check the staged tree
#   .githooks/gate.sh --staged     check the staged tree, but only when a
#                                  gated path is staged
#   .githooks/gate.sh --tree <sha> check the tree at <sha>
#
# Everything the gate reads comes from the tree under test, never from the
# working tree: the trigger set, the list of generated files and the scripts
# themselves. So the gate checks exactly the tree that is about to be
# committed or pushed, and a tree that carries its own configuration always
# gets checked against that configuration.
#
# The gate runs scripts/build.py against a scratch copy of the tree under
# test, so the working tree is never written to, and refuses when the
# generated files in that tree disagree with the generator. It then runs the
# unit tests and the visibility check, both against the same scratch copy.
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

# --- 1. Materialise the tree under test into a scratch copy. -----------------

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/agentic-tools-gate.XXXXXX")" \
  || refuse "cannot create a scratch directory."

# The commit before the tree under test, used to tell "this tree predates
# the gate" apart from "this commit removes the gate".
PARENT=""
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
  PARENT="$(git rev-parse "$TARGET^" 2>/dev/null)"
else
  if ! git checkout-index --all --prefix="$SCRATCH/"; then
    refuse "cannot materialise the index into $SCRATCH."
  fi
  BASE_REF=":"
  PARENT="$(git rev-parse HEAD 2>/dev/null)"
fi

had_path() {
  [ -n "$PARENT" ] || return 1
  git cat-file -e "$PARENT:$1" 2>/dev/null
}

# --- 2. The tree under test has to carry the gate's own machinery. ----------
#
# A tree from before the gate existed has nothing to gate against, so the
# gate says so and lets it through. A commit that *removes* the machinery is
# different: it would switch the gate off, so it is refused. CI catches the
# removal either way, because the test suite imports the configuration.

if [ ! -f "$SCRATCH/scripts/gated_paths.py" ]; then
  if had_path "scripts/gated_paths.py"; then
    refuse "this commit removes scripts/gated_paths.py, which is the gate's configuration. Removing it switches the gate off; keep it."
  fi
  printf '%s: this tree predates the gate; it has no scripts/gated_paths.py, so there is nothing to gate. Skipping the gate.\n' "$LABEL"
  exit 0
fi

if [ ! -f "$SCRATCH/scripts/run_tests.py" ]; then
  if had_path "scripts/run_tests.py"; then
    refuse "this commit removes scripts/run_tests.py, which is the test runner. Removing it switches the tests off; keep it."
  fi
elif [ ! -d "$SCRATCH/tests" ]; then
  refuse "the tree under test has scripts/run_tests.py but no tests/ directory, so the suite would collect nothing. Restore the tests, or remove the runner as well."
fi

# --- 3. Decide whether the gate fires. ---------------------------------------

if [ "$MODE" = "staged" ]; then
  GATED=""
  if ! GATED="$(git diff --cached --name-only | python3 "$SCRATCH/scripts/gated_paths.py" --filter)"; then
    refuse "scripts/gated_paths.py failed to read the staged paths."
  fi
  if [ -z "$GATED" ]; then
    exit 0
  fi
fi

# --- 4. Refuse a half-staged CSV before running anything. --------------------
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

# --- 5. Rebuild from the tree under test. ------------------------------------

if ! python3 "$SCRATCH/scripts/build.py"; then
  refuse "scripts/build.py failed on the tree under test. The message above is the generator's own. Your working tree was not touched."
fi

# --- 6. Refuse a generated file that disagrees with the generator. -----------

DERIVED_PATHS=""
if ! DERIVED_PATHS="$(python3 "$SCRATCH/scripts/gated_paths.py" --derived)"; then
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
    printf 'Rebuild them from the CSV in that commit and push the rebuild:\n\n' >&2
    printf '  git checkout %s\n' "$TARGET" >&2
    printf '  python3 scripts/build.py && git add%s\n' "$REMEDY_FILES" >&2
    printf '  git commit -m "Rebuild the generated files" && git push\n\n' >&2
  else
    printf '\nRegenerate them from the staged CSV, stage the result, and try again:\n\n' >&2
    printf '  python3 scripts/build.py && git add%s\n\n' "$REMEDY_FILES" >&2
  fi
  exit 1
fi

# --- 7. Run the unit tests. --------------------------------------------------

if [ -f "$SCRATCH/scripts/run_tests.py" ]; then
  if ! python3 "$SCRATCH/scripts/run_tests.py"; then
    refuse "the unit tests failed. The output above is the suite's own."
  fi
else
  printf '%s: this tree has no test suite; skipping the unit tests.\n' "$LABEL"
fi

# --- 8. Run the visibility check. -------------------------------------------

printf '%s: checking that every repo in starred_repos.csv is public (about 15 seconds)...\n' "$LABEL"
if ! python3 "$SCRATCH/scripts/check_public.py"; then
  refuse "scripts/check_public.py failed: either a repo is not public, or the check could not run. Both refuse to continue."
fi

# --- 9. Exit 0. -------------------------------------------------------------

exit 0
