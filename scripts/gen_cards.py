"""Draw the profile console (projects and stats) into assets/console-<datetime>.svg.

Needs GITHUB_TOKEN in the environment (GraphQL API).
"""
import glob
import json
import os
import random
import re
import textwrap
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

USER = "Severnbli"
PROMPT = "severnbli@github:~$ "
# Scripts, build files, shaders and documents rather than the language a project is written in
HIDE_LANGS = {
    "Shell", "PowerShell", "Batchfile", "Makefile", "CMake", "Dockerfile", "Procfile", "Nix",
    "ShaderLab", "HLSL", "GLSL", "Cg",
    "Rich Text Format", "TeX", "Roff",
}
PINS = ["localization-codegen", "bell-timer", "nAlbum", "dmb-timers", "rockit"]
ROOT = os.path.join(os.path.dirname(__file__), "..")
README = os.path.join(ROOT, "README.md")

BG = "#0a0a0a"
# (accent, text) per weekday, Monday first; the card is redrawn every night
# Weekday colors and image names follow local time (UTC+3), not UTC
TZ = timezone(timedelta(hours=3))
THEMES = [
    ("#8b3dff", "#c8a8ff"),  # Monday: violet
    ("#3d8bff", "#a8c8ff"),  # Tuesday: blue
    ("#00c8a0", "#a0f0dc"),  # Wednesday: teal
    ("#3ddc4a", "#b0f5b5"),  # Thursday: green
    ("#ffb000", "#ffe0a0"),  # Friday: amber
    ("#ff5a3d", "#ffc0b0"),  # Saturday: red
    ("#ff3d9e", "#ffb0d8"),  # Sunday: pink
]
COLS = 96
FONT, CHAR_W, LINE_H = 15, 9, 22
PAD_X, TOP = 24, 70
DESC_COL = 46  # project description column

# Commands typed (and never run) on the last prompt line, in order.
# Each step is ("type", text), ("erase", count) or ("wait", seconds).
COMMANDS = [
    [("type", "you still here? congratulations! :]")],
]
TYPE_S = (0.05, 0.12)  # random delay per typed key
ERASE_S = 0.03
HOLD_S = 2.0
PAUSE_S = 3.0  # empty prompt after each command
LEAD_S = 120.0  # empty prompt before the first command
# Run at the start of every loop; their output appears after Enter.
# Each is (typed, completed): the keys are typed, then Tab fills in the rest
INTRO = [("ls p", "ls projects/"), ("cat s", "cat stats.txt")]
TAB_S = 0.25  # pause before Tab completes the name
INTRO_WAIT_S = 0.6  # cursor blinks on an empty prompt before typing

# After the last command the console "reboots": a shutdown broadcast, a black
# screen, and the loop wraps around to the boot log it starts with.
REBOOT_CMD = "shutdown -r now"
ENTER_S = 0.5  # pause before the reboot command "runs"
# (appears, disappears or None to stay, text); seconds from the reboot start
BOOT = [
    (0.0, 0.8, "Broadcast message from severnbli@github (pts/0):"),
    (0.0, 0.8, "The system is going down for reboot NOW!"),
    (1.2, None, "SEVERNBLI BIOS v1.87   (C) 1987 Severnbli Megatrends"),
    (1.4, None, "CPU: Intel 80486DX @ 33 MHz"),
    (1.6, None, "Memory Test: {mem}"),
    (2.1, None, ""),
    (2.1, None, "Booting severnbli-os from /dev/github ..."),
    (2.3, None, "[  OK  ] Mounted ~/projects."),
    (2.5, None, "[  OK  ] Loaded stats.txt."),
    (2.7, None, "[ FAIL ] Failed to find .env (pushed to remote)."),
    (2.9, None, "[  OK  ] Started GitHub Profile Daemon."),
    (3.1, None, "Loading {bar}"),
    (3.9, None, ""),
    (4.0, None, "severnbli-os login: severnbli"),
]
MEM_STEPS = (1.6, 0.4, ["0K", "128K", "256K", "384K", "512K", "640K OK"])
BAR_STEPS = (3.1, 0.7, 10)  # start, duration, steps
BOOT_S = 4.4
SHUTDOWN_S = 1.2  # BOOT entries before this play at the end of the loop, the rest at its start

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
        # The description sits right of the columns, wrapped over two lines.
        # Columns get fixed x positions so they line up in any monospace font.
        width = COLS - DESC_COL
        desc = textwrap.wrap(r["description"] or "no description", width) + [""]
        if len(desc) > 3:
            desc[1] = fit(" ".join(desc[1:]), width)
        lines.append([
            ("", f"{name}/", 0),
            ("", f"*{r['stargazerCount']}", 23),
            ("", ", ".join(langs[:3]) or "-", 28),
            ("", desc[0], DESC_COL),
        ])
        lines.append([("", desc[1], DESC_COL)])
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


