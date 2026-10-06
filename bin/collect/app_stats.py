#!/usr/bin/env python3
"""app_stats.py - fill a product board's stats row from pulse's feed for its app (house#93).

A product board such as vault or watts names its app in its config.json, `"app": "vault"`. This reads pulse's one feed
for that app, GET /api/app/<name>, the same feed the coop's app page reads, so the board and the coop cannot disagree,
and writes the board's first stats section: whether it answers, its memory, its secrets owed a rotation, its jobs, and
last night's backup. The banner and every other section stay as a person wrote them.

A board may also name a wayfinder map, `"map": "jimmy/house#103"`. Then the board's Features section is drawn from
that map's tickets on the forge, one card per ticket with its state (house#94): a closed ticket is shipped, an open
one that a seat holds is in flight, and an open one nobody holds is next. The tickets are read with a read-only forge
token from ROOST_FORGE_ISSUE_TOKEN in roostrc, the way the CI collector's token is held, or ROOST_FORGE_TOKEN, or the file
ROOST_FORGE_TOKEN_FILE names, on standard input
to curl and never on a command line. No token -> the Features section is left as it is.

Config (~/.roostrc or the environment):
  ROOST_PULSE_URL=https://pulse.example.net   # pulse, default https://pulse.jimmyhoughjr.net
  ROOST_NODE_KEY=...                           # pulse's node key, or
  ROOST_NODE_KEY_FILE=~/.roost_node_key        # the file that holds it, the default
  ROOST_FORGE_URL=https://forgejo.example.net  # the forge, default https://forgejo.jimmyhoughjr.net
  ROOST_FORGE_ISSUE_TOKEN=...                  # a read-only forge token in roostrc, placed by hatchery's rotation, or
  ROOST_FORGE_TOKEN=...                        # the same from the environment, or
  ROOST_FORGE_TOKEN_FILE=~/.forge_read_token   # the file that holds it, the default

The key goes to curl on standard input and never on a command line, so the process list never shows it.

Non-fatal by contract: no key -> skip; a board whose feed does not answer -> that board untouched; always exit 0.
"""
import datetime
import json
import re
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

ANSWER_TONES = {"answering": "go", "drifting": "you", "not running": "stop", "stale": "none"}
BACKUP_TONES = {"go": "go", "warn": "you", "stop": "stop"}


