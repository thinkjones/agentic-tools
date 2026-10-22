#!/usr/bin/env python3
"""Run the repository's unit tests, and fail when none were collected.

    python3 scripts/run_tests.py

Exits non-zero when a test fails, and also when the suite collects zero
tests: a gate that runs nothing and reports success is worse than no gate
at all, because it looks like evidence.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def main():
    if not TESTS.is_dir():
        sys.exit(f"error: no test directory at {TESTS}")
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), top_level_dir=str(TESTS))
    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        sys.exit(1)
    count = suite.countTestCases()
    if count == 0:
        sys.exit(f"error: no tests were collected from {TESTS}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