def timeline():
    """Return the loop length, the last prompt's frames, the reboot time, and
    for each intro command its frames and when its output appears.

    A frame is (start, end, typed, cursor) where cursor is True (blinking),
    False (solid while typing) or None (no cursor once the command ran).
    """
    rng = random.Random(1)  # fixed seed keeps the svg stable between refreshes
    t = BOOT_S - SHUTDOWN_S
    intro, outputs = [], []
    for prefix, text in INTRO:
        assert text.startswith(prefix), f"{prefix!r} does not complete to {text!r}"
        f = [(t, t + INTRO_WAIT_S, "", True)]
        t += INTRO_WAIT_S
        for i in range(1, len(prefix) + 1):
            d = rng.uniform(*TYPE_S)
            f.append((t, t + d, prefix[:i], False))
            t += d
        f.append((t, t + TAB_S, prefix, False))
        t += TAB_S
        f.append((t, t + ENTER_S, text, True))
        t += ENTER_S
        intro.append(f)
        outputs.append(t)

    frames, typed = [], ""

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
        show(PAUSE_S, True)
    for ch in REBOOT_CMD:
        typed += ch
        show(rng.uniform(*TYPE_S))
    finals.append(typed)
    show(ENTER_S, True)
    # The loop wraps, so the last command also neighbours the first
    for a, b in zip(finals, finals[1:] + finals[:1]):
        assert a != b, f"{a!r} is typed twice in a row"
    total = t + SHUTDOWN_S
    # Intro commands stay printed until the reboot clears the screen
    for f, at in zip(intro, outputs):
        f.append((at, total, f[-1][2], None))
    return total, frames, t, intro, outputs


def keyframes(name, windows, total):
    keys = ["0%{opacity:0}"]
    for start, end in windows:
        keys.append(f"{start / total * 100:.4f}%{{opacity:1}}")
        keys.append(f"{end / total * 100:.4f}%{{opacity:0}}")
    return f"@keyframes {name}{{{''.join(keys)}}}"


def animated(name, total):
    return f'opacity="0" style="animation:{name} {total:.2f}s steps(1,end) infinite"'


def boot_screen(w, h, total, start):
    """Black screen with the shutdown broadcast from start to the end of the
    loop, and the boot log from the beginning of the loop."""
    booted = BOOT_S - SHUTDOWN_S

    def loop_time(x):
        # x is seconds from the reboot; the boot part wraps to the loop start
        return start + x if x < SHUTDOWN_S else x - SHUTDOWN_S

    css = [keyframes("boot", [(0, booted), (start, total)], total)]
    out = [f'<rect x="7" y="7" width="{w - 14}" height="{h - 14}" fill="{BG}" {animated("boot", total)}/>']

    def variants(text):
        # Lines with a counter get one variant per step, each shown until the next
        if "{mem}" in text:
            at, dur, steps = MEM_STEPS
            return [(at + dur * i / (len(steps) - 1), text.format(mem=m)) for i, m in enumerate(steps)]
        if "{bar}" in text:
            at, dur, n = BAR_STEPS
            return [
                (at + dur * i / n, text.format(bar=f"[{'#' * (i * 2):<{n * 2}}] {i * 100 // n:3}%"))
                for i in range(n + 1)
            ]
        return [(None, text)]

    # Lines that disappear are gone before the rest show, so both start at the top
    rows = {True: 0, False: 0}
    for i, (shown, hidden, text) in enumerate(BOOT):
        row = rows[hidden is None]
        rows[hidden is None] += 1
        steps = variants(text)
        for j, (at, variant) in enumerate(steps):
            if not variant:
                continue
            a = loop_time(at if at is not None else shown)
            b = loop_time(steps[j + 1][0]) if j + 1 < len(steps) else loop_time(hidden) if hidden else booted
            name = f"b{i}_{j}"
            css.append(keyframes(name, [(a, b)], total))
            body = escape(variant)
            for tag in ("[  OK  ]", "[ FAIL ]"):
                body = body.replace(tag, f'<tspan class="m">{tag}</tspan>')
            out.append(
                f'<text x="{PAD_X}" y="{40 + LINE_H * row}" class="t" xml:space="preserve" '
                f'{animated(name, total)}>{body}</text>'
            )
    return "\n".join(css), "\n".join(out)


