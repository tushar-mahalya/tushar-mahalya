"""Rebuild the open-source contributions section of README.md.

Finds every merged pull request by USERNAME in repositories USERNAME doesn't
own, groups them by project, and writes:

- assets/oss-light.svg and assets/oss-dark.svg: a grid of project cards (logo,
  stars, merged PR count, latest PR), shown with <picture> so it follows the
  viewer's GitHub theme. The grid grows in rows of three, not one line per PR.
- a collapsed table with every merged PR, between the OSS markers in README.md.

One-line descriptions come from oss-notes.json (key: "owner/repo#number").
Org avatars are embedded in the SVG as data URIs, because GitHub's image proxy
doesn't load external images referenced from inside an SVG.

Standard library only. Set GITHUB_TOKEN to avoid the low anonymous rate limit.
"""

import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from html import escape
from pathlib import Path

USERNAME = "tushar-mahalya"
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
NOTES = ROOT / "oss-notes.json"
ASSETS = ROOT / "assets"
START, END = "<!-- OSS:START -->", "<!-- OSS:END -->"
SEARCH_QUERY = f"is:pr is:merged author:{USERNAME} -user:{USERNAME}"

COLUMNS, CARD_W, CARD_H, GAP = 3, 272, 132, 12
THEMES = {
    "light": {"bg": "#ffffff", "border": "#d0d7de", "text": "#1f2328", "muted": "#59636e", "accent": "#1a7f37", "chip": "#dafbe1"},
    "dark": {"bg": "#0d1117", "border": "#30363d", "text": "#e6edf3", "muted": "#9198a1", "accent": "#3fb950", "chip": "#12261e"},
}


def request(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "profile-readme-oss"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=30)


def api(url):
    with request(url) as resp:
        return json.load(resp)


def merged_prs():
    prs, page = [], 1
    while True:
        params = urllib.parse.urlencode(
            {"q": SEARCH_QUERY, "sort": "updated", "order": "desc", "per_page": 100, "page": page}
        )
        data = api(f"https://api.github.com/search/issues?{params}")
        prs += data["items"]
        if len(prs) >= data["total_count"] or not data["items"]:
            return prs
        page += 1


def avatar_data_uri(owner):
    try:
        with request(f"https://github.com/{owner}.png?size=96", accept="image/*") as resp:
            kind = resp.headers.get_content_type() or "image/png"
            return f"data:{kind};base64,{base64.b64encode(resp.read()).decode()}"
    except OSError:
        return ""


