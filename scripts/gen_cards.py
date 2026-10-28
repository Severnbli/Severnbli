"""Draw the profile console (projects and stats) into assets/console.svg.

Needs GITHUB_TOKEN in the environment (GraphQL API).
"""
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

USER = "Severnbli"
PROMPT = "severnbli@github:~$ "
HIDE_LANGS = {"Rich Text Format"}
PINS = ["localization-codegen", "bell-timer", "nAlbum", "dmb-timers", "rockit"]
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "console.svg")

BG, MAIN, TEXT, DIM = "#0a0a0a", "#8b3dff", "#c8a8ff", "#5b2a9e"
COLS = 96
FONT, CHAR_W, LINE_H = 15, 9, 22
PAD_X, TOP = 24, 70

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      totalCommitContributions totalPullRequestContributions
      totalIssueContributions restrictedContributionsCount
    }
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        name description stargazerCount forkCount
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

CALENDAR = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""


def gql(query, **variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}"},
    )
    data = json.load(urllib.request.urlopen(req))
    if "errors" in data:
        raise SystemExit(data["errors"])
    return data["data"]["user"]


def contribution_days(created):
    # The calendar API spans at most one year per call
    days = {}
    start = created
    today = datetime.now(timezone.utc)
    while start < today:
        end = min(start + timedelta(days=365), today)
        cal = gql(CALENDAR, login=USER, **{"from": start.isoformat(), "to": end.isoformat()})
        for week in cal["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[date.fromisoformat(d["date"])] = d["contributionCount"]
        start = end
    return days


def streaks(days):
    longest = run = 0
    for d in sorted(days):
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    # Today without contributions yet does not break the current streak
    d = max(days)
    if not days[d]:
        d -= timedelta(days=1)
    current = 0
    while days.get(d):
        current += 1
        d -= timedelta(days=1)
    return sum(days.values()), current, longest


def fit(text, width):
    return text if len(text) <= width else text[: width - 3] + "..."


def projects_lines(repos):
    lines = []
    for name in PINS:
        r = repos[name]
        lang = (r["primaryLanguage"] or {}).get("name", "-")
        head = f"{name + '/':<23}{lang:<8}*{r['stargazerCount']:<4}"
        lines.append(("", head + fit(r["description"] or "", COLS - len(head))))
    return lines


def stats_lines(user, total, current, longest):
    c = user["contributionsCollection"]
    rows = [
        ("contributions", total),
        ("current streak", f"{current} days"),
        ("longest streak", f"{longest} days"),
        ("commits (1y)", c["totalCommitContributions"] + c["restrictedContributionsCount"]),
        ("pull requests", c["totalPullRequestContributions"]),
        ("issues", c["totalIssueContributions"]),
        ("stars", sum(r["stargazerCount"] for r in user["repositories"]["nodes"])),
        ("repositories", user["repositories"]["totalCount"]),
    ]
    return [("", f"{k} ".ljust(20, ".") + f" {v}") for k, v in rows]


def langs_lines(user):
    sizes = {}
    for r in user["repositories"]["nodes"]:
        for e in r["languages"]["edges"]:
            if e["node"]["name"] in HIDE_LANGS:
                continue
            sizes[e["node"]["name"]] = sizes.get(e["node"]["name"], 0) + e["size"]
    total = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:6]
    return [
        ("", f"{name[:14]:<14} [{'#' * round(size / total * 40):<40}] {size / total * 100:5.1f}%")
        for name, size in top
    ]


def render(lines):
    w = PAD_X * 2 + COLS * CHAR_W
    h = TOP + LINE_H * len(lines) + 24
    out = []
    for i, (cls, text) in enumerate(lines):
        y = TOP + LINE_H * i
        if cls == "cmd":
            out.append(
                f'<text x="{PAD_X}" y="{y}" class="t" xml:space="preserve">'
                f'<tspan class="m">{escape(PROMPT)}</tspan>{escape(text)}</text>'
            )
        elif cls == "cursor":
            out.append(
                f'<text x="{PAD_X}" y="{y}" class="t" xml:space="preserve">'
                f'<tspan class="m">{escape(PROMPT)}</tspan><tspan class="m cur">&#9608;</tspan></text>'
            )
        elif text:
            out.append(f'<text x="{PAD_X}" y="{y}" class="t" xml:space="preserve">{escape(text)}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<style>
.t{{font-family:'Courier New',Courier,monospace;font-size:{FONT}px;fill:{TEXT}}}
.m{{fill:{MAIN};font-weight:700}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
.cur{{animation:blink 1.1s steps(1) infinite}}
</style>
<defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" fill-opacity=".35"/></pattern></defs>
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="{BG}" stroke="{MAIN}" stroke-width="3"/>
<rect x="7" y="7" width="{w - 14}" height="{h - 14}" fill="none" stroke="{MAIN}" stroke-width="1"/>
<rect x="7" y="7" width="{w - 14}" height="28" fill="{MAIN}"/>
<text x="{w / 2}" y="26" text-anchor="middle" class="t" style="fill:{BG};font-weight:700">severnbli@github: ~</text>
{chr(10).join(out)}
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="url(#scan)"/>
</svg>
"""


def main():
    user = gql(QUERY, login=USER)
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    total, current, longest = streaks(contribution_days(created))
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    lines = (
        [("cmd", "ls projects/")]
        + projects_lines(repos)
        + [("", ""), ("cmd", "cat stats.txt")]
        + stats_lines(user, total, current, longest)
        + [("", ""), ("cmd", "du -sh languages/*")]
        + langs_lines(user)
        + [("", ""), ("cursor", "")]
    )
    with open(OUT, "w") as f:
        f.write(render(lines))
    print(f"wrote console at {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z")


if __name__ == "__main__":
    main()
