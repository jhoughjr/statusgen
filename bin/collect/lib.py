"""collect/lib.py — shared primitives for statusgen board collectors.

Collectors are small scripts that patch live numbers into a board.json before
a status push. They share these rules:
  - config comes from ~/.roostrc (simple KEY=VALUE, shell-style), never code
  - any failure is NON-FATAL: leave the board untouched, exit 0
  - a collector with no config prints a skip note and exits 0
"""
import json
import os
import re
import subprocess
import pathlib

ROOSTRC = os.path.expanduser("~/.roostrc")


def read_roostrc():
    """Parse ~/.roostrc (KEY=VALUE lines, shell-style). Expands ~ and $HOME.
    Environment variables override file values."""
    cfg = {}
    if os.path.exists(ROOSTRC):
        for line in open(ROOSTRC):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            v = v.replace("$HOME", os.path.expanduser("~"))
            cfg[k.strip()] = os.path.expanduser(v)
    for k, v in os.environ.items():
        if k.startswith("ROOST_"):
            cfg[k] = v
    return cfg


def site_dir(cfg=None):
    cfg = cfg or read_roostrc()
    return pathlib.Path(cfg.get("ROOST_STATUS_SITE",
                                os.path.expanduser("~/status-site")))


def sh(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


# ── board IO ─────────────────────────────────────────────────────────────

def load_board(path):
    return json.load(open(path))


def save_board(path, board):
    json.dump(board, open(path, "w"), indent=2)
    open(path, "a").write("\n")


def board_at(site, rel, before="7 days ago"):
    """The board as of a past commit (rolling baseline for deltas).
    Falls back to the oldest commit when history is younger than `before`."""
    site = str(site)
    sha = sh(["git", "log", "-1", f"--before={before}", "--format=%H",
              "--", rel], site).stdout.strip()
    if not sha:
        lines = sh(["git", "log", "--reverse", "--format=%H",
                    "--", rel], site).stdout.strip().splitlines()
        sha = lines[0] if lines else None
    if not sha:
        return None
    r = sh(["git", "show", f"{sha}:{rel}"], site)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def find_stat(board, label_prefix, column=0):
    """Numeric value of a tile whose label starts with `label_prefix`.
    Handles both the compare layout (first column by default) and the
    legacy untitled hero-stats layout."""
    if not board:
        return None
    for s in board.get("sections", []):
        if s.get("kind") == "compare":
            for i in s["columns"][column]["items"]:
                if str(i.get("label", "")).startswith(label_prefix):
                    try:
                        return int(str(i["n"]).replace(",", "").lstrip("+"))
                    except ValueError:
                        return None
    for s in board.get("sections", []):  # legacy hero stats (untitled)
        if s.get("kind") == "stats" and not s.get("title"):
            for i in s.get("items", []):
                if str(i.get("label", "")).startswith(label_prefix):
                    try:
                        return int(str(i["n"]).replace(",", "").lstrip("+"))
                    except ValueError:
                        return None
    return None


def set_compare_tile(board, match, n, label=None, tone=None):
    """Set the value (and optionally label/tone) of the compare tile whose
    current label starts with `match`, searching every column. Returns True
    when a tile was found and updated — collectors use this to wire a
    previously hardcoded tile to live data. A tile the board doesn't have is a
    silent no-op (the tile was deleted, or this board doesn't carry it)."""
    for s in board.get("sections", []):
        if s.get("kind") != "compare":
            continue
        for col in s.get("columns", []):
            for tile in col.get("items", []):
                if str(tile.get("label", "")).startswith(match):
                    tile["n"] = str(n)
                    if label is not None:
                        tile["label"] = label
                    if tone is not None:
                        tile["tone"] = tone
                    return True
    return False


def upsert_section(board, title, section, after_kind="compare"):
    """Replace the section with this title, or insert it after the first
    section of `after_kind` (top if none)."""
    secs = [s for s in board.get("sections", []) if s.get("title") != title]
    i = next((idx for idx, s in enumerate(secs) if s.get("kind") == after_kind), -1)
    secs.insert(i + 1, section)
    board["sections"] = secs
    return board


# ── coverage ─────────────────────────────────────────────────────────────

def line_coverage(repo, min_mtime=None):
    """Line % from an istanbul/v8 coverage-summary.json, or None.

    min_mtime: when set, a summary older than this timestamp is treated as
    stale leftovers from a previous run and ignored — a status push must
    report current state, never a number that predates the run.
    """
    p = os.path.join(repo, "coverage", "coverage-summary.json")
    if not os.path.exists(p):
        return None
    if min_mtime is not None and os.path.getmtime(p) < min_mtime:
        return None
    return round(json.load(open(p))["total"]["lines"]["pct"])


# ── test runs ────────────────────────────────────────────────────────────

def test_count(repo, cmd):
    """Passing-test count from running `cmd` in `repo`. Understands vitest
    output, with a generic '<n> passed/passing' fallback."""
    r = sh(cmd.split(), repo)
    out = r.stdout + r.stderr
    m = re.search(r"Tests\s+(\d+)\s+passed", out)
    if not m:
        m = re.search(r"(\d+)\s+pass(?:ed|ing)", out)
    return int(m.group(1)) if m else None


# ── GitHub Actions ───────────────────────────────────────────────────────

TONE = {
    "success": "go",
    "failure": "you", "startup_failure": "you", "timed_out": "you",
    "in_progress": "wip", "queued": "wip", "waiting": "wip", "requested": "wip",
    "cancelled": "none", "skipped": "none", "neutral": "none",
}

# States we never surface in the console. The push-based board update runs
# INSIDE a CI run, so `gh run list` reports that very run as `in_progress` —
# showing it would freeze the console as "in progress" forever, even though the
# run finishes green moments later (its own update step can't outlive it).
# Cancelled/skipped are concurrency-superseded churn on a busy branch, not
# outcomes. Filtering both leaves a clean log of the latest real results; the
# currently-building run reappears as success/failure on the next refresh.
CONSOLE_SKIP = {"in_progress", "queued", "waiting", "requested",
                "cancelled", "skipped"}


def gh_runs(repo, limit):
    r = sh(["gh", "run", "list", "--repo", repo, "--limit", str(limit),
            "--json", "status,conclusion,headBranch,event,createdAt,url"])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def console_lines(sources):
    """sources: [(repo, label, limit)] → statusgen console-section lines."""
    lines = []
    for repo, label, limit in sources:
        # Over-fetch: on a busy branch most recent runs are in-progress or
        # concurrency-cancelled, so pull well past `limit` to still land
        # `limit` real outcomes after CONSOLE_SKIP filtering.
        data = gh_runs(repo, max(limit * 6, 30))
        if data is None:
            continue
        shown = 0
        for r in data:
            state = r.get("conclusion") or r.get("status") or ""
            if state in CONSOLE_SKIP:
                continue
            if shown >= limit:
                break
            # createdAt is UTC ISO-8601 (…Z). Pass it as `ts` so the renderer
            # localizes it to the viewer's timezone (fmtTime); only the trigger
            # event goes in meta. (Baking a "… UTC" string here showed UTC to
            # everyone.)
            line = {
                "status": state.replace("_", " ") or "unknown",
                "tone": TONE.get(state, "none"),
                "text": f"{label} · {r.get('headBranch', '?')}",
            }
            event = r.get("event", "")
            if event:
                line["meta"] = f"· {event}"
            ts = r.get("createdAt", "")
            if ts:
                line["ts"] = ts
            url = r.get("url", "")
            if url:
                line["href"] = url
            lines.append(line)
            shown += 1
        # A terminal watch line per repo: the cmd renders as a
        # copy-to-clipboard chip; with no run id, gh prompts with
        # in-progress runs — the "watch it live" gesture.
        if data:
            lines.append({
                "status": "watch", "tone": "none", "text": label,
                "cmd": f"gh run watch -R {repo}",
            })
    return lines
