# Contributing

Thanks for looking at this repo. It publishes a curated list of GitHub repos for building software with AI agents: a README, a GitHub Pages site and the same data as CSV, TOML and JSON.

Two things are worth knowing before you start.

**The licence has not been chosen yet.** `LICENSE` is a placeholder, and the licence it will hold is the maintainer's decision, not yours. Please open an issue to ask before making a substantial contribution.

**The data is generated. Do not edit it by hand.** `starred_repos.csv` is the only source of truth, and everything else in the repo is built from it. Editing `starred_repos.toml`, `starred_repos.json`, the charts or the generated README tables will be rejected by the gate.

## Getting set up

```bash
git clone --config core.hooksPath=.githooks https://github.com/thinkjones/agentic-tools.git
```

The `--config` flag points git at the hooks in `.githooks/`, which are tracked by the repository. It is the only setup step. If you already have a clone, wire it with:

```bash
python3 scripts/setup_hooks.py
```

That script is idempotent. `python3 scripts/setup_hooks.py --check` reports the wiring without changing it.

You need Python 3.11 or later and the `gh` CLI, signed in. Nothing else: the scripts and the tests use the standard library alone.

## Making a change

Work on a branch. `main` is protected, and merging to `main` publishes the site.

```bash
git switch -c my-change
```

If your change touches the list itself, it goes through the CSV, not through the generated files:

```bash
python3 scripts/export_stars.py --decisions decisions.json   # re-file or rename lists
python3 scripts/build.py                                     # CSV -> everything else
```

`export_stars.py` reads the maintainer's GitHub stars, so it is the maintainer's tool. To propose a different repo for the list, open an issue rather than editing the CSV.

Rebuild after any change to the CSV, then check the work:

```bash
python3 scripts/build.py          # regenerate the TOML, JSON, charts and README blocks
python3 scripts/run_tests.py      # run the unit tests
python3 scripts/check_public.py   # confirm every listed repo is public
```

Then commit, push and open a pull request:

```bash
git add -A
git commit -m "Describe the change"
git push -u origin my-change
```

## The gate

`.githooks/gate.sh` runs before a gated commit and before a push. It:

1. Rebuilds the TOML, JSON, charts and README blocks from a scratch copy of the tree it is checking, and refuses when the committed files disagree with the generator.
2. Runs the unit tests.
3. Runs `scripts/check_public.py`, which fails when any listed repo is not public on GitHub.

Every check fails closed. If the `gh` CLI is missing or signed out, or the API call fails, the check exits non-zero and the gate refuses the commit. A gate that passes because it could not run is worse than no gate, because it looks like evidence. The same checks run in CI on every pull request and on every push to `main`, so a clone with no hooks wired is still guarded before anything merges.

The pre-push hook also refuses a push straight to `main`, because every change lands through a pull request.

If a gate refuses you and you are certain it is wrong, `--no-verify` skips the hook. Use it deliberately: it is the one place where a mistake reaches `main` unchecked.

## What CI checks

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs the unit tests, the build, the generated-file drift check and the visibility check on every non-draft pull request and on every push to `main`. The status check it reports is `Validate CSV + check public`.

A separate workflow, [`.github/workflows/refresh-stats.yml`](./.github/workflows/refresh-stats.yml), refreshes the stars, forks, activity and releases every morning and opens a pull request with the result. It never changes which list a repo is in.

## House rules

- Never publish a private or internal repository. That is what `scripts/check_public.py` is for.
- Do not edit generated files. Change the CSV, or change `scripts/build.py`, then rebuild.
- Keep the scripts standard-library only and the site dependency-free.
- Do not hard-wrap prose in markdown files. Write each paragraph and list item on one line.

## Layout

| Path | What it is |
| --- | --- |
| `starred_repos.csv` | The source of truth. |
| `scripts/export_stars.py` | GitHub stars to the CSV. |
| `scripts/build.py` | CSV to everything else. |
| `scripts/check_public.py` | The visibility check. |
| `scripts/gated_paths.py` | The single source of truth for the gate's trigger set. |
| `scripts/run_tests.py` | The test runner. |
| `scripts/setup_hooks.py` | Wires the hooks for a clone. |
| `tests/` | The unit tests. |
| `.githooks/` | The gate and the hooks that run it. |
| `index.html` | The site. Hand-written, no build step. |
