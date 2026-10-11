---
name: github-star-organizer
description: Use when the user wants to refresh, re-categorise, tidy or re-upload their GitHub stars or star lists in this repo - new stars to file, list headings to rename/merge/split, starred_repos.csv or .toml out of date, or GitHub Lists that should match the published list.
---

# GitHub star organizer

Round trip: GitHub stars → `starred_repos.csv` → TOML, JSON, README and site → GitHub Lists. The CSV is the only file edited; everything else is generated from it. Run every command from the repo root.

## Steps

1. **Export.** `python3 scripts/export_stars.py` rewrites `starred_repos.csv` from the signed-in `gh` account. It keeps each repo's existing list, drops unstarred repos, leaves out private repos, and prints new repos and anything `Unsorted`.
2. **Suggest headings.** Read the CSV (the `Proposed List`, `Topics` and `Description` columns) and propose the list headings: where each `Unsorted` or new repo goes, plus whatever tidy-up the user asked for (renames, merges, splits, moving repos between lists). Show the user a table of heading, repo count and what changed, with the repos that move. Wait for their answer before step 3.
3. **Record decisions.** Write the agreed changes to a new `.gh-stars-organizer/decisions.json` (create the folder if needed; it is git-ignored scratch, and either key may be omitted), then re-run the export with it:

   ```json
   {"rename": {"Old heading": "New heading"},
    "assign": {"owner/repo": "Heading"}}
   ```

   `python3 scripts/export_stars.py --decisions .gh-stars-organizer/decisions.json`

   Renaming two headings to the same name merges them. A split is a set of `assign` entries. A heading disappears once every repo is assigned away from it. Repeat until the export prints `No Unsorted repos.`
4. **Build and check.** `python3 scripts/build.py`, then `python3 scripts/check_public.py`. The build fails if the TOML does not round-trip to the CSV. `python3 scripts/sync_repo_meta.py` previews the GitHub description (it carries the repo and list counts) and topics from `.github/repo.toml`; run it with `--apply` when the user pushes.
5. **Preview the upload.** `python3 scripts/organize_stars.py` is a dry run: it changes nothing on GitHub and prints the lists it would create or reuse, and the current lists that are not in the plan. It needs `uv` or `pipx` to fetch the gh-stars-organizer tool. Show the user that plan. Two things in it are expected:
   - Long headings appear under their shortened GitHub names from `SHORT_NAMES`.
   - Starred repos "not in starred_repos.toml" are the private ones the export left out. Leave them alone, and keep their names out of anything public.

   Steps 1–5 never change GitHub.
6. **Upload.** Only after the user approves the plan: `python3 scripts/organize_stars.py --apply`, adding `--replace-lists` and `--public` as they choose. It needs the `user` scope; if it says so, ask the user to run `! gh auth refresh -s user`.

## Heading rules

| Rule | Why |
| --- | --- |
| 32 lists at most | GitHub's per-account limit |
| Name of 32 characters or fewer | GitHub's limit; longer names need an entry in `SHORT_NAMES` in `scripts/organize_stars.py` |
| One list per repo | The upload replaces a repo's list membership |
| Keep existing headings unless the user agrees to change them | Renames change the public README, site anchors and GitHub Lists |
| A list under 3 repos is a merge candidate; one over 35 is a split candidate | Keeps lists scannable. Propose it; the user decides |
| A repo that fits no heading: ask the user where it goes | Do not force it into a poor fit or invent a catch-all on your own |
| No `Unsorted` left | The upload refuses to run with it |

## Before changing anything outside the repo

- `--apply` moves repos out of the GitHub Lists they are in now. A current list that is not in the plan is left behind empty, or deleted with `--replace-lists`. Tell the user which lists that affects and get a yes to the exact flags.
- `--apply` saves a backup under `.gh-stars-organizer/backups/` first; `--restore <file>` puts lists back.
- `main` is protected: commit to a branch and open a pull request, and only when the user asks. Merging publishes the site.
- Never add a private repo to the CSV by hand; `check_public.py` must pass before a push.

## Common mistakes

- Editing `starred_repos.toml`, `starred_repos.json` or the README tables directly. They are overwritten by the build; change the CSV through a decisions file.
- Editing the CSV by hand for list changes. A decisions file keeps the quoting and sort order right.
- Running `--apply` straight after the export. Build first: the upload reads `starred_repos.toml`.
- Treating a clean dry run as an upload. Nothing changes on GitHub without `--apply`.

`export_stars.py`, `organize_stars.py` and `sync_repo_meta.py` document their flags in `--help`. `build.py` and `check_public.py` take no flags and run immediately.
