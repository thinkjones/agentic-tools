"""Unit tests for scripts/build.py.

The build is the only thing that writes starred_repos.toml, starred_repos.json,
the two charts and the generated README blocks, so its invariants are the
repo's contract with the published site.
"""

import csv
import datetime
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402  (path set up above)

COLUMNS = [
    "Proposed List", "Repo", "URL", "Stars", "Forks", "Activity", "Last Push", "Last Release",
    "Release Date", "License", "Language", "Homepage", "Topics", "Description", "Starred On",
]

FULL_ROW = {
    "Proposed List": "AI · Agent Frameworks",
    "Repo": "acme/alpha",
    "URL": "https://github.com/acme/alpha",
    "Stars": "12345",
    "Forks": "678",
    "Activity": "Very active",
    "Last Push": "2026-10-01",
    "Last Release": "v1.2.3",
    "Release Date": "2026-09-30",
    "License": "MIT",
    "Language": "Python",
    "Homepage": "https://acme.example",
    "Topics": "agents, llm",
    "Description": "A tool, with a comma | and a pipe",
    "Starred On": "2026-01-15",
}

SPARSE_ROW = {
    "Proposed List": "Terminal",
    "Repo": "acme/beta",
    "URL": "https://github.com/acme/beta",
    "Stars": "10",
    "Forks": "0",
    "Activity": "Dormant",
    "Last Push": "2024-03-04",
    "Last Release": "",
    "Release Date": "",
    "License": "",
    "Language": "",
    "Homepage": "",
    "Topics": "",
    "Description": "",
    "Starred On": "2025-06-07",
}

QUOTED_ROW = {
    "Proposed List": "AI · Agent Frameworks",
    "Repo": "acme/gamma",
    "URL": "https://github.com/acme/gamma",
    "Stars": "500",
    "Forks": "9",
    "Activity": "Active",
    "Last Push": "2026-09-02",
    "Last Release": "",
    "Release Date": "",
    "License": "Apache-2.0",
    "Language": "TypeScript",
    "Homepage": "",
    "Topics": "agents",
    "Description": 'He said "hello" — naïve',
    "Starred On": "2026-02-03",
}

ROWS = [FULL_ROW, SPARSE_ROW, QUOTED_ROW]

README_TEMPLATE = """# Fixture

<!-- summary:start -->
the old summary
<!-- summary:end -->

Some narrative prose that must survive.

<!-- contents:start -->
the old contents
<!-- contents:end -->

<!-- lists:start -->
the old lists
<!-- lists:end -->

Trailing narrative.
"""


