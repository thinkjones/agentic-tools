#!/usr/bin/env python3
"""Refresh starred_repos.csv from the signed-in GitHub account's stars.

Fetches every public starred repo with current stars, forks, release, license
and topics, and writes the CSV that scripts/build.py turns into the TOML, JSON,
README and site. Private and internal repos are never written.

Each repo's list is carried over from the existing CSV. A repo that is new to
the CSV takes the GitHub List it is in today, or "Unsorted" when it is in none
or in several. Change lists with a decisions file:

    {"rename": {"Old list name": "New list name"},
     "assign": {"owner/repo": "List name"}}

    python3 scripts/export_stars.py                              # refresh the CSV
    python3 scripts/export_stars.py --decisions decisions.json   # refresh and re-file
    python3 scripts/export_stars.py --output /tmp/preview.csv    # leave the CSV alone

Needs Python 3.11+ and the gh CLI, signed in.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "starred_repos.csv"
UNSORTED = "Unsorted"

COLUMNS = [
    "Proposed List", "Repo", "URL", "Stars", "Forks", "Activity", "Last Push", "Last Release",
    "Release Date", "License", "Language", "Homepage", "Topics", "Description", "Starred On",
]  # fmt: skip

STARS_QUERY = """
query($after: String) {
  viewer {
    starredRepositories(first: 100, after: $after, orderBy: {field: STARRED_AT, direction: DESC}) {
      edges {
        starredAt
        node {
          nameWithOwner url visibility stargazerCount forkCount isArchived pushedAt
          description homepageUrl
          latestRelease { tagName publishedAt }
          licenseInfo { spdxId }
          primaryLanguage { name }
          repositoryTopics(first: 20) { nodes { topic { name } } }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
LISTS_QUERY = """
query($after: String) {
  viewer {
    lists(first: 50, after: $after) {
      nodes {
        id name
        items(first: 100) {
          nodes { ... on Repository { nameWithOwner } }
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
        nodes { ... on Repository { nameWithOwner } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def fail(message):
    sys.exit(f"error: {message}")


def gql(query, **variables):
    for attempt in range(3):
        proc = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"],
            input=json.dumps({"query": query, "variables": variables}),
            capture_output=True,
            text=True,
        )
        if not re.search(r"HTTP 5\d\d", proc.stderr):
            break
        time.sleep(2 * (attempt + 1))  # GitHub's gateway times out now and then
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail(f"gh api graphql failed: {proc.stderr.strip() or proc.stdout.strip()}")
    if payload.get("errors"):
        fail("GitHub API: " + "; ".join(e.get("message", str(e)) for e in payload["errors"]))
    return payload["data"]


def fetch_stars():
    edges, after = [], None
    while True:
        page = gql(STARS_QUERY, after=after)["viewer"]["starredRepositories"]
        edges += page["edges"]
        if not page["pageInfo"]["hasNextPage"]:
            return edges
        after = page["pageInfo"]["endCursor"]


def fetch_memberships():
    """Map lower-cased owner/name to the names of the GitHub Lists it is in."""
    memberships, after = {}, None
    while True:
        page = gql(LISTS_QUERY, after=after)["viewer"]["lists"]
        for node in page["nodes"]:
            items = node["items"]
            repos = [n for n in items["nodes"] if n]
            while items["pageInfo"]["hasNextPage"]:
                items = gql(ITEMS_QUERY, id=node["id"], after=items["pageInfo"]["endCursor"])["node"]["items"]
                repos += [n for n in items["nodes"] if n]
            for repo in repos:
                memberships.setdefault(repo["nameWithOwner"].lower(), []).append(node["name"])
        if not page["pageInfo"]["hasNextPage"]:
            return memberships
        after = page["pageInfo"]["endCursor"]


def activity(node, today):
    """Label a repo by how recently it was pushed to."""
    if node["isArchived"]:
        return "Archived"
    days = (today - datetime.fromisoformat(node["pushedAt"]).date()).days
    if days <= 31:
        return "Very active"
    if days <= 92:
        return "Active"
    if days <= 365:
        return "Slowing"
    return "Dormant"


def day(timestamp):
    return timestamp[:10] if timestamp else ""


def to_row(edge, today):
    node = edge["node"]
    release = node["latestRelease"] or {}
    return {
        "Repo": node["nameWithOwner"],
        "URL": node["url"],
        "Stars": node["stargazerCount"],
        "Forks": node["forkCount"],
        "Activity": activity(node, today),
        "Last Push": day(node["pushedAt"]),
        "Last Release": release.get("tagName") or "",
        "Release Date": day(release.get("publishedAt")),
        "License": (node["licenseInfo"] or {}).get("spdxId") or "",
        "Language": (node["primaryLanguage"] or {}).get("name") or "",
        "Homepage": node["homepageUrl"] or "",
        "Topics": ", ".join(sorted(t["topic"]["name"] for t in node["repositoryTopics"]["nodes"])),
        "Description": " ".join((node["description"] or "").split()),
        "Starred On": day(edge["starredAt"]),
    }


def previous_lists(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["Repo"].lower(): row["Proposed List"] for row in csv.DictReader(f)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--decisions", metavar="FILE", help="JSON file with list renames and repo assignments")
    parser.add_argument("--output", metavar="FILE", type=Path, default=CSV_PATH, help="write here instead of starred_repos.csv")
    args = parser.parse_args()

    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8")) if args.decisions else {}
    rename = decisions.get("rename", {})
    assign = {name.lower(): value for name, value in decisions.get("assign", {}).items()}
    unknown_keys = set(decisions) - {"rename", "assign"}
    if unknown_keys:
        fail(f"unknown keys in decisions file: {', '.join(sorted(unknown_keys))}")

    previous = previous_lists(CSV_PATH)
    memberships = fetch_memberships()
    edges = fetch_stars()
    today = datetime.now(timezone.utc).date()

    rows, hidden, added = [], 0, []
    for edge in edges:
        if edge["node"]["visibility"] != "PUBLIC":
            hidden += 1
            continue
        row = to_row(edge, today)
        key = row["Repo"].lower()
        if key in previous:
            current = previous[key]
        else:
            lists = memberships.get(key, [])
            current = lists[0] if len(lists) == 1 else UNSORTED
            added.append(row["Repo"])
        current = rename.get(current, current)
        row["Proposed List"] = assign.pop(key, current) or UNSORTED
        rows.append(row)
    if assign:
        fail("decisions file assigns repos that are not public stars: " + ", ".join(sorted(assign)))

    starred = {row["Repo"].lower() for row in rows}
    dropped = sorted(name for name in previous if name not in starred)
    rows.sort(key=lambda r: (r["Proposed List"] == UNSORTED, r["Proposed List"].lower(), -r["Stars"]))

    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for row in rows:
        counts[row["Proposed List"]] = counts.get(row["Proposed List"], 0) + 1
    print(f"Wrote {len(rows)} public repos in {len(counts)} lists to {args.output}")
    for name, count in counts.items():
        print(f"  {count:4}  {name}")
    print(f"Left out {hidden} private or internal starred repos.")
    if added:
        print(f"\n{len(added)} repos are new to the CSV:")
        for row in rows:
            if row["Repo"] in added:
                print(f"  {row['Repo']}  [{row['Proposed List']}]  {row['Description'][:90]}")
    if dropped:
        print(f"\n{len(dropped)} repos were in the CSV and are no longer public stars (removed):")
        print("  " + "\n  ".join(dropped))
    if counts.get(UNSORTED):
        print(f"\n{counts[UNSORTED]} repos are {UNSORTED}. Assign them with --decisions before publishing.")
    else:
        print(f"\nNo {UNSORTED} repos.")


if __name__ == "__main__":
    main()
