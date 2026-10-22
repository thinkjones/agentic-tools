#!/usr/bin/env python3
"""The single source of truth for the paths the local git gate watches.

`.githooks/pre-commit` and `.githooks/pre-push` read the trigger set from
here, and `tests/test_gated_paths.py` checks that AGENTS.md still documents
the same set. Change a path here and nowhere else.

    python3 scripts/gated_paths.py --gated     # the trigger set, one per line
    python3 scripts/gated_paths.py --derived    # the generated files, one per line
    python3 scripts/gated_paths.py --markdown   # the AGENTS.md bullet list
    python3 scripts/gated_paths.py --filter     # stdin: staged paths, stdout: the gated ones
    python3 scripts/gated_paths.py --check      # AGENTS.md still matches? exits non-zero if not
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = ROOT / "AGENTS.md"

# Staged paths that make the gate fire. README.md is deliberately absent: it
# is half generated and half narrative prose, so it is compared for drift
# (see DERIVED_PATHS) rather than used as a trigger.
#
# An entry ending in "/" is a directory: every staged path under it fires the
# gate. `scripts/gated_paths.py` is in the list because changing the trigger
# set has to be gated by the trigger set.
GATED_PATHS = (
    "starred_repos.csv",
    "starred_repos.toml",
    "starred_repos.json",
    "assets/readme/hero.svg",
    "assets/readme/lists.svg",
    "scripts/build.py",
    "scripts/check_public.py",
    "scripts/gated_paths.py",
    "tests/",
)

# Files the generator owns, compared against the generator's output on every
# gated commit. README.md is one of them.
DERIVED_PATHS = (
    "starred_repos.toml",
    "starred_repos.json",
    "assets/readme/hero.svg",
    "assets/readme/lists.svg",
    "README.md",
)

MARKER_START = "<!-- gated-paths:start -->"
MARKER_END = "<!-- gated-paths:end -->"


def is_gated(path):
    """True when a repo-relative staged path makes the gate fire."""
    path = path.strip()
    for gated in GATED_PATHS:
        if gated.endswith("/"):
            if path.startswith(gated):
                return True
        elif path == gated:
            return True
    return False


def filter_gated(paths):
    """The subset of `paths` that fires the gate, order preserved."""
    return [path for path in paths if is_gated(path)]


def markdown():
    """The AGENTS.md bullet list for the trigger set."""
    return "\n".join(f"- `{path}`" for path in GATED_PATHS)


def agents_md_block():
    """The bullet list AGENTS.md currently documents, or None when unmarked."""
    if not AGENTS_MD.exists():
        return None
    text = AGENTS_MD.read_text(encoding="utf-8")
    if MARKER_START not in text or MARKER_END not in text:
        return None
    body = text.split(MARKER_START, 1)[1].split(MARKER_END, 1)[0]
    return body.strip("\n")


def check_agents_md():
    """True when AGENTS.md documents exactly the trigger set."""
    return agents_md_block() == markdown()


def main():
    args = sys.argv[1:]
    if args == ["--gated"]:
        print("\n".join(GATED_PATHS))
    elif args == ["--derived"]:
        print("\n".join(DERIVED_PATHS))
    elif args == ["--markdown"]:
        print(markdown())
    elif args == ["--filter"]:
        for path in filter_gated(line for line in sys.stdin.read().splitlines()):
            print(path)
    elif args == ["--check"]:
        if not check_agents_md():
            print("error: AGENTS.md does not document the current trigger set.", file=sys.stderr)
            print("Regenerate the block with:", file=sys.stderr)
            print("  python3 scripts/gated_paths.py --markdown", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"usage: {sys.argv[0]} --gated|--derived|--markdown|--filter|--check", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
