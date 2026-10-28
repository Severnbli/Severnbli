"""Draw the profile console (projects and stats) into assets/console.svg.

Needs GITHUB_TOKEN in the environment (GraphQL API).
"""
import json
import os
import random
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

# Commands typed (and never run) on the last prompt line, in order.
# Each step is ("type", text), ("erase", count) or ("wait", seconds).
# Typos hit a neighbouring QWERTY key: d for f, ^ (shift+6) for & (shift+7), j for h.
COMMANDS = [
    [("type", "rm -rd"), ("wait", 0.6), ("erase", 1), ("type", "f *")],
    [("type", "git push --force origin main")],
    [("type", ":(){ :|:^"), ("wait", 0.6), ("erase", 1), ("type", "& };:")],
    [("type", "git add .env && git push")],
    [("type", "shutdown -h now")],
    [("type", ":]")],
    [("type", "rm -rf *")],
    [("type", "git pusj"), ("wait", 0.6), ("erase", 1), ("type", "h --force origin main")],
    [("type", ":(){ :|:& };:")],
    [("type", "you still here? congratulations!")],
]
TYPE_S = (0.10, 0.24)  # random delay per typed key
ERASE_S = 0.05
HOLD_S = 2.0
PAUSE_S = 10.0
LEAD_S = 1.0  # empty prompt before the first command

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      totalCommitContributions totalPullRequestContributions
      totalIssueContributions restrictedContributionsCount
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        name description stargazerCount
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
        langs = [e["node"]["name"] for e in r["languages"]["edges"] if e["node"]["name"] not in HIDE_LANGS]
        lines.append([("m", f"{name + '/':<23}"), ("", f"*{r['stargazerCount']:<4}{', '.join(langs[:3]) or '-'}")])
        lines.append([("", "    " + fit(r["description"] or "no description", COLS - 4))])
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
    return [[("", f"{k} ".ljust(20, ".") + f" {v}")] for k, v in rows]


def cmd(text):
    return [("m", PROMPT), ("", text)]


def timeline():
    """Return the loop length and (start, end, typed, cursor_blinks) frames."""
    rng = random.Random(1)  # fixed seed keeps the svg stable between refreshes
    frames, t, typed = [], 0.0, ""

    def show(dur, blink=False):
        nonlocal t
        frames.append((t, t + dur, typed, blink))
        t += dur

    finals = []
    show(LEAD_S, True)
    for steps in COMMANDS:
        for kind, arg in steps:
            if kind == "type":
                for ch in arg:
                    typed += ch
                    show(rng.uniform(*TYPE_S))
            elif kind == "erase":
                for _ in range(arg):
                    typed = typed[:-1]
                    show(ERASE_S)
            else:
                show(arg, True)
        finals.append(typed)
        show(HOLD_S, True)
        while typed:
            typed = typed[:-1]
            show(ERASE_S)
        show(PAUSE_S - (LEAD_S if steps is COMMANDS[-1] else 0), True)
    # The loop wraps, so the last command also neighbours the first
    for a, b in zip(finals, finals[1:] + finals[:1]):
        assert a != b, f"{a!r} is typed twice in a row"
    return t, frames


def animated_line(y):
    total, frames = timeline()
    states = {}
    for start, end, typed, blink in frames:
        states.setdefault((typed, blink), []).append((start, end))
    css, out = [], []
    for i, ((typed, blink), windows) in enumerate(states.items()):
        keys = ["0%{opacity:0}"]
        for start, end in windows:
            keys.append(f"{start / total * 100:.4f}%{{opacity:1}}")
            keys.append(f"{end / total * 100:.4f}%{{opacity:0}}")
        css.append(f"@keyframes f{i}{{{''.join(keys)}}}")
        cursor = '<tspan class="m cur">&#9608;</tspan>' if blink else '<tspan class="m">&#9608;</tspan>'
        out.append(
            f'<text x="{PAD_X}" y="{y}" class="t" xml:space="preserve" opacity="0" '
            f'style="animation:f{i} {total:.2f}s steps(1,end) infinite">'
            f'<tspan class="m">{escape(PROMPT)}</tspan>{escape(typed)}{cursor}</text>'
        )
    return "\n".join(css), "\n".join(out)


def render(lines):
    w = PAD_X * 2 + COLS * CHAR_W
    h = TOP + LINE_H * len(lines) + 24
    out = []
    for i, spans in enumerate(lines):
        if spans:
            body = "".join(f'<tspan class="{cls}">{escape(s)}</tspan>' if cls else escape(s) for cls, s in spans)
            out.append(f'<text x="{PAD_X}" y="{TOP + LINE_H * i}" class="t" xml:space="preserve">{body}</text>')
    anim_css, anim = animated_line(TOP + LINE_H * len(lines))
    h += LINE_H
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<style>
.t{{font-family:'Courier New',Courier,monospace;font-size:{FONT}px;fill:{TEXT}}}
.m{{fill:{MAIN};font-weight:700}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
.cur{{animation:blink 1.1s steps(1) infinite}}
{anim_css}
</style>
<defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" fill-opacity=".35"/></pattern></defs>
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="{BG}" stroke="{MAIN}" stroke-width="3"/>
<rect x="7" y="7" width="{w - 14}" height="{h - 14}" fill="none" stroke="{MAIN}" stroke-width="1"/>
<rect x="7" y="7" width="{w - 14}" height="28" fill="{MAIN}"/>
<text x="{w / 2}" y="26" text-anchor="middle" class="t" style="fill:{BG};font-weight:700">severnbli@github: ~</text>
{chr(10).join(out)}
{anim}
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="url(#scan)"/>
</svg>
"""


def main():
    user = gql(QUERY, login=USER)
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    total, current, longest = streaks(contribution_days(created))
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    lines = (
        [cmd("ls projects/")]
        + projects_lines(repos)
        + [[], cmd("cat stats.txt")]
        + stats_lines(user, total, current, longest)
        + [[]]
    )
    with open(OUT, "w") as f:
        f.write(render(lines))
    print(f"wrote console at {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z")


if __name__ == "__main__":
    main()
