"""Unit tests for scripts/gated_paths.py.

The trigger set used to live in the `.githooks/pre-commit` script and was
mirrored by hand in AGENTS.md. It now has one home, and these tests are what
stop a second copy from creeping back in.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gated_paths  # noqa: E402  (path set up above)


class GatedPathsTests(unittest.TestCase):
    def test_agents_md_documents_the_current_trigger_set(self):
        self.assertTrue(
            gated_paths.check_agents_md(),
            "AGENTS.md does not document the current trigger set; "
            "regenerate the block with `python3 scripts/gated_paths.py --markdown`",
        )

    def test_every_gated_path_exists(self):
        for path in gated_paths.GATED_PATHS:
            if path.endswith("/"):
                self.assertTrue((ROOT / path).is_dir(), path)
            else:
                self.assertTrue((ROOT / path).exists(), path)

    def test_every_derived_path_exists(self):
        for path in gated_paths.DERIVED_PATHS:
            self.assertTrue((ROOT / path).exists(), path)

    def test_the_trigger_set_source_is_itself_gated(self):
        self.assertIn("scripts/gated_paths.py", gated_paths.GATED_PATHS)

    def test_derived_paths_are_gated_or_the_readme(self):
        for path in gated_paths.DERIVED_PATHS:
            if path == "README.md":
                continue  # README.md is compared for drift, but is not a trigger
            self.assertIn(path, gated_paths.GATED_PATHS)

    def test_filter_matches_exact_paths_and_directory_prefixes(self):
        staged = [
            "starred_repos.csv",
            "README.md",
            "tests/test_build.py",
            "tests/nested/deep.py",
            "scripts/build.py",
            "scripts/something_else.py",
        ]
        self.assertEqual(
            gated_paths.filter_gated(staged),
            ["starred_repos.csv", "tests/test_build.py", "tests/nested/deep.py", "scripts/build.py"],
        )

    def test_filter_does_not_match_a_prefix_that_is_not_a_directory(self):
        self.assertEqual(gated_paths.filter_gated(["testsfoo/bar.py"]), [])

    def test_the_hooks_do_not_hardcode_the_trigger_set(self):
        hooks = ROOT / ".githooks"
        for hook in sorted(hooks.iterdir()):
            if hook.suffix != ".sh" and hook.name not in ("pre-commit", "pre-push"):
                continue
            text = hook.read_text(encoding="utf-8")
            self.assertNotIn("GATED_PATHS=(", text, f"{hook.name} hardcodes the trigger set")

    def test_check_agents_md_reports_a_stale_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "AGENTS.md"
            stale.write_text(
                f"{gated_paths.MARKER_START}\n- `stale.csv`\n{gated_paths.MARKER_END}\n",
                encoding="utf-8",
            )
            original = gated_paths.AGENTS_MD
            gated_paths.AGENTS_MD = stale
            try:
                self.assertFalse(gated_paths.check_agents_md())
            finally:
                gated_paths.AGENTS_MD = original

    def test_check_agents_md_reports_a_missing_marker_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            unmarked = Path(tmp) / "AGENTS.md"
            unmarked.write_text("# No markers here\n", encoding="utf-8")
            original = gated_paths.AGENTS_MD
            gated_paths.AGENTS_MD = unmarked
            try:
                self.assertFalse(gated_paths.check_agents_md())
            finally:
                gated_paths.AGENTS_MD = original


if __name__ == "__main__":
    unittest.main()