def animated_line(prefix, y, total, frames):
    states = {}
    for start, end, typed, blink in frames:
        states.setdefault((typed, blink), []).append((start, end))
    css, out = [], []
    for i, ((typed, blink), windows) in enumerate(states.items()):
        name = f"{prefix}{i}"
        css.append(keyframes(name, windows, total))
        cursor = {True: '<tspan class="m cur">&#9608;</tspan>', False: '<tspan class="m">&#9608;</tspan>', None: ""}[blink]
        out.append(
            f'<text x="{PAD_X}" y="{y}" class="t" xml:space="preserve" {animated(name, total)}>'
            f'<tspan class="m">{escape(PROMPT)}</tspan>{escape(typed)}{cursor}</text>'
        )
    return "\n".join(css), "\n".join(out)


def text_row(y, spans):
    """One row of text. A span with a column starts its own <text> at a fixed x,
    so columns line up whatever the font width or zoom level."""
    groups = []
    for cls, text, *col in spans:
        if col or not groups:
            groups.append((col[0] if col else 0, []))
        groups[-1][1].append(f'<tspan class="{cls}">{escape(text)}</tspan>' if cls else escape(text))
    return "\n".join(
        f'<text x="{PAD_X + col * CHAR_W}" y="{y}" class="t" xml:space="preserve">{"".join(body)}</text>'
        for col, body in groups
        if any(body)
    )


def render(lines, main, text):
    """Lines are span lists, or an int k marking where INTRO[k] is typed;
    the lines after it are its output."""
    w = PAD_X * 2 + COLS * CHAR_W
    h = TOP + LINE_H * len(lines) + 24 + LINE_H
    total, frames, reboot, intro, outputs = timeline()
    css, out, group = [], [], None
    for i, line in enumerate(lines):
        y = TOP + LINE_H * i
        if isinstance(line, int):
            if group is not None:
                out.append("</g>")
            group = line
            c, a = animated_line(f"i{line}_", y, total, intro[line])
            css.append(c)
            out.append(a)
            css.append(keyframes(f"o{line}", [(outputs[line], total)], total))
            out.append(f"<g {animated(f'o{line}', total)}>")
        elif line:
            out.append(text_row(y, line))
    if group is not None:
        out.append("</g>")
    c, a = animated_line("f", TOP + LINE_H * len(lines), total, frames)
    css.append(c)
    out.append(a)
    boot_css, boot = boot_screen(w, h, total, reboot)
    anim_css, anim = "\n".join(css), ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<style>
.t{{font-family:'Courier New',Courier,monospace;font-size:{FONT}px;fill:{text}}}
.m{{fill:{main};font-weight:700}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
.cur{{animation:blink 1.1s steps(1) infinite}}
{anim_css}
{boot_css}
</style>
<defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" fill-opacity=".35"/></pattern></defs>
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="{BG}" stroke="{main}" stroke-width="3"/>
<rect x="7" y="7" width="{w - 14}" height="{h - 14}" fill="none" stroke="{main}" stroke-width="1"/>
<rect x="7" y="7" width="{w - 14}" height="28" fill="{main}"/>
<text x="{w / 2}" y="26" text-anchor="middle" class="t" style="fill:{BG};font-weight:700">severnbli@github: ~</text>
{chr(10).join(out)}
{anim}
{boot}
<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" fill="url(#scan)"/>
</svg>
"""


def main():
    user = gql(QUERY, login=USER)
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    total, current, longest = streaks(contribution_days(created))
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    lines = (
        [0]
        + projects_lines(repos)
        + [[], 1]
        + stats_lines(user, total, current, longest)
        + [[]]
    )
    now = datetime.now(TZ)
    main_color, text_color = THEMES[now.weekday()]
    svg = render(lines, main_color, text_color)
    # GitHub caches images by URL, so the generation time in the name forces a fresh copy
    name = f"console-{now:%Y%m%d-%H%M%S}.svg"
    for old in glob.glob(os.path.join(ROOT, "assets", "console*.svg")):
        os.remove(old)
    with open(os.path.join(ROOT, "assets", name), "w") as f:
        f.write(svg)
    with open(README) as f:
        readme = f.read()
    readme = re.sub(r"assets/console[^\"]*\.svg", f"assets/{name}", readme)
    # Badge icons follow the day's accent too
    readme = re.sub(r"logoColor=[0-9a-f]{6}", f"logoColor={main_color[1:]}", readme)
    with open(README, "w") as f:
        f.write(readme)
    print(f"wrote {name} at {now:%Y-%m-%d %H:%M} UTC+3")


if __name__ == "__main__":
    main()
