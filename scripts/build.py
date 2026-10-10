#!/usr/bin/env python3
"""Rebuild every derived file from starred_repos.csv.

Writes starred_repos.toml, starred_repos.json, the two README charts under
assets/readme/, and the generated blocks inside README.md. Standard library
only; needs Python 3.11+ for the TOML round-trip check.

    python3 scripts/build.py
"""

import csv
import json
import math
import re
import tomllib
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "starred_repos.csv"
SITE_URL = "https://thinkjones.github.io/ai-sdlc-repo-list/"

# CSV header -> key used in the TOML and JSON files.
FIELDS = {
    "Proposed List": "list",
    "Repo": "repo",
    "URL": "url",
    "Stars": "stars",
    "Forks": "forks",
    "Activity": "activity",
    "Last Push": "last_push",
    "Last Release": "last_release",
    "Release Date": "release_date",
    "License": "license",
    "Language": "language",
    "Homepage": "homepage",
    "Topics": "topics",
    "Description": "description",
    "Starred On": "starred_on",
}
INT_FIELDS = {"stars", "forks"}
DATE_FIELDS = {"last_push", "release_date", "starred_on"}

# Activity levels, busiest first, with the chart colour and README marker.
ACTIVITY = [
    ("Very active", "#9CC4FF", "🔵"),
    ("Active", "#FFF1B8", "🟡"),
    ("Slowing", "#FFB45E", "🟠"),
    ("Dormant", "#F0705A", "🔴"),
    ("Archived", "#7C84A6", "⚫"),
]
COLOUR = {name: colour for name, colour, _ in ACTIVITY}
MARK = {name: mark for name, _, mark in ACTIVITY}

INK, RAISED, RULE, TEXT, MUTED = "#131A3A", "#1B2450", "#2C3668", "#E9ECF8", "#A3ACD0"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
SERIF = "Georgia, 'Times New Roman', serif"


def load():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    repos = []
    for row in rows:
        repo = {}
        for header, key in FIELDS.items():
            value = row[header].strip()
            if not value:
                continue  # TOML has no null, so empty cells are left out
            if key in INT_FIELDS:
                value = int(value)
            elif key == "topics":
                value = [t.strip() for t in value.split(",") if t.strip()]
            repo[key] = value
        repos.append(repo)
    return repos


def lists_of(repos):
    """Lists in CSV order, each with its repos sorted by stars."""
    grouped = {}
    for repo in repos:
        grouped.setdefault(repo["list"], []).append(repo)
    return {name: sorted(items, key=lambda r: -r["stars"]) for name, items in grouped.items()}


def snapshot_date(repos):
    return max(r["last_push"] for r in repos)


# ---------------------------------------------------------------- data files


def toml_string(value):
    # JSON string escapes are a subset of TOML basic-string escapes.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007F")


def toml_value(key, value):
    if key in INT_FIELDS:
        return str(value)
    if key in DATE_FIELDS:
        return value  # bare YYYY-MM-DD is a TOML local date
    if key == "topics":
        return "[" + ", ".join(toml_string(t) for t in value) + "]"
    return toml_string(value)


def write_toml(repos):
    out = [
        "# Generated from starred_repos.csv by scripts/build.py. Do not edit by hand.",
        "# One [[repos]] table per repository. Keys with no value in the CSV are omitted.",
        "",
        "[meta]",
        f"snapshot = {snapshot_date(repos)}",
        f"count = {len(repos)}",
        f"source = {toml_string(SITE_URL)}",
    ]
    for repo in repos:
        out += ["", "[[repos]]"]
        out += [f"{key} = {toml_value(key, repo[key])}" for key in FIELDS.values() if key in repo]
    path = ROOT / "starred_repos.toml"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # Round-trip: the TOML must parse back to exactly what the CSV held.
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))["repos"]
    for item in parsed:
        for key in DATE_FIELDS & item.keys():
            item[key] = item[key].isoformat()
    assert parsed == repos, "starred_repos.toml does not round-trip to the CSV"


