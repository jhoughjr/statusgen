#!/usr/bin/env python3
"""loc.py — patch lines-of-code charts on a board from the working tree.

Why this exists: LOC sections were the one part of a board with no collector.
They were hand-written, so they froze the day someone last edited them and then
quietly kept quoting a fortnight-old commit while the rest of the board stayed
live. This makes them regenerate on every status push like everything else.

Config comes from a JSON file pointed at by ROOST_LOC_CONFIG (nothing hardcodes
a repo path). No config → print a skip note and exit 0, like every collector.

    {
      "board": "clauffice",              # board slug under the status site
      "charts": [
        { "title": "Codebase",           # patched by section title
          "buckets": [
            { "label": "App tests", "root": "~/repos/Phoenix-Electron",
              "paths": ["src"], "ext": [".ts", ".tsx"], "tests": "only",
              "fill": "code" },
            { "label": "App source", "root": "~/repos/Phoenix-Electron",
              "paths": ["src"], "ext": [".ts", ".tsx"], "tests": "exclude",
              "exclude": ["src/sdk"], "fill": "code" }
          ],
          "note": "This week: {commits_7d:Phoenix-Electron} commits. "
                  "{total_h} lines counted from {sha:Phoenix-Electron}." }
      ]
    }

Bucket fields:
  label     bar/slice label — also how a note refers to it
  root      repo or directory to scan (~ expanded)
  paths     subpaths of root to include (default: all of root). May contain
            glob characters — "Sources/*/GeneratedSources" beats enumerating
            modules that come and go.
  exclude   subpaths to skip, relative to root (default: none); globs too
  ext       file extensions to count (default: every file)
  tests     "both" (default) | "only" | "exclude" — a file is a test if its
            name matches *.test.* / *.spec.* or it sits under a test dir
  fill      barchart fill class; tone   pie slice tone

`.git`, `node_modules`, and `generated` are always pruned — same exclusions
git-stats.sh uses, so the two agree.

Note placeholders (a chart's `note` is a format template, all optional):
  {total} {total_h}          chart total, raw and humanized (139,412 / 139.4k)
  {n}                        number of buckets
  {stamp}                    today, YYYY-MM-DD
  {b:Label} {bh:Label}       one bucket's lines, raw and humanized
  {commits_7d:Label}         commits in that bucket's repo, last 7 days
  {sha:Label}                that repo's short HEAD, as "branch@abc1234"

A chart whose section is absent from the board is skipped with a note, never
an error — a board may adopt a chart before the section exists.
"""
import json
import os
import pathlib
import re
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

