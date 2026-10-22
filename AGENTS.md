# Agent instructions

This repo publishes a curated list of GitHub repos for building software with AI agents: a README, a GitHub Pages site (`index.html`, served from `main`) and the same data as CSV, TOML and JSON. Live site: https://thinkjones.github.io/agentic-tools/

## How the repo fits together

- `starred_repos.csv` is the only source of truth. It is written by `scripts/export_stars.py` from the maintainer's GitHub stars.
- `scripts/build.py` generates everything else from the CSV: `starred_repos.toml`, `starred_repos.json`, the charts in `assets/readme/`, and the blocks in `README.md` between `<!-- name:start -->` and `<!-- name:end -->` markers.
- `index.html` is a single hand-written file with no build step. It loads `starred_repos.json` in the browser.
- `scripts/organize_stars.py` uploads the lists to the maintainer's GitHub Lists. `scripts/sync_repo_meta.py` sets the repo description and topics from `.github/repo.toml`.
- `.github/workflows/refresh-stats.yml` runs `export_stars.py --refresh` and the build every day and opens a `refresh-stats` pull request. It only updates stats and drops repos that are no longer public; it never adds or re-files repos.
- `tests/` holds the unit tests for the scripts, and `scripts/run_tests.py` runs them. It fails when it collects no tests, because a suite that runs nothing and reports success is worse than no suite.
- `.gh-stars-organizer/` is git-ignored scratch (decisions, cache, list backups).

## Commands

```bash
python3 scripts/export_stars.py        # GitHub stars -> starred_repos.csv
python3 scripts/build.py               # CSV -> TOML, JSON, charts, README blocks
python3 scripts/check_public.py        # fail if any listed repo is not public
python3 scripts/run_tests.py           # run the unit tests
python3 scripts/setup_hooks.py         # wire this clone's git hooks
python3 scripts/organize_stars.py      # dry run of the GitHub Lists upload
python3 scripts/sync_repo_meta.py      # dry run of the repo description and topics
python3 -m http.server                 # preview the site at http://localhost:8000
```

The scripts need Python 3.11 or later and the `gh` CLI, and use only the standard library. The tests use the standard library alone, so `python3 scripts/run_tests.py` needs nothing installed.

To add, remove or re-file repos, follow the `github-star-organizer` skill in `.claude/skills/github-star-organizer/SKILL.md`.

### The gate

The repository has a gate that checks the data before it can be committed or pushed. The gate itself lives in `.githooks/gate.sh`, and two hooks use it:

- `.githooks/pre-commit` runs the gate against the staged tree, but only when a gated path is staged. A commit that stages none of them is not intercepted.
- `.githooks/pre-push` refuses a direct push to `main`, and runs the gate against the tree being pushed, so a push that was made with the commit gate bypassed is still caught.

The gate runs `scripts/build.py` against a scratch copy of the tree under test, so the working tree is never written to, and refuses when the generated files in that tree disagree with the generator. It then runs the unit tests and `scripts/check_public.py`, both against the same scratch copy, so every check sees exactly the tree that is about to be committed or pushed. Everything the gate reads — the trigger set, the list of generated files, the scripts themselves — comes from that tree, never from the working tree.

The gate refuses a commit whose working-tree `starred_repos.csv` differs from the staged one. The gate checks the CSV that is staged, and the rebuild it suggests on failure runs against the working tree, so the two have to be the same file: if they differ, the remedy rebuilds from a different CSV and the gate refuses again. Stage the whole CSV or stash the rest.

Every check fails closed. If the `gh` CLI is missing or signed out, or the API call fails, `scripts/check_public.py` exits non-zero and the gate refuses. A gate that passes because it could not run is worse than no gate, because it looks like evidence. The scripts' output reaches the terminal unwrapped, so you read the same messages you would see on a pull request.

The one exception is a tree that predates the gate's own configuration: without `scripts/gated_paths.py` there is no trigger set to check against, so the gate says so and lets the commit through. A commit that *removes* that configuration, or the test runner, is refused instead, because it would switch the gate or the tests off. CI catches either case, since the test suite imports the configuration.

The gate fires when the staged paths include any of:

<!-- gated-paths:start -->
- `starred_repos.csv`
- `starred_repos.toml`
- `starred_repos.json`
- `assets/readme/hero.svg`
- `assets/readme/lists.svg`
- `scripts/build.py`
- `scripts/check_public.py`
- `scripts/gated_paths.py`
- `scripts/run_tests.py`
- `tests/`
- `.githooks/`
<!-- gated-paths:end -->

That list has exactly one home, `scripts/gated_paths.py`: the hooks read it from there, and `tests/test_gated_paths.py` fails when AGENTS.md stops documenting the same set. Change it there and nowhere else. `tests/` and `.githooks/` are directories, so any change under them fires the gate.

That list is the trigger set. `README.md` is compared for drift whenever the gate fires for one of those paths, but it is not itself a trigger, so a commit that stages only `README.md` invokes neither script.

The cost is about 0.1s for `build.py`, about 5s for the unit tests and about 15s for `check_public.py` on the current 344-repo CSV, and it is paid only by commits that touch the gated files. A documentation-only commit invokes neither script.

`.github/workflows/ci.yml` is the backstop: pull requests and pushes to `main` are gated whether or not you have enabled the local hook.

`build.py` imports `tomllib`, so it needs Python 3.11 or later — the same interpreter requirement as the commands above, which the hook inherits. On an older interpreter the hook fails with a `ModuleNotFoundError` from `build.py` rather than failing later on the visibility check.

### Enabling the gate

The gate is tracked in `.githooks/`, so each clone needs one setting to point git at it. For a new clone the setting is made as the clone is created, with no second command:

```bash
git clone --config core.hooksPath=.githooks https://github.com/thinkjones/agentic-tools.git
```

For a clone that already exists:

```bash
python3 scripts/setup_hooks.py
```

The script is idempotent and prints what it did. `python3 scripts/setup_hooks.py --check` reports the wiring without changing it. A clone with no wiring is not unguarded: CI gates every pull request and every push to `main` regardless.

## Rules

- Never publish a private or internal repo. Do not add rows to the CSV by hand, and run `scripts/check_public.py` before opening a pull request that changes the data.
- Do not edit generated files (`starred_repos.toml`, `starred_repos.json`, `assets/readme/*.svg`, the marked README blocks). Change the CSV through `export_stars.py --decisions`, or change `build.py`, then rebuild.
- `main` is protected. Work on a branch and open a pull request; merging to `main` publishes the site.
- Anything that changes the maintainer's GitHub account (starring repos, `organize_stars.py --apply`, `sync_repo_meta.py --apply`) needs their approval first. The dry runs are always safe.
- Keep the scripts standard-library only and the site dependency-free.
- Do not hard-wrap prose in markdown files. Write each paragraph and list item on one line.
- `LICENSE` is a placeholder: the licence for this repository has not been chosen yet. Do not copy the `license = "MIT"` line out of the TOML sample in `README.md` — that field describes a listed third-party repo, not this repo.

## Design

The site and the README charts use the Four Signals 2.1 design system: light mode, Source Serif 4 for headlines, Inter for body text, JetBrains Mono for labels, brand orange `#e85d26`, corner radius of 4px at most, and no divider lines between sections. The colour and font constants at the top of `scripts/build.py` and the CSS variables in `index.html` must stay in step, as must `LOG_MAX` in both files.
