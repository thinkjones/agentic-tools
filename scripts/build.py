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
    ("Very active", "#e85d26", "🟠"),
    ("Active", "#19a0a6", "🔵"),
    ("Slowing", "#ffb800", "🟡"),
    ("Dormant", "#EB5570", "🔴"),
    ("Archived", "#94a3b8", "⚫"),
]
COLOUR = {name: colour for name, colour, _ in ACTIVITY}
MARK = {name: mark for name, _, mark in ACTIVITY}

# Four Signals 2.1 light surfaces. SVGs on GitHub cannot load web fonts, so
# these are the system stand-ins for Source Serif 4, Inter and JetBrains Mono.
PAGE, CARD, RULE, TEXT, SECONDARY, MUTED, ORANGE = "#f8fafc", "#ffffff", "#e2e8f0", "#0f172a", "#475569", "#94a3b8", "#e85d26"
SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


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
        f' stroke="{CARD}" stroke-width="1"/>'
        for r, x, y in zip(repos, xs, ys)
    )


def axis(left, right, top, bottom, label_y):
    parts = []
    for power, label in [(2, "100"), (3, "1k"), (4, "10k"), (5, "100k")]:
        x = left + (right - left) * power / LOG_MAX
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{RULE}" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{label_y}" text-anchor="middle" font-family="{MONO}" font-size="18"'
            f' fill="{SECONDARY}">{label}</text>'
        )
    return "\n".join(parts)


def label(x, y, text, anchor="start"):
    """Mono, upper-case section label."""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{MONO}" font-size="18"'
        f' letter-spacing="3" fill="{SECONDARY}">{escape(text.upper())}</text>'
    )


def svg(width, height, title, desc, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"'
        f' font-family="{SANS}">\n'
        f'<title id="title">{escape(title)}</title>\n<desc id="desc">{escape(desc)}</desc>\n'
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="4" fill="{CARD}" stroke="{RULE}"'
        f' stroke-width="2"/>\n{body}\n</svg>\n'
    )


def write_hero(repos, groups):
    counts = {name: sum(r["activity"] == name for r in repos) for name, _, _ in ACTIVITY}
    ai = sum(len(items) for name, items in groups.items() if name.startswith("AI"))
    legend = "\n".join(
        f'<circle cx="0" cy="{i * 34 - 7}" r="7" fill="{colour}"/>'
        f'<text x="22" y="{i * 34}" font-family="{MONO}" font-size="20" fill="{TEXT}">{name}</text>'
        f'<text x="250" y="{i * 34}" font-family="{MONO}" font-size="20" fill="{SECONDARY}" text-anchor="end">{counts[name]}</text>'
        for i, (name, colour, _) in enumerate(ACTIVITY)
    )
    body = f"""<g id="title-block" transform="translate(64 0)">
{label(0, 78, "// thinkjones / starred repositories")}
<text y="158" font-family="{SERIF}" font-size="72" font-weight="700" letter-spacing="-3" fill="{TEXT}">AI SDLC repo list</text>
<text y="208" font-size="25" fill="{TEXT}">{len(repos)} public repos sorted into {len(groups)} lists.</text>
<text y="242" font-size="25" fill="{SECONDARY}">{ai} of them are tools for building software with AI agents.</text>
</g>
<g id="legend" transform="translate(886 76)">
{legend}
</g>
<g id="swarm">
{label(64, 304, "// each dot is one repo, placed by GitHub stars")}
{axis(64, 1136, 320, 460, 490)}
{dots(repos, 64, 1136, 390, 5, 70)}
</g>"""
    desc = (
        f"{len(repos)} starred repositories plotted by star count and coloured by activity: "
        + ", ".join(f"{counts[name]} {name.lower()}" for name, _, _ in ACTIVITY)
        + "."
    )
    (ROOT / "assets/readme/hero.svg").write_text(
        svg(1200, 514, "AI SDLC repo list", desc, body), encoding="utf-8"
    )


def write_lists_chart(groups):
    row_h, top = 34, 88
    left, right = 600, 1144
    height = top + row_h * len(groups) + 26
    rows = []
    for i, (name, items) in enumerate(groups.items()):
        y = top + i * row_h
        rows.append(
            f'<text x="48" y="{y + 7}" font-size="20" fill="{TEXT}">{escape(name)}</text>'
            f'<text x="556" y="{y + 7}" font-family="{MONO}" font-size="20" fill="{SECONDARY}" text-anchor="end">{len(items)}</text>'
            f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="{RULE}" stroke-width="1"/>\n'
            + dots(items, left, right, y, 5, 9)
        )
    body = (
        label(48, 48, "// list")
        + label(556, 48, "repos", "end")
        + "\n"
        + axis(left, right, 62, height - 26, 48)
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
