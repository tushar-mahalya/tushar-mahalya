"""Rebuild the open-source contributions section of README.md.

Finds every merged pull request by USERNAME in repositories USERNAME doesn't
own, and writes them as a table between the OSS markers in README.md.
One-line descriptions come from oss-notes.json (key: "owner/repo#number");
a PR without a note falls back to its title.

Standard library only. Set GITHUB_TOKEN to avoid the low anonymous rate limit.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

USERNAME = "tushar-mahalya"
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
NOTES = ROOT / "oss-notes.json"
START, END = "<!-- OSS:START -->", "<!-- OSS:END -->"


def api(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def merged_prs():
    query = f"is:pr is:merged author:{USERNAME} -user:{USERNAME}"
    prs, page = [], 1
    while True:
        params = urllib.parse.urlencode(
            {"q": query, "sort": "updated", "order": "desc", "per_page": 100, "page": page}
        )
        data = api(f"https://api.github.com/search/issues?{params}")
        prs += data["items"]
        if len(prs) >= data["total_count"] or not data["items"]:
            return prs
        page += 1


def row(pr, notes):
    repo = pr["repository_url"].removeprefix("https://api.github.com/repos/")
    owner = repo.split("/")[0]
    key = f"{repo}#{pr['number']}"
    merged = pr["pull_request"]["merged_at"][:10]
    note = notes.get(key, "")
    title = pr["title"].replace("|", "\\|")
    what = f"[{title}]({pr['html_url']})" + (f"<br><sub>{note}</sub>" if note else "")
    return pr["pull_request"]["merged_at"], (
        f'| <img src="https://github.com/{owner}.png?size=80" width="40" alt="{owner}"/> '
        f"| **[{repo}](https://github.com/{repo})**<br>"
        f"![stars](https://img.shields.io/github/stars/{repo}?style=flat-square&label=%E2%98%85&color=4B5563) "
        f"| {what} "
        f"| {datetime.strptime(merged, '%Y-%m-%d').strftime('%b %Y')} |"
    )


def build(prs, notes):
    if not prs:
        return "_Contributions coming soon._"
    rows = sorted((row(pr, notes) for pr in prs), reverse=True)
    repos = {pr["repository_url"] for pr in prs}
    summary = (
        f"![Merged PRs](https://img.shields.io/badge/merged_PRs-{len(prs)}-10B981?style=for-the-badge&logo=github) "
        f"![Projects](https://img.shields.io/badge/projects-{len(repos)}-4B5563?style=for-the-badge&logo=git&logoColor=white)"
    )
    lines = [
        '<div align="center">',
        "",
        summary,
        "",
        "</div>",
        "",
        "| | Project | Contribution | Merged |",
        "|:-:|:--|:--|:-:|",
        *(r for _, r in rows),
    ]
    return "\n".join(lines)


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
