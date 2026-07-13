#!/usr/bin/env python3
"""Collector: regenerate a site's History board from its own git log.

A skimmable digest (pushes-per-day bars + push-mix donut) over a HISTORY PER
BOARD: one console section per board, listing the pushes that touched that
board, newest first, tone-coded (authored / by-hand). A status push carries ONE
message for the whole push, so a board's line is the push's overall message;
when several boards moved together the line notes the others ("· also fleet").
Scheduled metric refreshes are excluded from the per-board logs (regenerations,
not authored updates) but still count in the digest.

Generic: nothing here knows a specific board. Titles and (optional) per-board
icons are read from the site's status.json manifest; a board with no `icon`
falls back to a neutral default. Output: <site>/history/board.json, and the
manifest's `history` entry is stamped today.

Site location resolves from STATUS_SITE_DIR, else ROOST_STATUS_SITE in
~/.roostrc. Run standalone or via `roost status`; safe any time.
"""
import datetime
import json
import os
import re
import subprocess
import sys

MAX_LINES = 40        # kept for parity; per-board caps below
CHART_DAYS = 14
PER_BOARD_MAX = 15
DEFAULT_ICON = "📋"


def resolve_site():
    """Where the status site lives. Env wins; else ~/.roostrc; else error."""
    d = os.environ.get("STATUS_SITE_DIR")
    if not d:
        try:
            for line in open(os.path.expanduser("~/.roostrc")):
                line = line.strip()
                if line.startswith("ROOST_STATUS_SITE=") and "=" in line:
                    d = os.path.expandvars(line.split("=", 1)[1].strip())
                    break
        except OSError:
            pass
    if not d:
        sys.exit("history: no site dir — set STATUS_SITE_DIR or ROOST_STATUS_SITE")
    d = os.path.expanduser(d)
    if not os.path.isdir(os.path.join(d, ".git")):
        sys.exit(f"history: {d} is not a git repo (the site must be versioned)")
    return d


DIR = resolve_site()


def git(*args):
    return subprocess.run(["git", *args], cwd=DIR, capture_output=True, text=True).stdout


def classify(subject):
    """(display text, status word, tone) for a push's commit subject.
    `roost status` commits as "status: <msg> (YYYY-MM-DD)"; anything else
    touching a board.json was a by-hand commit."""
    if not subject.startswith("status: "):
        return subject, "edit", "wip"
    text = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)$", "", subject[len("status: "):])
    if text.startswith("scheduled refresh"):
        return text, "auto", "done"
    return text, "push", "go"


# \x01 separates commits, \x1f separates header fields, so subjects can
# contain anything; --name-only lists the board files under each header.
records = git("log", "--format=%x01%H%x1f%ci%x1f%s", "--name-only",
              "--", "*/board.json").split("\x01")
pushes = []
for rec in records:
    if not rec.strip():
        continue
    head, _, files = rec.partition("\n")
    sha, ci, subject = head.split("\x1f")
    boards = sorted({f.split("/")[0] for f in files.splitlines()
                     if f.endswith("board.json") and not f.startswith("history/")})
    if not boards:
        continue  # only history/board.json itself changed — not a real push
    dt = datetime.datetime.strptime(ci, "%Y-%m-%d %H:%M:%S %z")
    pushes.append({"sha": sha, "dt": dt, "subject": subject, "boards": boards})

# ---- digest ----------------------------------------------------------------

per_day = {}
mix = {"push": 0, "auto": 0, "edit": 0}
board_set = set()
for p in pushes:
    per_day[p["dt"].date()] = per_day.get(p["dt"].date(), 0) + 1
    mix[classify(p["subject"])[1]] += 1
    board_set.update(p["boards"])

today = datetime.date.today()
days = [today - datetime.timedelta(days=i) for i in range(CHART_DAYS - 1, -1, -1)]
series = [{"label": d.strftime("%m-%d"), "value": per_day.get(d, 0), "fill": "code"}
          for d in days]

