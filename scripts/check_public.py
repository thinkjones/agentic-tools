#!/usr/bin/env python3
"""Fail if starred_repos.csv lists any repository that is not public on GitHub.

Uses the gh CLI (signed in) so that private repositories you can see are
reported as private instead of as missing.

    python3 scripts/check_public.py
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "starred_repos.csv"
BATCH = 50


def main():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        names = [row["Repo"] for row in csv.DictReader(f)]

    not_public = []
    for start in range(0, len(names), BATCH):
        batch = names[start : start + BATCH]
        fields = "".join(
            f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ visibility }} "
            for i, (owner, name) in enumerate(n.split("/", 1) for n in batch)
        )
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query=query {{ {fields} }}"],
            capture_output=True,
            text=True,
        )
        try:
            data = json.loads(result.stdout).get("data") or {}
        except json.JSONDecodeError:
            sys.exit(f"gh api failed: {result.stderr.strip() or result.stdout.strip()}")
        if not data:
            sys.exit(f"gh api returned no data: {result.stderr.strip() or result.stdout.strip()}")
        for i, name in enumerate(batch):
            repo = data.get(f"r{i}")
            if not repo or repo["visibility"] != "PUBLIC":
                not_public.append((name, repo["visibility"] if repo else "NOT FOUND"))

    for name, state in not_public:
        print(f"{state:10} {name}")
    if not_public:
        sys.exit(f"{len(not_public)} of {len(names)} repos are not public. Remove them before publishing.")
    print(f"All {len(names)} repos are public.")


if __name__ == "__main__":
    main()