def short_number(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def projects(prs):
    grouped = {}
    for pr in prs:
        repo = pr["repository_url"].removeprefix("https://api.github.com/repos/")
        grouped.setdefault(repo, []).append(pr)
    result = []
    for repo, items in grouped.items():
        items.sort(key=lambda p: p["pull_request"]["merged_at"], reverse=True)
        info = api(f"https://api.github.com/repos/{repo}")
        result.append({
            "repo": repo,
            "owner": repo.split("/")[0],
            "name": repo.split("/")[1],
            "stars": info.get("stargazers_count", 0),
            "prs": items,
            "latest": items[0]["pull_request"]["merged_at"],
        })
    result.sort(key=lambda p: p["latest"], reverse=True)
    return result


def card(project, x, y, theme, avatar):
    t = THEMES[theme]
    count = len(project["prs"])
    latest = project["prs"][0]
    merged = datetime.strptime(latest["pull_request"]["merged_at"][:10], "%Y-%m-%d").strftime("%b %Y")
    title = escape(truncate(latest["title"], 38))
    clip = f"clip-{theme}-{x}-{y}"
    logo = (
        f'<clipPath id="{clip}"><rect x="{x + 16}" y="{y + 16}" width="36" height="36" rx="8"/></clipPath>'
        f'<image href="{avatar}" x="{x + 16}" y="{y + 16}" width="36" height="36" clip-path="url(#{clip})"/>'
        if avatar else ""
    )
    chip = f"{count} merged PR" + ("s" if count > 1 else "")
    chip_w = 14 + 6.6 * len(chip)
    return (
        f'<g>'
        f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{CARD_W - 1}" height="{CARD_H - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>'
        f"{logo}"
        f'<text x="{x + 62}" y="{y + 31}" class="owner" fill="{t["muted"]}">{escape(truncate(project["owner"], 28))}</text>'
        f'<text x="{x + 62}" y="{y + 49}" class="name" fill="{t["text"]}">{escape(truncate(project["name"], 24))}</text>'
        f'<text x="{x + CARD_W - 16}" y="{y + 80}" class="stars" fill="{t["muted"]}" text-anchor="end">★ {short_number(project["stars"])}</text>'
        f'<rect x="{x + 16}" y="{y + 66}" width="{chip_w:.0f}" height="20" rx="10" fill="{t["chip"]}"/>'
        f'<text x="{x + 23}" y="{y + 80}" class="chip" fill="{t["accent"]}">{chip}</text>'
        f'<text x="{x + 16}" y="{y + 106}" class="title" fill="{t["text"]}">{title}</text>'
        f'<text x="{x + 16}" y="{y + 122}" class="meta" fill="{t["muted"]}">latest · {merged}</text>'
        f"</g>"
    )


def svg(items, theme, avatars):
    rows = max(1, -(-len(items) // COLUMNS))
    width = COLUMNS * CARD_W + (COLUMNS - 1) * GAP
    height = rows * CARD_H + (rows - 1) * GAP
    cards = []
    for i, project in enumerate(items):
        x = (i % COLUMNS) * (CARD_W + GAP)
        y = (i // COLUMNS) * (CARD_H + GAP)
        cards.append(card(project, x, y, theme, avatars.get(project["owner"], "")))
    style = (
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}"
        ".owner{font-size:12px}.name{font-size:16px;font-weight:600}.stars{font-size:12px}"
        ".chip{font-size:11px;font-weight:600}.title{font-size:12px}.meta{font-size:11px}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Open-source projects with merged pull requests">'
        f"<style>{style}</style>{''.join(cards)}</svg>\n"
    )


def table(items, notes):
    lines = ["| Project | Contribution | Merged |", "|:--|:--|:-:|"]
    for project in items:
        for pr in project["prs"]:
            note = notes.get(f"{project['repo']}#{pr['number']}", "")
            title = pr["title"].replace("|", "\\|")
            what = f"[{title}]({pr['html_url']})" + (f"<br><sub>{note}</sub>" if note else "")
            merged = datetime.strptime(pr["pull_request"]["merged_at"][:10], "%Y-%m-%d").strftime("%b %Y")
            lines.append(f"| [{project['repo']}](https://github.com/{project['repo']}) | {what} | {merged} |")
    return "\n".join(lines)


def build(prs, notes):
    if not prs:
        return "_Contributions coming soon._"
    items = projects(prs)
    avatars = {p["owner"]: avatar_data_uri(p["owner"]) for p in items}
    ASSETS.mkdir(exist_ok=True)
    for theme in THEMES:
        (ASSETS / f"oss-{theme}.svg").write_text(svg(items, theme, avatars))
    stars = sum(p["stars"] for p in items)
    search = "https://github.com/search?" + urllib.parse.urlencode({"q": SEARCH_QUERY, "type": "pullrequests"})
    plural = lambda n, word: f"{n} {word}" + ("s" if n != 1 else "")
    return "\n".join([
        '<p align="center">',
        f'  <a href="{search}">',
        "    <picture>",
        '      <source media="(prefers-color-scheme: dark)" srcset="assets/oss-dark.svg">',
        '      <img alt="Open-source projects I have contributed to" src="assets/oss-light.svg" width="840">',
        "    </picture>",
        "  </a>",
        "</p>",
        "",
        f'<p align="center"><sub>{plural(len(prs), "merged PR")} in {plural(len(items), "project")} '
        f"with {short_number(stars)} combined stars · updated daily</sub></p>",
        "",
        "<details>",
        "<summary><b>All merged PRs</b></summary>",
        "",
        table(items, notes),
        "",
        "</details>",
    ])


def main():
    notes = json.loads(NOTES.read_text()) if NOTES.exists() else {}
    text = README.read_text()
    if START not in text or END not in text:
        sys.exit(f"README.md is missing the {START} / {END} markers")
    section = build(merged_prs(), notes)
    new = re.sub(
        rf"{re.escape(START)}.*?{re.escape(END)}",
        lambda _: f"{START}\n{section}\n{END}",
        text,
        flags=re.S,
    )
    if new != text:
        README.write_text(new)
        print("README.md updated")
    else:
        print("No changes")


if __name__ == "__main__":
    main()