slices = [s for s in [
    {"label": "authored updates", "value": mix["push"], "tone": "go"},
    {"label": "scheduled refreshes", "value": mix["auto"], "tone": "done"},
    {"label": "by-hand commits", "value": mix["edit"], "tone": "wip"},
] if s["value"]]

# ---- per-board logs --------------------------------------------------------
# One console section per board: the pushes that touched THAT board, newest
# first. Auto "scheduled refresh" commits are excluded here (they still count in
# the digest). A push's message covers the whole push, so other boards moved in
# the same push are noted as "· also <slug>". Titles + icons come from the
# manifest, so this stays board-agnostic.
manifest_path = os.path.join(DIR, "status.json")
manifest = json.load(open(manifest_path))
titles = {b["slug"]: b.get("title", b["slug"]) for b in manifest}
icons = {b["slug"]: b.get("icon", DEFAULT_ICON) for b in manifest}

per_board = {}   # slug -> pushes touching it, newest first (pushes already are)
last_dt = {}     # slug -> most recent authored push, for ordering sections
for p in pushes:
    if classify(p["subject"])[1] == "auto":
        continue  # scheduled metric refresh, not an authored board update
    for slug in p["boards"]:
        per_board.setdefault(slug, []).append(p)
        last_dt.setdefault(slug, p["dt"])

board_sections = []
for slug in sorted(per_board, key=lambda s: last_dt[s], reverse=True):
    ps = per_board[slug]
    board_lines = []
    for p in ps[:PER_BOARD_MAX]:
        text, status, tone = classify(p["subject"])
        others = [b for b in p["boards"] if b != slug]
        meta = p["dt"].strftime("%m-%d %H:%M")
        if others:
            meta += " · also " + "+".join(others)
        board_lines.append({"status": status, "tone": tone,
                            "text": text[:160], "meta": meta})
    board_sections.append({
        "kind": "console", "icon": icons.get(slug, DEFAULT_ICON),
        "title": titles.get(slug, slug),
        "desc": "updates that touched this board",
        "count": f"showing {min(PER_BOARD_MAX, len(ps))} of {len(ps)}",
        "lines": board_lines,
    })

board = {
    "title": "History",
    "eyebrow": "status.jimmyhoughjr.net",
    "stamp": f"Updated {today.isoformat()} — status pushes grouped by board (each "
             "board is a repo), newest first, straight from git. Green dot = "
             "authored update, amber = by-hand commit. Scheduled metric refreshes "
             "are left out of the per-board logs; a push's message covers the whole "
             "push, so boards that moved together share wording ('· also …').",
    "sections": [
        {"kind": "stats", "items": [
            {"n": str(len(pushes)), "label": "Status pushes", "tone": "go"},
            {"n": str(per_day.get(today, 0)), "label": "Today", "tone": "you"},
            {"n": str(len(board_set)), "label": "Boards tracked", "tone": "go"},
            {"n": pushes[0]["dt"].strftime("%m-%d %H:%M") if pushes else "—",
             "label": "Latest push", "tone": "done"},
        ]},
        {"kind": "barchart", "icon": "📈", "title": "Activity",
         "desc": f"pushes per day, last {CHART_DAYS} days",
         "series": series},
        {"kind": "pie", "icon": "🍩", "title": "Push mix",
         "desc": "who triggered what, all time",
         "slices": slices},
        *board_sections,
    ],
}
os.makedirs(os.path.join(DIR, "history"), exist_ok=True)
json.dump(board, open(os.path.join(DIR, "history/board.json"), "w"), indent=2, ensure_ascii=False)

# make sure the hub lists it, stamped today
for b in manifest:
    if b["slug"] == "history":
        b["updated"] = today.isoformat()
        break
else:
    manifest.append({"slug": "history", "title": "History",
                     "description": "Every status push, newest first — browse how each board evolved.",
                     "updated": today.isoformat()})
json.dump(manifest, open(manifest_path, "w"), indent=2, ensure_ascii=False)
print(f"history board: {len(board_sections)} per-board logs, "
      f"{len(pushes)} pushes total, {per_day.get(today, 0)} today")