def node_key(cfg):
    """The node key from the environment, roostrc, or the holder file the host keeps."""
    value = cfg.get("ROOST_NODE_KEY", "")
    if value:
        return value
    path = os.path.expanduser(cfg.get("ROOST_NODE_KEY_FILE", "~/.roost_node_key"))
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def forge_token(cfg):
    """A read-only forge token from the environment, roostrc, or the holder file the host keeps."""
    value = cfg.get("ROOST_FORGE_ISSUE_TOKEN", "") or cfg.get("ROOST_FORGE_TOKEN", "")
    if value:
        return value
    path = os.path.expanduser(cfg.get("ROOST_FORGE_TOKEN_FILE", "~/.forge_read_token"))
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def read_map_tickets(forge, token, spec):
    """The tickets under one map, `owner/repo#number`, newest first, or None with the reason."""
    try:
        repo, number = spec.rsplit("#", 1)
        number = int(number)
    except ValueError:
        return None, "a map is owner/repo#number"
    url = "{}/api/v1/repos/{}/issues?state=all&type=issues&limit=200".format(forge.rstrip("/"), repo)
    config = 'header = "Authorization: token {}"\nheader = "User-Agent: statusgen-app-stats/1"\n'.format(token)
    try:
        answer = subprocess.run(["curl", "-sfS", "--max-time", "20", "-K", "-", url], input=config, capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if answer.returncode != 0:
        return None, answer.stderr.strip() or "curl exit {}".format(answer.returncode)
    try:
        issues = json.loads(answer.stdout)
    except ValueError as error:
        return None, "not json: {}".format(error)
    mark = re.compile(r"^Part of #{}\b".format(number), re.M)
    tickets = [i for i in issues if isinstance(i, dict) and mark.search(i.get("body") or "")]
    tickets.sort(key=lambda i: i.get("number", 0))
    return tickets, None


def feature_cards(tickets):
    """One card per ticket: its number, its title, and its state as a pill."""
    cards = []
    for t in tickets:
        closed = t.get("state") == "closed"
        held = bool(t.get("assignees")) or bool(t.get("assignee"))
        pill = {"text": "Shipped", "tone": "done"} if closed else {"text": "In flight", "tone": "srv"} if held else {"text": "Next", "tone": "you"}
        card = {"id": "#{}".format(t.get("number")), "q": t.get("title", ""), "pill": pill}
        if t.get("html_url"):
            card["href"] = t["html_url"]
        cards.append(card)
    return cards


def write_features(board, tickets, spec):
    """Replaces the Features section's cards with the map's tickets, and says where they came from."""
    section = {"kind": "cards", "title": "Features", "items": feature_cards(tickets),
               "count": "{} shipped of {}".format(sum(1 for t in tickets if t.get("state") == "closed"), len(tickets)),
               "desc": "from the tickets of {}".format(spec)}
    lib.upsert_section(board, "Features", section, after_kind="stats")
    return board


def read_feed(pulse, key, app):
    """Pulse's feed for one app, or None with the reason. curl, because the mini grants Local Network access per binary."""
    url = "{}/api/app/{}".format(pulse.rstrip("/"), app)
    config = 'header = "x-roost-node-key: {}"\nheader = "User-Agent: statusgen-app-stats/1"\n'.format(key)
    try:
        answer = subprocess.run(["curl", "-sfS", "--max-time", "20", "-K", "-", url], input=config, capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if answer.returncode != 0:
        return None, answer.stderr.strip() or "curl exit {}".format(answer.returncode)
    try:
        return json.loads(answer.stdout), None
    except ValueError as error:
        return None, "not json: {}".format(error)


def items(feed):
    """The stats tiles for one feed: answers, memory, secrets, jobs, backup."""
    out = []
    answers = feed.get("answers")
    kind = feed.get("kind", "app")
    declared = feed.get("declared") or {}
    if kind != "job":
        if answers:
            state = answers.get("state", "stale")
            code = answers.get("httpCode")
            label = "Answers" if state == "answering" else "Answers {} where {} is expected".format(code or "nothing", declared.get("expectedStatus", "200")) if state == "drifting" else "Not running" if state == "not running" else "No answer from the reconcile"
            out.append({"n": code or state, "label": label, "tone": ANSWER_TONES.get(state, "none")})
            if answers.get("memMb") is not None:
                out.append({"n": answers["memMb"], "label": "MB in use", "tone": "go"})
        else:
            out.append({"n": "—", "label": "No answer from the reconcile", "tone": "none"})
    secrets = feed.get("secrets") or {}
    if secrets.get("count"):
        owed = secrets.get("owed", 0)
        out.append({"n": "{}/{}".format(owed, secrets["count"]), "label": "Secrets owed a rotation", "tone": "go" if owed == 0 else "you"})
    jobs = feed.get("jobs") or []
    if jobs:
        bad = [j for j in jobs if j.get("state") in ("failed", "late", "drift")]
        out.append({"n": "{}/{}".format(len(bad), len(jobs)), "label": "Jobs late or failed", "tone": "stop" if any(j.get("state") == "failed" for j in bad) else "you" if bad else "go"})
    backup = feed.get("backup")
    if backup:
        tone = backup.get("tone") or "unknown"
        out.append({"n": tone, "label": "Last night's backup of its box", "tone": BACKUP_TONES.get(tone, "none")})
    return out


def write_stats(board, feed, app):
    """Replaces the items of the board's first stats section, and says where they came from."""
    sections = board.get("sections", [])
    at = next((i for i, s in enumerate(sections) if isinstance(s, dict) and s.get("kind") == "stats"), None)
    section = dict(sections[at]) if at is not None else {"kind": "stats"}
    section["items"] = items(feed)
    section["generatedAt"] = feed.get("read") or lib.generated_now()
    section["desc"] = "generated from pulse's feed for {}, read {}".format(app, feed.get("read") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if at is not None:
        sections[at] = section
    else:
        sections.insert(0, section)
    board["sections"] = sections
    return board


def main():
    cfg = lib.read_roostrc()
    pulse = cfg.get("ROOST_PULSE_URL", "https://pulse.jimmyhoughjr.net")
    key = node_key(cfg)
    if not key:
        print("app-stats: no node key in ROOST_NODE_KEY or ROOST_NODE_KEY_FILE - skipping")
        return 0
    site = lib.site_dir(cfg)
    done = 0
    for config_path in sorted(site.glob("*/config.json")):
        try:
            config = json.load(open(config_path))
        except (OSError, ValueError):
            continue
        app = config.get("app") if isinstance(config, dict) else None
        if not isinstance(app, str) or not app:
            continue
        board_path = config_path.with_name("board.json")
        if not board_path.exists():
            print("app-stats: {} names {} and has no board.json - skipping".format(config_path.parent.name, app))
            continue
        feed, why = read_feed(pulse, key, app)
        if feed is None:
            print("app-stats: pulse did not answer for {} ({}) - leaving {} as-is".format(app, why, board_path.parent.name))
            continue
        board = lib.load_board(board_path)
        write_stats(board, feed, app)
        print("app-stats: {} tiles onto {} from pulse's feed for {}".format(len(board["sections"][0].get("items", [])) if board["sections"] else 0, board_path.parent.name, app))
        spec = config.get("map")
        if isinstance(spec, str) and spec:
            token = forge_token(cfg)
            if not token:
                print("app-stats: {} names map {} and this host holds no forge token - Features left as-is".format(board_path.parent.name, spec))
            else:
                tickets, why = read_map_tickets(cfg.get("ROOST_FORGE_URL", "https://forgejo.jimmyhoughjr.net"), token, spec)
                if tickets is None:
                    print("app-stats: the forge did not answer for {} ({}) - Features left as-is".format(spec, why))
                else:
                    write_features(board, tickets, spec)
                    print("app-stats: {} feature cards onto {} from {}".format(len(tickets), board_path.parent.name, spec))
        lib.save_board(board_path, board)
        done += 1
    if not done:
        print("app-stats: no board names an app in its config.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
