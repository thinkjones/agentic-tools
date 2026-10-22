#!/usr/bin/env python3
"""Wire this clone's git hooks to the .githooks directory.

    python3 scripts/setup_hooks.py          # wire the hooks
    python3 scripts/setup_hooks.py --check  # report the wiring, change nothing

The gate lives in .githooks/ and is tracked by git, so the wiring is one
setting per clone:

    git config core.hooksPath .githooks

For a brand new clone the setting can be made at clone time, with no second
command at all:

    git clone --config core.hooksPath=.githooks <url>

This script does that setting for an existing clone, and reports what it
did. It is idempotent: running it twice changes nothing the second time.
"""

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".githooks"
HOOKS_PATH = ".githooks"
HOOK_NAMES = ("pre-commit", "pre-push")


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def current_hooks_path():
    result = git("config", "--local", "--get", "core.hooksPath")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def hook_is_executable(name):
    path = HOOKS_DIR / name
    if not path.exists():
        return False
    return bool(path.stat().st_mode & stat.S_IXUSR)


def report():
    configured = current_hooks_path()
    wired = configured == HOOKS_PATH
    print(f"core.hooksPath: {configured if configured else '(unset)'}")
    for name in HOOK_NAMES:
        path = HOOKS_DIR / name
        if not path.exists():
            print(f"  {name}: MISSING")
            continue
        state = "executable" if hook_is_executable(name) else "not executable"
        print(f"  {name}: {state}")
    if wired:
        print("\nThe gate is wired for this clone: commits and pushes are checked.")
    else:
        print("\nThe gate is NOT running for this clone.")
        print("  python3 scripts/setup_hooks.py")
    return 0 if wired else 1


def wire():
    if not HOOKS_DIR.is_dir():
        sys.exit(f"error: {HOOKS_DIR} is missing; there are no hooks to wire.")
    missing = [name for name in HOOK_NAMES if not (HOOKS_DIR / name).exists()]
    if missing:
        sys.exit(f"error: missing hook(s): {', '.join(missing)}")

    already = current_hooks_path() == HOOKS_PATH
    if not already:
        result = git("config", "--local", "core.hooksPath", HOOKS_PATH)
        if result.returncode != 0:
            sys.exit(f"error: git config failed: {result.stderr.strip() or result.stdout.strip()}")

    # git tracks the executable bit, but a checkout that crossed a filesystem
    # without one leaves the hooks unreadable. Make sure they can run.
    for name in HOOK_NAMES:
        path = HOOKS_DIR / name
        mode = path.stat().st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if already:
        print(f"core.hooksPath is already {HOOKS_PATH}; nothing to change.")
    else:
        print(f"Set core.hooksPath to {HOOKS_PATH} for this clone.")
    print("Commits and pushes now run the gate in .githooks/.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report the wiring without changing it")
    args = parser.parse_args()
    if args.check:
        sys.exit(report())
    sys.exit(wire())


if __name__ == "__main__":
    main()
