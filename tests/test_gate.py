"""Integration tests for .githooks/gate.sh.

The unit tests cover the pieces. These cover the decision the hook actually
makes: does the gate fire for a staged path, and does it take the trigger
set from the tree under test rather than from a copy of the list?

Each test builds a scratch repository holding the real scripts and runs the
real hook against it, with a fake `gh` on PATH so nothing touches the
network.
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

FAKE_GH = """#!/usr/bin/env python3
import json
import re
import sys

query = ""
for arg in sys.argv[1:]:
    if arg.startswith("query="):
        query = arg[len("query="):]

count = len(re.findall(r"repository\\(owner:", query))
data = {}
for i in range(count):
    data["r" + str(i)] = {"visibility": "PUBLIC"}
print(json.dumps({"data": data}))
"""

CSV_COLUMNS = [
    "Proposed List", "Repo", "URL", "Stars", "Forks", "Activity", "Last Push", "Last Release",
    "Release Date", "License", "Language", "Homepage", "Topics", "Description", "Starred On",
]

README = """# Scratch

<!-- summary:start -->
<!-- summary:end -->

<!-- contents:start -->
<!-- contents:end -->

<!-- lists:start -->
<!-- lists:end -->
"""

SCRATCHED = (".githooks/gate.sh", "scripts/gated_paths.py", "scripts/build.py", "scripts/check_public.py")

# git exports GIT_DIR and GIT_INDEX_FILE to the hooks it runs, so a git
# command started inside a hook inherits the outer repository's git
# environment and silently operates on the outer repository instead of the
# one it was pointed at. Every git command in these tests runs with those
# variables cleared, so the scratch repository is the only repository they
# can touch.
INHERITED_GIT_VARS = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


def clean_git_env():
    env = dict(os.environ)
    for name in INHERITED_GIT_VARS:
        env.pop(name, None)
    return env


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.install_fake_gh()
        self.run_git("init", "-q", ".")
        self.write_csv()
        (self.repo / "README.md").write_text(README, encoding="utf-8")
        for name in SCRATCHED:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.run_git("add", "-A")
        # Build once so the scratch repository starts with its generated files
        # in sync with the CSV, the way a real clone is.
        self.build()
        self.run_git("add", "-A")
        self.run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

    def install_fake_gh(self):
        path = self.bin / "gh"
        path.write_text(FAKE_GH.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
        path.chmod(0o755)

    def write_csv(self, name="acme/alpha"):
        with (self.repo / "starred_repos.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writeheader()
            writer.writerow(
                {
                    "Proposed List": "Tools",
                    "Repo": name,
                    "URL": "https://github.com/" + name,
                    "Stars": "10",
                    "Forks": "1",
                    "Activity": "Active",
                    "Last Push": "2026-10-01",
                    "Last Release": "",
                    "Release Date": "",
                    "License": "MIT",
                    "Language": "Python",
                    "Homepage": "",
                    "Topics": "agents",
                    "Description": "A repo",
                    "Starred On": "2026-01-01",
                }
            )

    def build(self):
        result = subprocess.run(
            [sys.executable, str(self.repo / "scripts/build.py")],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"scripts/build.py failed: {result.stderr}")

    def run_git(self, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=False,
            env=clean_git_env(),
        )
        if result.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {result.stderr}")
        return result

    def run_gate(self):
        environment = clean_git_env()
        environment["PATH"] = f"{self.bin}{os.pathsep}{environment['PATH']}"
        return subprocess.run(
            [str(self.repo / ".githooks/gate.sh"), "--staged"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def touch(self, name, text="# a change\n"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.run_git("add", name)

    def test_the_scratch_repository_is_isolated_from_the_outer_one(self):
        """git exports GIT_DIR and GIT_INDEX_FILE to the hooks it runs. A git
        command started inside a hook must not inherit them, or it commits to
        the outer repository instead of the scratch one."""
        git_dir = Path(self.run_git("rev-parse", "--absolute-git-dir").stdout.strip())
        self.assertEqual(git_dir, (self.repo / ".git").resolve())
        subject = self.run_git("log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, "init")

    def test_the_gate_stays_quiet_when_nothing_gated_is_staged(self):
        self.touch("NOTES.md", "a note\n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("checking that every repo", result.stdout)

    def test_the_gate_fires_for_a_gated_path(self):
        self.touch("scripts/build.py", "# a change\n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checking that every repo", result.stdout)

    def test_the_gate_fires_for_a_path_under_the_tests_directory(self):
        self.touch("tests/test_x.py", "x = 1\n")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checking that every repo", result.stdout)

    def test_the_gate_reads_the_trigger_set_from_the_tree_under_test(self):
        """The staged tree's configuration decides, not the working tree's."""
        # Commit a configuration that no longer gates the CSV...
        config = self.repo / "scripts/gated_paths.py"
        original = config.read_text(encoding="utf-8")
        config.write_text(original.replace('    "starred_repos.csv",\n', ""), encoding="utf-8")
        self.run_git("add", "scripts/gated_paths.py")
        self.run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "drop the csv trigger")

        # ...then put the original configuration back in the working tree,
        # un-staged, and stage a CSV change. The tree under test says the CSV
        # is not a trigger, so the gate must not fire.
        config.write_text(original, encoding="utf-8")
        self.write_csv(name="acme/gamma")
        self.run_git("add", "starred_repos.csv")
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("checking that every repo", result.stdout)

    def test_the_gate_refuses_a_commit_that_removes_its_own_configuration(self):
        self.run_git("rm", "-q", "scripts/gated_paths.py")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("removes scripts/gated_paths.py", result.stderr)

    def test_the_gate_refuses_a_commit_that_removes_the_test_runner(self):
        self.touch("scripts/run_tests.py", "# a test runner\n")
        self.run_git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "add a runner")
        self.run_git("rm", "-q", "scripts/run_tests.py")
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("removes scripts/run_tests.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