PRUNE = {".git", "node_modules", "generated"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
TEST_FILE = re.compile(r"\.(test|spec)\.[^.]+$")


def expand(root, patterns):
    """Resolve a bucket's `paths`/`exclude` entries against root, expanding any
    that contain glob characters.

    Enumerating directories by hand rots: MWServer-Models grew a fourth
    `Sources/*/GeneratedSources` module, and a hardcoded list of three silently
    under-counted it by ~12k lines — the precise sort of confident-but-wrong
    number this collector exists to prevent. A glob absorbs the fifth."""
    out = []
    for p in patterns:
        if any(ch in p for ch in "*?["):
            out.extend(sorted(root.glob(p)))
        else:
            out.append(root / p)
    return out


def is_test(path, root):
    """A file counts as a test if it's named like one or lives under a test
    directory anywhere between root and itself."""
    if TEST_FILE.search(path.name):
        return True
    return any(part.lower() in TEST_DIRS for part in path.relative_to(root).parts[:-1])


def count_lines(path):
    """Lines in one file. Unreadable or binary files count 0 rather than
    breaking a whole push."""
    try:
        with open(path, "rb") as fh:
            return fh.read().count(b"\n")
    except OSError:
        return 0


def bucket_lines(bucket):
    """Total lines matching one bucket's filters, or None if the root isn't on
    this machine.

    None matters: two machines push this site (laptop + mini) and they don't
    have the same repos cloned. Counting a missing repo as 0 would let whichever
    machine lacks it flatten the bar on every push — a wrong number that looks
    authoritative, which is worse than the stale one we're replacing. The
    caller keeps the previous value instead."""
    root = pathlib.Path(os.path.expanduser(bucket.get("root", ""))).resolve()
    if not root.is_dir():
        print(f"loc: {bucket.get('label')!r}: {root} not on this machine — keeping previous value")
        return None

    exts = tuple(bucket.get("ext") or [])
    mode = bucket.get("tests", "both")
    excluded = {p.resolve() for p in expand(root, bucket.get("exclude", []))}
    # "no paths configured" means the whole root; "paths configured that matched
    # nothing" means zero. Collapsing the two would let one stale glob quietly
    # count an entire repo into a bucket meant for a subdirectory.
    patterns = bucket.get("paths", [])
    roots = expand(root, patterns) if patterns else [root]
    if patterns and not roots:
        print(f"loc: {bucket.get('label')!r}: paths {patterns} matched nothing under {root} — counted 0")
        return 0

    total = 0
    for start in roots:
        if not start.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            here = pathlib.Path(dirpath)
            dirnames[:] = [d for d in dirnames
                           if d not in PRUNE and (here / d).resolve() not in excluded]
            for name in filenames:
                fpath = here / name
                if exts and not name.endswith(exts):
                    continue
                if mode != "both":
                    t = is_test(fpath, root)
                    if (mode == "only") != t:
                        continue
                total += count_lines(fpath)
    return total


def human(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def git_facts(root):
    """(commits_7d, "branch@sha") for a repo, or (0, "?") when it isn't one."""
    root = os.path.expanduser(root)
    log = lib.sh(["git", "-C", root, "log", "--since=7 days ago", "--oneline"])
    if log.returncode != 0:
        return 0, "?"
    commits = len([l for l in log.stdout.splitlines() if l.strip()])
    sha = lib.sh(["git", "-C", root, "rev-parse", "--short", "HEAD"]).stdout.strip()
    branch = lib.sh(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    return commits, f"{branch}@{sha}" if sha else "?"


def render_note(template, buckets, counts):
    """Substitute the documented placeholders. An unknown one is left verbatim
    rather than raising — a typo shows up on the board instead of killing the
    push."""
    if not template:
        return None
    total = sum(counts.values())
    by_label = {b.get("label"): b for b in buckets}
    facts = {}

    def fact(label):
        if label not in facts:
            b = by_label.get(label)
            facts[label] = git_facts(b["root"]) if b and b.get("root") else (0, "?")
        return facts[label]

    def sub(m):
        key, _, arg = m.group(1).partition(":")
        if key == "total":
            return f"{total:,}"
        if key == "total_h":
            return human(total)
        if key == "n":
            return str(len(buckets))
        if key == "stamp":
            return datetime.date.today().isoformat()
        if key == "b":
            return f"{counts.get(arg, 0):,}"
        if key == "bh":
            return human(counts.get(arg, 0))
        if key == "commits_7d":
            return str(fact(arg)[0])
        if key == "sha":
            return fact(arg)[1]
        return m.group(0)

    return re.sub(r"\{([^{}]+)\}", sub, template)


def patch_chart(board, chart):
    """Patch one barchart's series or one pie's slices. Returns True if the
    section was found."""
    title = chart.get("title")
    buckets = chart.get("buckets") or []
    for section in board.get("sections", []):
        if section.get("title") != title:
            continue

        key = "slices" if section.get("kind") == "pie" else "series"
        previous = {e.get("label"): e.get("value")
                    for e in section.get(key, []) if isinstance(e, dict)}

        counted = {b.get("label"): bucket_lines(b) for b in buckets}
        if all(v is None for v in counted.values()):
            print(f"loc: {title}: no bucket roots on this machine — left untouched")
            return True
        # A missing root falls back to what the board already showed (0 only if
        # the board never had a value for that label).
        counts = {label: (v if v is not None else previous.get(label, 0))
                  for label, v in counted.items()}
        # Biggest first — both charts read as a magnitude ranking.
        ordered = sorted(buckets, key=lambda b: counts.get(b.get("label"), 0), reverse=True)

        extra = "tone" if key == "slices" else "fill"
        section[key] = [
            {"label": b["label"], "value": counts[b["label"]],
             **({extra: b[extra]} if b.get(extra) else {})}
            for b in ordered
        ]
        note = render_note(chart.get("note"), buckets, counts)
        if note:
            section["note"] = note
        # Counted fresh every push, so it can't be stale — drop any hand-era
        # asOf stamp rather than leaving the board claiming a July date.
        section.pop("asOf", None)
        missing = sum(1 for v in counted.values() if v is None)
        tail = f" ({missing} kept from previous)" if missing else ""
        print(f"loc: {title}: {sum(counts.values()):,} lines across {len(buckets)} buckets{tail}")
        return True
    print(f"loc: no {title!r} section on board — nothing to patch")
    return False


def main():
    cfg = lib.read_roostrc()
    config_path = cfg.get("ROOST_LOC_CONFIG")
    if not config_path:
        print("loc: ROOST_LOC_CONFIG not set — skipping")
        return 0
    config_path = os.path.expanduser(config_path)
    if not os.path.exists(config_path):
        print(f"loc: config {config_path} not found — skipping")
        return 0

    conf = json.load(open(config_path))
    slug = conf.get("board") or cfg.get("ROOST_STATS_BOARD")
    if not slug:
        print("loc: no board slug (config 'board' or ROOST_STATS_BOARD) — skipping")
        return 0

    board_path = lib.site_dir(cfg) / slug / "board.json"
    if not board_path.exists():
        print(f"loc: {board_path} not found — skipping")
        return 0

    board = lib.load_board(board_path)
    patched = sum(bool(patch_chart(board, c)) for c in conf.get("charts", []))
    if patched:
        lib.save_board(board_path, board)
    print(f"loc: patched {patched} chart(s) on {slug}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"loc: non-fatal error: {e}")
        sys.exit(0)