def write_json(repos):
    doc = {
        "meta": {"snapshot": snapshot_date(repos), "count": len(repos), "source": SITE_URL},
        "repos": repos,
    }
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    (ROOT / "starred_repos.json").write_text(text + "\n", encoding="utf-8")


# -------------------------------------------------------------------- charts

LOG_MAX = 5.7  # 10^5.7 is about 500k stars, above the largest repo


def star_x(stars, left, right):
    return left + (right - left) * min(math.log10(stars + 1), LOG_MAX) / LOG_MAX


def swarm(xs, radius, max_offset):
    """Stack dots sharing an x position away from the centre line. Returns y offsets."""
    placed, offsets = [], [0.0] * len(xs)
    gap = radius * 2 + 0.6
    for i in sorted(range(len(xs)), key=lambda i: xs[i]):
        near = [(px, py) for px, py in placed if abs(px - xs[i]) < gap]
        candidates = [0.0]
        for px, py in near:
            dy = math.sqrt(max(gap * gap - (px - xs[i]) ** 2, 0))
            candidates += [py + dy, py - dy]
        free = [
            y
            for y in candidates
            if all((px - xs[i]) ** 2 + (py - y) ** 2 >= gap * gap - 1e-6 for px, py in near)
        ]
        y = min(free, key=abs)
        offsets[i] = max(-max_offset, min(max_offset, y))
        placed.append((xs[i], offsets[i]))
    return offsets


def dots(repos, left, right, centre, radius, max_offset):
    xs = [star_x(r["stars"], left, right) for r in repos]
    ys = swarm(xs, radius, max_offset)
    return "\n".join(
        f'<circle cx="{x:.1f}" cy="{centre + y:.1f}" r="{radius}" fill="{COLOUR[r["activity"]]}"'
        f' fill-opacity="0.9"/>'
        for r, x, y in zip(repos, xs, ys)
    )


def axis(left, right, top, bottom, label_y):
    parts = []
    for power, label in [(2, "100"), (3, "1k"), (4, "10k"), (5, "100k")]:
        x = left + (right - left) * power / LOG_MAX
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{RULE}" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{label_y}" text-anchor="middle" font-size="18" fill="{MUTED}">{label}</text>'
        )
    return "\n".join(parts)


def svg(width, height, title, desc, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"'
        f' font-family="{SANS}">\n'
        f'<title id="title">{escape(title)}</title>\n<desc id="desc">{escape(desc)}</desc>\n'
        f'<rect width="{width}" height="{height}" rx="26" fill="{INK}"/>\n{body}\n</svg>\n'
    )


def write_hero(repos, groups):
    counts = {name: sum(r["activity"] == name for r in repos) for name, _, _ in ACTIVITY}
    ai = sum(len(items) for name, items in groups.items() if name.startswith("AI"))
    legend = "\n".join(
        f'<circle cx="0" cy="{i * 34 - 7}" r="8" fill="{colour}"/>'
        f'<text x="22" y="{i * 34}" font-size="21" fill="{TEXT}">{name}</text>'
        f'<text x="250" y="{i * 34}" font-size="21" fill="{MUTED}" text-anchor="end">{counts[name]}</text>'
        for i, (name, colour, _) in enumerate(ACTIVITY)
    )
    body = f"""<g id="title-block" transform="translate(64 0)">
<text y="76" font-size="21" fill="{MUTED}">thinkjones / starred repositories</text>
<text y="150" font-family="{SERIF}" font-size="68" fill="{TEXT}">AI SDLC repo list</text>
<text y="200" font-size="25" fill="{TEXT}">{len(repos)} public repos sorted into {len(groups)} lists.</text>
<text y="234" font-size="25" fill="{MUTED}">{ai} of them are tools for building software with AI agents.</text>
</g>
<g id="legend" transform="translate(886 72)">
{legend}
</g>
<g id="swarm">
<text x="64" y="296" font-size="18" fill="{MUTED}">Each dot is one repo, placed by GitHub stars</text>
{axis(64, 1136, 312, 452, 482)}
{dots(repos, 64, 1136, 382, 5, 70)}
</g>"""
    desc = (
        f"{len(repos)} starred repositories plotted by star count and coloured by activity: "
        + ", ".join(f"{counts[name]} {name.lower()}" for name, _, _ in ACTIVITY)
        + "."
    )
    (ROOT / "assets/readme/hero.svg").write_text(
        svg(1200, 506, "AI SDLC repo list", desc, body), encoding="utf-8"
    )


