#!/usr/bin/env python3
"""File your GitHub stars into GitHub Lists that match starred_repos.toml.

Drives gh-stars-organizer (https://github.com/vins13pattar/gh-stars-organizer):
it syncs your stars, this script tells it which list each repo belongs to
(from the `list` key in starred_repos.toml, so no LLM call is needed), and it
creates the lists and assigns the repos.

    python3 scripts/organize_stars.py                    # dry run: print the plan
    python3 scripts/organize_stars.py --apply            # make the changes
    python3 scripts/organize_stars.py --apply --replace-lists --public
    python3 scripts/organize_stars.py --restore .gh-stars-organizer/backups/<file>.json

Needs Python 3.11+, the gh CLI signed in, and uv or pipx to run the tool.
--apply also needs the `user` scope: gh auth refresh -s user

Things to know before --apply:
- A repo ends up in exactly one list. The tool replaces a repo's current list
  membership, so repos leave whatever lists they are in today.
- GitHub allows 32 lists per account. If the new lists do not fit next to your
  current ones, pass --replace-lists to delete the lists that are not in the
  plan. Deleting a list never unstars a repo.
- Your current lists are saved to .gh-stars-organizer/backups/ first.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "starred_repos.toml"
STATE = ROOT / ".gh-stars-organizer"
CONFIG_PATH = STATE / "config.yaml"
CACHE_PATH = STATE / "cache.db"

TOOL = "gh-stars-organizer"
TOOL_VERSION = "1.0.3"  # the seeding below depends on this version's cache schema
MODEL = "gpt-4.1-mini"  # the tool keys cached classifications by model name

MAX_LISTS = 32
MAX_NAME = 32  # GitHub's list-name limit
# Names in the data that are too long for a GitHub list.
SHORT_NAMES = {
    "AI · Applied (Business, Media, Research)": "AI · Applied",
    "AI · LLM Platforms, Gateways & Local AI": "AI · LLM Platforms & Local AI",
    "AI · Skills, Plugins & Registries": "AI · Skills & Plugins",
    "Archive · Legacy JS (Angular 1 / MEAN era)": "Archive · Legacy JS",
    "SaaS Building Blocks (UI, Forms, Grids)": "SaaS Building Blocks",
    "Workflow Automation & Durable Execution": "Workflow & Durable Execution",
}


def fail(message):
    sys.exit(f"error: {message}")


def gql(query, **variables):
    proc = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=json.dumps({"query": query, "variables": variables}),
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail(f"gh api graphql failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if payload.get("errors"):
        fail("GitHub API: " + "; ".join(e.get("message", str(e)) for e in payload["errors"]))
    return payload["data"]


def run_tool(command):
    if shutil.which("uvx"):
        runner = ["uvx", "--from", f"{TOOL}=={TOOL_VERSION}", TOOL]
    elif shutil.which("pipx"):
        runner = ["pipx", "run", "--spec", f"{TOOL}=={TOOL_VERSION}", TOOL]
    else:
        fail("install uv or pipx so the script can run gh-stars-organizer")
    proc = subprocess.run([*runner, command, "--config", str(CONFIG_PATH)])
    if proc.returncode != 0:
        fail(f"gh-stars-organizer {command} exited with status {proc.returncode}")


# ---------------------------------------------------------------- the plan


def load_plan():
    """Map lower-cased owner/name to its GitHub list name, plus name -> full title."""
    with DATA_PATH.open("rb") as f:
        repos = tomllib.load(f)["repos"]
    unsorted = [repo["repo"] for repo in repos if repo["list"] == "Unsorted"]
    if unsorted:
        fail(f"{len(unsorted)} repos are still Unsorted, for example {unsorted[0]}. Assign them first.")
    titles = {}
    for repo in repos:
        short = SHORT_NAMES.get(repo["list"], repo["list"])
        if len(short) > MAX_NAME:
            fail(f"list name {short!r} is over {MAX_NAME} characters; rename it or add it to SHORT_NAMES")
        titles[short] = repo["list"]
    if len(titles) > MAX_LISTS:
        fail(f"{len(titles)} lists is over GitHub's limit of {MAX_LISTS}; merge some")
    wanted = {repo["repo"].lower(): SHORT_NAMES.get(repo["list"], repo["list"]) for repo in repos}
    if len({name.lower() for name in titles}) != len(titles):
        fail("two lists share a name once shortened; fix SHORT_NAMES")
    return wanted, titles


def write_config(categories):
    STATE.mkdir(exist_ok=True)
    lines = [
        f"model: {json.dumps(MODEL)}",
        f"cache_db_path: {json.dumps(str(CACHE_PATH))}",
        f"faiss_index_path: {json.dumps(str(STATE / 'embeddings.index'))}",
        f"local_lists_path: {json.dumps(str(STATE / 'lists'))}",
        f"insights_report_path: {json.dumps(str(STATE / 'stars-insights.md'))}",
        "categories:",
        *(f"  - {json.dumps(name, ensure_ascii=False)}" for name in categories),
    ]
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed_cache(wanted, classify_new):
    """Give the tool our list for every synced repo. Returns (starred, uncatalogued) names."""
    db = sqlite3.connect(CACHE_PATH)
    starred = dict(db.execute("SELECT repo_id, full_name FROM repositories"))
    now = datetime.now(timezone.utc).isoformat()
    uncatalogued = []
    db.execute("DELETE FROM classifications WHERE model = ?", (MODEL,))
    for repo_id, name in starred.items():
        category = wanted.get(name.lower())
        if category:
            db.execute(
                "INSERT INTO classifications (repo_id, model, category, created_at) VALUES (?, ?, ?, ?)",
                (repo_id, MODEL, category, now),
            )
        else:
            uncatalogued.append(name)
            if not classify_new:
                # Not in the cache means the tool leaves the repo alone.
                db.execute("DELETE FROM repositories WHERE repo_id = ?", (repo_id,))
    db.commit()
    db.close()
    return set(starred.values()), sorted(uncatalogued, key=str.lower)


# ------------------------------------------------------------ GitHub lists

LISTS_QUERY = """
query($after: String) {
  viewer {
    lists(first: 50, after: $after) {
      nodes {
        id name description isPrivate
        items(first: 100) {
          nodes { ... on Repository { id nameWithOwner } }
          pageInfo { hasNextPage endCursor }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
ITEMS_QUERY = """
query($id: ID!, $after: String) {
  node(id: $id) {
    ... on UserList {
      items(first: 100, after: $after) {
        nodes { ... on Repository { id nameWithOwner } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def fetch_lists():
    lists, after = [], None
    while True:
        page = gql(LISTS_QUERY, after=after)["viewer"]["lists"]
        for node in page["nodes"]:
            items = node.pop("items")
            repos = [n for n in items["nodes"] if n]
            while items["pageInfo"]["hasNextPage"]:
                items = gql(ITEMS_QUERY, id=node["id"], after=items["pageInfo"]["endCursor"])["node"]["items"]
                repos += [n for n in items["nodes"] if n]
            node["repos"] = repos
            lists.append(node)
        if not page["pageInfo"]["hasNextPage"]:
            return lists
        after = page["pageInfo"]["endCursor"]


def has_user_scope():
    """False only when the token reports its scopes and `user` is not one of them."""
    proc = subprocess.run(["gh", "api", "-i", "user"], capture_output=True, text=True)
    match = re.search(r"^x-oauth-scopes:(.*)$", proc.stdout, re.I | re.M)
    if not match:
        return True  # fine-grained tokens do not list scopes; the final check catches failures
    return "user" in [s.strip() for s in match.group(1).split(",")]


def save_backup(lists):
    folder = STATE / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"lists-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(lists, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


UPDATE_LIST = """
mutation($id: ID!, $name: String!, $description: String, $private: Boolean) {
  updateUserList(input: {listId: $id, name: $name, description: $description, isPrivate: $private}) {
    list { id }
  }
}
"""


def restore(path):
    backup = json.loads(Path(path).read_text(encoding="utf-8"))
    if not has_user_scope():
        fail("the gh token needs the `user` scope. Run: gh auth refresh -s user")
    current = {item["name"].lower(): item["id"] for item in fetch_lists()}
    missing = [item for item in backup if item["name"].lower() not in current]
    if len(current) + len(missing) > MAX_LISTS:
        fail(
            f"restoring needs {len(missing)} more lists but GitHub allows {MAX_LISTS} "
            f"and you have {len(current)}. Delete some lists on GitHub first."
        )
    memberships = {}
    for item in backup:
        list_id = current.get(item["name"].lower())
        if not list_id:
            data = gql(
                "mutation($name: String!, $description: String, $private: Boolean) {"
                " createUserList(input: {name: $name, description: $description, isPrivate: $private})"
                " { list { id } } }",
                name=item["name"],
                description=item["description"],
                private=item["isPrivate"],
            )
            list_id = data["createUserList"]["list"]["id"]
            print(f"Created list {item['name']}")
        for repo in item["repos"]:
            memberships.setdefault(repo["id"], []).append(list_id)
    for repo_id, list_ids in memberships.items():
        gql(
            "mutation($item: ID!, $lists: [ID!]!) {"
            " updateUserListsForItem(input: {itemId: $item, listIds: $lists}) { clientMutationId } }",
            item=repo_id,
            lists=list_ids,
        )
    print(f"Restored {len(memberships)} repos across {len(backup)} lists from {path}.")
    print("Lists created since the backup were left in place.")


# -------------------------------------------------------------------- main


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="change the lists on GitHub (default is a dry run)")
    parser.add_argument("--replace-lists", action="store_true", help="delete current lists that are not in the plan")
    parser.add_argument("--public", action="store_true", help="make the planned lists public (the tool creates private lists)")
    parser.add_argument(
        "--classify-new",
        action="store_true",
        help="let the tool's LLM place starred repos that are missing from the data file (needs OPENAI_API_KEY)",
    )
    parser.add_argument("--restore", metavar="BACKUP", help="put lists back as recorded in a backup file, then exit")
    args = parser.parse_args()

    if args.restore:
        return restore(args.restore)
    if args.classify_new and not os.getenv("OPENAI_API_KEY"):
        fail("--classify-new needs OPENAI_API_KEY; without it the tool files unknown repos by keyword guess")

    wanted, titles = load_plan()
    # With an LLM in play the tool needs an "other" bucket, or it files misses under the first list.
    write_config([*titles, "other"] if args.classify_new else list(titles))
    run_tool("sync")
    starred, uncatalogued = seed_cache(wanted, args.classify_new)
    starred_lower = {name.lower() for name in starred}
    unstarred = sorted(name for name in wanted if name not in starred_lower)

    current = fetch_lists()
    by_name = {item["name"].lower(): item for item in current}
    to_create = [name for name in titles if name.lower() not in by_name]
    extra = [item for item in current if item["name"].lower() not in {n.lower() for n in titles}]
    total_after = len(current) + len(to_create) - (len(extra) if args.replace_lists else 0)

    counts = {}
    for name, list_name in wanted.items():
        if name in starred_lower:
            counts[list_name] = counts.get(list_name, 0) + 1

    print(f"\nPlan for {sum(counts.values())} starred repos in {len(titles)} lists:")
    for name in titles:
        state = "create" if name in to_create else "reuse"
        print(f"  {state:6} {name:{MAX_NAME}} {counts.get(name, 0):4} repos")
    if extra:
        verb = "Delete" if args.replace_lists else "Keep, but emptied of the repos above:"
        print(f"\n{verb} {len(extra)} current lists that are not in the plan:")
        for item in extra:
            print(f"  {item['name']:{MAX_NAME}} {len(item['repos']):4} repos now")
    if uncatalogued:
        fate = "placed by the tool's LLM" if args.classify_new else "left out of the new lists"
        print(f"\n{len(uncatalogued)} starred repos are not in {DATA_PATH.name} and are {fate}:")
        print("  " + "\n  ".join(uncatalogued))
    if unstarred:
        print(f"\n{len(unstarred)} repos in {DATA_PATH.name} are no longer starred (or were renamed) and are skipped:")
        print("  " + "\n  ".join(unstarred))

    if total_after > MAX_LISTS:
        print(
            f"\nThis does not fit: {total_after} lists would be needed and GitHub allows {MAX_LISTS}. "
            f"Pass --replace-lists to delete the {len(extra)} lists that are not in the plan."
        )
        if args.apply:
            sys.exit(1)
    if not args.apply:
        print("\nDry run. Nothing on GitHub was changed. Add --apply to make these changes.")
        return

    if not has_user_scope():
        fail("the gh token needs the `user` scope to edit lists. Run: gh auth refresh -s user")
    print(f"\nSaved your current lists to {save_backup(current)}")

    if args.replace_lists:
        for item in extra:
            gql("mutation($id: ID!) { deleteUserList(input: {listId: $id}) { clientMutationId } }", id=item["id"])
            print(f"Deleted list {item['name']}")

    run_tool("organize")

    # The tool exits 0 even when it falls back to local files, so check GitHub itself.
    after = {item["name"].lower(): item for item in fetch_lists()}
    placed = {
        repo["nameWithOwner"].lower(): item["name"]
        for item in after.values()
        for repo in item["repos"]
    }
    wrong = [name for name, list_name in wanted.items() if name in starred_lower and placed.get(name, "").lower() != list_name.lower()]
    if wrong:
        fail(f"{len(wrong)} repos are not in their planned list, for example {wrong[0]}. See the tool output above.")

    for name, title in titles.items():
        item = after[name.lower()]
        description = item["description"] or (title if title != name else None)
        private = False if args.public else item["isPrivate"]
        if description != item["description"] or private != item["isPrivate"]:
            gql(UPDATE_LIST, id=item["id"], name=item["name"], description=description, private=private)
    print(f"Done. {sum(counts.values())} repos are filed in {len(titles)} lists: https://github.com/stars")


if __name__ == "__main__":
    main()
