#!/usr/bin/env python3
"""Set the GitHub repo's description, homepage and topics from .github/repo.toml.

    python3 scripts/sync_repo_meta.py            # show what would be set
    python3 scripts/sync_repo_meta.py --apply    # set it on GitHub

Needs Python 3.11+ and the gh CLI, signed in with admin rights on the repo.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_DESCRIPTION = 350
MAX_TOPICS = 20


def fail(message):
    sys.exit(f"error: {message}")


def gh(method, path, payload):
    proc = subprocess.run(
        ["gh", "api", "-X", method, path, "--input", "-"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        fail(f"gh api {method} {path} failed: {proc.stderr.strip() or proc.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="change the repo on GitHub")
    args = parser.parse_args()

    config = tomllib.loads((ROOT / ".github" / "repo.toml").read_text(encoding="utf-8"))
    repos = tomllib.loads((ROOT / "starred_repos.toml").read_text(encoding="utf-8"))["repos"]
    description = config["description"].format(count=len(repos), lists=len({r["list"] for r in repos}))
    topics = config["topics"]

    if len(description) > MAX_DESCRIPTION:
        fail(f"description is {len(description)} characters; GitHub allows {MAX_DESCRIPTION}")
    if len(topics) > MAX_TOPICS:
        fail(f"{len(topics)} topics; GitHub allows {MAX_TOPICS}")
    bad = [t for t in topics if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", t)]
    if bad:
        fail("topics must be lower-case letters, digits and hyphens: " + ", ".join(bad))

    print(f"{config['repo']}\n  description  {description}\n  homepage     {config['homepage']}\n  topics       {', '.join(topics)}")
    if not args.apply:
        print("\nDry run. Add --apply to set this on GitHub.")
        return
    gh("PATCH", f"repos/{config['repo']}", {"description": description, "homepage": config["homepage"]})
    gh("PUT", f"repos/{config['repo']}/topics", {"names": topics})
    print("\nDone.")


if __name__ == "__main__":
    main()
