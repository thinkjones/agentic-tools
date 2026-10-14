# Agent instructions

This repo publishes a curated list of GitHub repos for building software with AI agents: a README, a GitHub Pages site (`index.html`, served from `main`) and the same data as CSV, TOML and JSON. Live site: https://thinkjones.github.io/agentic-tools/

## How the repo fits together

- `starred_repos.csv` is the only source of truth. It is written by `scripts/export_stars.py` from the maintainer's GitHub stars.
- `scripts/build.py` generates everything else from the CSV: `starred_repos.toml`, `starred_repos.json`, the charts in `assets/readme/`, and the blocks in `README.md` between `<!-- name:start -->` and `<!-- name:end -->` markers.
- `index.html` is a single hand-written file with no build step. It loads `starred_repos.json` in the browser.
- `scripts/organize_stars.py` uploads the lists to the maintainer's GitHub Lists. `scripts/sync_repo_meta.py` sets the repo description and topics from `.github/repo.toml`.
- `.github/workflows/refresh-stats.yml` runs `export_stars.py --refresh` and the build every Monday and opens a `refresh-stats` pull request. It only updates stats; it never adds, removes or re-files repos.
- `.gh-stars-organizer/` is git-ignored scratch (decisions, cache, list backups).

## Commands

```bash
python3 scripts/export_stars.py        # GitHub stars -> starred_repos.csv
python3 scripts/build.py               # CSV -> TOML, JSON, charts, README blocks
python3 scripts/check_public.py        # fail if any listed repo is not public
python3 scripts/organize_stars.py      # dry run of the GitHub Lists upload
python3 scripts/sync_repo_meta.py      # dry run of the repo description and topics
python3 -m http.server                 # preview the site at http://localhost:8000
```

The scripts need Python 3.11 or later and the `gh` CLI, and use only the standard library. There is no test suite: the build asserts that the TOML round-trips to the CSV, and `check_public.py` is the gate before publishing.

To add, remove or re-file repos, follow the `github-star-organizer` skill in `.claude/skills/github-star-organizer/SKILL.md`.

## Rules

- Never publish a private or internal repo. Do not add rows to the CSV by hand, and run `scripts/check_public.py` before opening a pull request that changes the data.
- Do not edit generated files (`starred_repos.toml`, `starred_repos.json`, `assets/readme/*.svg`, the marked README blocks). Change the CSV through `export_stars.py --decisions`, or change `build.py`, then rebuild.
- `main` is protected. Work on a branch and open a pull request; merging to `main` publishes the site.
- Anything that changes the maintainer's GitHub account (starring repos, `organize_stars.py --apply`, `sync_repo_meta.py --apply`) needs their approval first. The dry runs are always safe.
- Keep the scripts standard-library only and the site dependency-free.
- Do not hard-wrap prose in markdown files. Write each paragraph and list item on one line.

## Design

The site and the README charts use the Four Signals 2.1 design system: light mode, Source Serif 4 for headlines, Inter for body text, JetBrains Mono for labels, brand orange `#e85d26`, corner radius of 4px at most, and no divider lines between sections. The colour and font constants at the top of `scripts/build.py` and the CSS variables in `index.html` must stay in step, as must `LOG_MAX` in both files.