def write_lists_chart(groups):
    row_h, top = 34, 84
    left, right = 600, 1144
    height = top + row_h * len(groups) + 26
    rows = []
    for i, (name, items) in enumerate(groups.items()):
        y = top + i * row_h
        rows.append(
            f'<text x="48" y="{y + 7}" font-size="20" fill="{TEXT}">{escape(name)}</text>'
            f'<text x="556" y="{y + 7}" font-size="20" fill="{MUTED}" text-anchor="end">{len(items)}</text>'
            f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="{RULE}" stroke-width="1"/>\n'
            + dots(items, left, right, y, 5, 9)
        )
    body = (
        f'<text x="48" y="46" font-size="20" fill="{MUTED}">List</text>'
        f'<text x="556" y="46" font-size="20" fill="{MUTED}" text-anchor="end">Repos</text>\n'
        + axis(left, right, 58, height - 26, 46)
        + "\n"
        + "\n".join(rows)
    )
    desc = "Each of the lists as a row of dots, one per repo, placed by star count and coloured by activity."
    (ROOT / "assets/readme/lists.svg").write_text(
        svg(1200, height, "Repos per list by star count", desc, body), encoding="utf-8"
    )


# -------------------------------------------------------------------- README


def short_stars(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def cell(text, limit=None):
    text = " ".join(text.split())
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return escape(text, quote=False).replace("|", "\\|")


def readme_blocks(repos, groups):
    ai = sum(len(items) for name, items in groups.items() if name.startswith("AI"))
    summary = (
        f"{len(repos)} public GitHub repositories I have starred, sorted into {len(groups)} lists. "
        f"{ai} of them are tools for building software with AI agents: frameworks, coding harnesses, "
        f"orchestration, memory, skills and evals. The rest are the terminal tools, infrastructure and "
        f"references around them. Snapshot taken {snapshot_date(repos)}."
    )

    contents = ["| List | Repos | Most starred |", "| --- | ---: | --- |"]
    sections = []
    for i, (name, items) in enumerate(groups.items(), 1):
        anchor = f"list-{i:02d}"
        top = items[0]
        contents.append(f"| [{cell(name)}](#{anchor}) | {len(items)} | [{top['repo']}]({top['url']}) |")
        section = [
            f'<a id="{anchor}"></a>',
            "",
            f"### {name}",
            "",
            "| Repo | Stars | Language | Activity | Last push |",
            "| --- | ---: | --- | --- | --- |",
        ]
        for r in items:
            about = cell(r.get("description", ""), 150)
            name_cell = f"[**{r['repo']}**]({r['url']})" + (f"<br>{about}" if about else "")
            section.append(
                f"| {name_cell} | {short_stars(r['stars'])} | {r.get('language', '')} "
                f"| {MARK[r['activity']]} {r['activity']} | {r['last_push']} |"
            )
        sections.append("\n".join(section))

    return {"summary": summary, "contents": "\n".join(contents), "lists": "\n\n".join(sections)}


def write_readme(repos, groups):
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    for name, block in readme_blocks(repos, groups).items():
        pattern = re.compile(rf"(<!-- {name}:start -->\n).*?(<!-- {name}:end -->)", re.S)
        text, n = pattern.subn(lambda m: m.group(1) + block + "\n" + m.group(2), text)
        assert n == 1, f"README.md is missing the {name} markers"
    path.write_text(text, encoding="utf-8")


def main():
    repos = load()
    groups = lists_of(repos)
    (ROOT / "assets/readme").mkdir(parents=True, exist_ok=True)
    write_toml(repos)
    write_json(repos)
    write_hero(repos, groups)
    write_lists_chart(groups)
    write_readme(repos, groups)
    print(f"Built {len(repos)} repos in {len(groups)} lists (snapshot {snapshot_date(repos)}).")


if __name__ == "__main__":
    main()
