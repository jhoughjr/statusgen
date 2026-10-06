#!/usr/bin/env python3
"""app_stats.py - fill a product board's stats row from pulse's feed for its app (house#93).

A product board such as vault or watts names its app in its config.json, `"app": "vault"`. This reads pulse's one feed
for that app, GET /api/app/<name>, the same feed the coop's app page reads, so the board and the coop cannot disagree,
and writes the board's first stats section: whether it answers, its memory, its secrets owed a rotation, its jobs, and
last night's backup. The banner and every other section stay as a person wrote them.

Config (~/.roostrc or the environment):
  ROOST_PULSE_URL=https://pulse.example.net   # pulse, default https://pulse.jimmyhoughjr.net
  ROOST_NODE_KEY=...                           # pulse's node key, or
  ROOST_NODE_KEY_FILE=~/.roost_node_key        # the file that holds it, the default

The key goes to curl on standard input and never on a command line, so the process list never shows it.

Non-fatal by contract: no key -> skip; a board whose feed does not answer -> that board untouched; always exit 0.
"""
import datetime
import json
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
        lib.save_board(board_path, write_stats(board, feed, app))
        print("app-stats: {} tiles onto {} from pulse's feed for {}".format(len(board["sections"][0].get("items", [])) if board["sections"] else 0, board_path.parent.name, app))
        done += 1
    if not done:
        print("app-stats: no board names an app in its config.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