class BuildTestCase(unittest.TestCase):
    """Runs build.py against a scratch directory instead of the repository."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.orig_root, self.orig_csv = build.ROOT, build.CSV_PATH
        build.ROOT = self.root
        build.CSV_PATH = self.root / "starred_repos.csv"
        self.addCleanup(self.restore_paths)
        self.write_csv(ROWS)

    def restore_paths(self):
        build.ROOT, build.CSV_PATH = self.orig_root, self.orig_csv

    def write_csv(self, rows, encoding="utf-8-sig"):
        with build.CSV_PATH.open("w", encoding=encoding, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def write_readme_fixture(self, text=README_TEMPLATE):
        path = self.root / "README.md"
        path.write_text(text, encoding="utf-8")
        return path


class ParseTests(BuildTestCase):
    """The CSV -> repo dicts path."""

    def test_load_reads_every_csv_column_into_its_key(self):
        repo = build.load()[0]
        self.assertEqual(repo["repo"], "acme/alpha")
        self.assertEqual(repo["url"], "https://github.com/acme/alpha")
        self.assertEqual(repo["list"], "AI · Agent Frameworks")
        self.assertEqual(repo["activity"], "Very active")
        self.assertEqual(repo["last_release"], "v1.2.3")
        self.assertEqual(repo["license"], "MIT")
        self.assertEqual(repo["language"], "Python")
        self.assertEqual(repo["homepage"], "https://acme.example")
        self.assertEqual(repo["starred_on"], "2026-01-15")

    def test_load_coerces_stars_and_forks_to_int(self):
        repo = build.load()[0]
        self.assertEqual(repo["stars"], 12345)
        self.assertEqual(repo["forks"], 678)
        self.assertIsInstance(repo["stars"], int)

    def test_load_omits_cells_that_are_empty(self):
        repo = build.load()[1]
        self.assertNotIn("description", repo)
        self.assertNotIn("topics", repo)
        self.assertNotIn("license", repo)
        self.assertNotIn("last_release", repo)
        self.assertIn("stars", repo)

    def test_load_splits_topics_into_a_list(self):
        repo = build.load()[0]
        self.assertEqual(repo["topics"], ["agents", "llm"])

    def test_load_strips_surrounding_whitespace(self):
        row = dict(FULL_ROW, Topics="  agents , llm  ", Description="  padded  ")
        self.write_csv([row])
        repo = build.load()[0]
        self.assertEqual(repo["topics"], ["agents", "llm"])
        self.assertEqual(repo["description"], "padded")

    def test_load_reads_a_utf8_byte_order_mark(self):
        self.write_csv(ROWS, encoding="utf-8-sig")
        repo = build.load()[0]
        self.assertEqual(repo["repo"], "acme/alpha")
        self.assertEqual(repo["list"], "AI · Agent Frameworks")

    def test_load_keeps_dates_as_plain_strings(self):
        repo = build.load()[0]
        self.assertEqual(repo["last_push"], "2026-10-01")
        self.assertEqual(repo["release_date"], "2026-09-30")
        self.assertIsInstance(repo["last_push"], str)

    def test_load_keeps_the_csv_row_order(self):
        self.assertEqual([r["repo"] for r in build.load()], ["acme/alpha", "acme/beta", "acme/gamma"])

    def test_lists_of_groups_by_list_and_sorts_by_stars(self):
        groups = build.lists_of(build.load())
        self.assertEqual(sorted(groups), ["AI · Agent Frameworks", "Terminal"])
        self.assertEqual([r["repo"] for r in groups["AI · Agent Frameworks"]], ["acme/alpha", "acme/gamma"])
        self.assertEqual([r["repo"] for r in groups["Terminal"]], ["acme/beta"])

    def test_snapshot_date_is_the_latest_last_push(self):
        self.assertEqual(build.snapshot_date(build.load()), "2026-10-01")


class TomlTests(BuildTestCase):
    """The TOML emit path."""

    def test_write_toml_round_trips_to_the_csv(self):
        repos = build.load()
        build.write_toml(repos)
        parsed = tomllib.loads((self.root / "starred_repos.toml").read_text(encoding="utf-8"))["repos"]
        for item in parsed:
            for key in build.DATE_FIELDS & item.keys():
                item[key] = item[key].isoformat()
        self.assertEqual(parsed, repos)

    def test_write_toml_omits_empty_keys(self):
        build.write_toml(build.load())
        text = (self.root / "starred_repos.toml").read_text(encoding="utf-8")
        blocks = text.split("\n[[repos]]\n")
        alpha, beta = blocks[1], blocks[2]
        self.assertIn('license = "MIT"', alpha)
        self.assertNotIn("license", beta)
        self.assertNotIn("description", beta)
        self.assertNotIn("topics", beta)

    def test_write_toml_writes_dates_bare_and_ints_unquoted(self):
        build.write_toml(build.load())
        text = (self.root / "starred_repos.toml").read_text(encoding="utf-8")
        self.assertIn("last_push = 2026-10-01", text)
        self.assertIn("stars = 12345", text)

    def test_write_toml_writes_topics_as_an_array(self):
        build.write_toml(build.load())
        text = (self.root / "starred_repos.toml").read_text(encoding="utf-8")
        self.assertIn('topics = ["agents", "llm"]', text)

    def test_write_toml_meta_records_the_snapshot_and_count(self):
        build.write_toml(build.load())
        meta = tomllib.loads((self.root / "starred_repos.toml").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["snapshot"], datetime.date(2026, 10, 1))
        self.assertEqual(meta["count"], 3)
        self.assertEqual(meta["source"], build.SITE_URL)

    def test_write_toml_refuses_a_csv_it_cannot_represent(self):
        build.CSV_PATH.write_text(
            build.CSV_PATH.read_text(encoding="utf-8-sig").replace("2026-10-01", "not-a-date"),
            encoding="utf-8-sig",
        )
        with self.assertRaises(build.BuildError):
            build.write_toml(build.load())


class JsonTests(BuildTestCase):
    """The JSON emit path."""

    def test_write_json_round_trips_to_the_csv(self):
        repos = build.load()
        build.write_json(repos)
        doc = json.loads((self.root / "starred_repos.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["repos"], repos)

    def test_write_json_meta_records_the_snapshot_and_count(self):
        build.write_json(build.load())
        meta = json.loads((self.root / "starred_repos.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["snapshot"], "2026-10-01")
        self.assertEqual(meta["count"], 3)
        self.assertEqual(meta["source"], build.SITE_URL)


class ChartTests(BuildTestCase):
    """The two SVG charts."""

    def setUp(self):
        super().setUp()
        (self.root / "assets/readme").mkdir(parents=True, exist_ok=True)

    def test_write_hero_writes_an_svg_with_a_title_and_description(self):
        build.write_hero(build.load(), build.lists_of(build.load()))
        text = (self.root / "assets/readme/hero.svg").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<svg "))
        self.assertIn("<title id=\"title\">Agentic tools</title>", text)
        self.assertIn("<desc id=\"desc\">", text)

    def test_write_lists_chart_writes_one_row_per_list(self):
        groups = build.lists_of(build.load())
        build.write_lists_chart(groups)
        text = (self.root / "assets/readme/lists.svg").read_text(encoding="utf-8")
        for name in groups:
            self.assertIn(f">{name}<", text)

    def test_star_x_is_monotonic_and_capped_at_log_max(self):
        left, right = 10.0, 100.0
        xs = [build.star_x(s, left, right) for s in (0, 10, 1000, 100000, 10 ** 9)]
        self.assertEqual(xs, sorted(xs))
        self.assertAlmostEqual(xs[0], left)
        self.assertAlmostEqual(xs[-1], right)

    def test_swarm_keeps_every_dot_inside_the_max_offset(self):
        xs = [build.star_x(s, 0, 1000) for s in (10, 11, 12, 13, 14, 15)]
        offsets = build.swarm(xs, 5, 9)
        self.assertEqual(len(offsets), len(xs))
        for offset in offsets:
            self.assertLessEqual(abs(offset), 9)


class ReadmeTests(BuildTestCase):
    """The generated README blocks."""

    def test_write_readme_replaces_each_marked_block(self):
        path = self.write_readme_fixture()
        build.write_readme(build.load(), build.lists_of(build.load()))
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("the old summary", text)
        self.assertNotIn("the old contents", text)
        self.assertNotIn("the old lists", text)
        self.assertIn("3 public GitHub repositories", text)
        self.assertIn("| List | Repos | Most starred |", text)
        self.assertIn("### AI · Agent Frameworks", text)

    def test_write_readme_refuses_a_readme_without_the_markers(self):
        self.write_readme_fixture("# No markers here\n")
        with self.assertRaises(build.BuildError):
            build.write_readme(build.load(), build.lists_of(build.load()))

    def test_write_readme_leaves_the_narrative_around_the_markers_alone(self):
        path = self.write_readme_fixture()
        build.write_readme(build.load(), build.lists_of(build.load()))
        text = path.read_text(encoding="utf-8")
        self.assertIn("# Fixture", text)
        self.assertIn("Some narrative prose that must survive.", text)
        self.assertIn("Trailing narrative.", text)

    def test_write_readme_is_idempotent(self):
        path = self.write_readme_fixture()
        build.write_readme(build.load(), build.lists_of(build.load()))
        once = path.read_text(encoding="utf-8")
        build.write_readme(build.load(), build.lists_of(build.load()))
        self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_readme_blocks_escapes_pipes_and_collapses_whitespace(self):
        self.assertEqual(build.cell("a|b"), "a\\|b")
        self.assertEqual(build.cell("a   b\n c"), "a b c")
        self.assertEqual(build.cell("x" * 200, 150), "x" * 149 + "…")

    def test_short_stars_formats_thousands(self):
        self.assertEqual(build.short_stars(999), "999")
        self.assertEqual(build.short_stars(1000), "1.0k")
        self.assertEqual(build.short_stars(12345), "12.3k")


class MainTests(BuildTestCase):
    """The whole build."""

    def test_main_writes_every_derived_file(self):
        self.write_readme_fixture()
        build.main()
        for name in (
            "starred_repos.toml",
            "starred_repos.json",
            "assets/readme/hero.svg",
            "assets/readme/lists.svg",
            "README.md",
        ):
            self.assertTrue((self.root / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
