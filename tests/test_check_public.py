"""Unit tests for scripts/check_public.py.

The visibility gate decides whether a repo may be published. It has to fail
closed: a gate that cannot run must not report success, or an unwired machine
turns into an unreviewed private repo on the live site.

The script is run as a subprocess against a scratch copy, with a fake `gh` on
PATH, so the tests are hermetic and exercise the real exit codes.
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_PUBLIC = ROOT / "scripts" / "check_public.py"

FAKE_GH = """#!/usr/bin/env python3
import json
import os
import re
import sys

query = ""
for arg in sys.argv[1:]:
    if arg.startswith("query="):
        query = arg[len("query="):]

mode = os.environ.get("FAKE_GH_MODE", "ok")
if mode == "unauthenticated":
    sys.stderr.write("To get started with GitHub CLI, please run: gh auth login\\n")
    sys.exit(4)

count = len(re.findall(r"repository\\(owner:", query))
data = {}
for i in range(count):
    data["r" + str(i)] = {"visibility": "PUBLIC"}
if mode == "one_private" and count > 1:
    data["r1"] = {"visibility": "PRIVATE"}
print(json.dumps({"data": data}))
"""


class CheckPublicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        shutil.copy2(CHECK_PUBLIC, self.scripts / "check_public.py")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.empty_bin = self.root / "empty-bin"
        self.empty_bin.mkdir()
        self.write_csv(["acme/alpha", "acme/beta", "acme/gamma"])

    def write_csv(self, names):
        with (self.root / "starred_repos.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writerow(["Repo"])
            for name in names:
                writer.writerow([name])

    def install_fake_gh(self):
        path = self.bin / "gh"
        path.write_text(FAKE_GH.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
        path.chmod(0o755)

    def run_check(self, path=None, mode="ok"):
        self.install_fake_gh()
        environment = dict(os.environ)
        environment["PATH"] = str(path if path is not None else self.bin)
        environment["FAKE_GH_MODE"] = mode
        environment.pop("GH_TOKEN", None)
        environment.pop("GITHUB_TOKEN", None)
        return subprocess.run(
            [sys.executable, str(self.scripts / "check_public.py")],
            capture_output=True,
            text=True,
            env=environment,
            cwd=str(self.root),
        )

    def test_check_public_fails_when_gh_is_missing(self):
        result = self.run_check(path=self.empty_bin)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("gh", result.stderr.lower())
        self.assertIn("install", result.stderr.lower())

    def test_check_public_fails_when_gh_is_not_authenticated(self):
        result = self.run_check(mode="unauthenticated")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("gh api failed", result.stderr.lower())

    def test_check_public_fails_when_a_repo_is_not_public(self):
        result = self.run_check(mode="one_private")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acme/beta", result.stdout)
        self.assertIn("PRIVATE", result.stdout)

    def test_check_public_passes_when_every_repo_is_public(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("All 3 repos are public.", result.stdout)


if __name__ == "__main__":
    unittest.main()
