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


def sh(args, cwd=None, timeout=None):
    """Run a command, capturing output. A timeout comes back as a non-zero
    result rather than an exception, so a collector's normal "returncode != 0 →
    leave the board alone" path covers a hung command too — nothing that talks
    to a network (a git fetch against an unreachable remote, say) should be
    able to wedge a status push."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timed out")
    except (OSError, ValueError) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


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


def compare_columns(board, match=None):
    """The compare columns of `board`, optionally only those whose title
    contains `match` (case-insensitive). A compare board is one section with N
    columns — "Phoenix ⟷ MWServer" — so `match` is how a collector says *which
    side of the board it owns* instead of writing into whichever column happens
    to hold a similarly-named tile."""
    out = []
    for s in board.get("sections", []):
        if s.get("kind") != "compare":
            continue
        for col in s.get("columns", []):
            if match is None or match.lower() in str(col.get("title", "")).lower():
                out.append(col)
    return out


def set_compare_tile(board, match, n, label=None, tone=None, column=None):
    """Set the value (and optionally label/tone) of the compare tile whose
    current label starts with `match`. Returns True when a tile was found and
    updated — collectors use this to wire a previously hardcoded tile to live
    data. A tile the board doesn't have is a silent no-op (the tile was
    deleted, or this board doesn't carry it).

    `column` scopes the search to columns whose title contains it. Pass it
    whenever the value is repo-specific: without it the search spans every
    column and stops at the first label match, which on a two-repo board means
    one repo's number can silently land in the other repo's column."""
    for col in compare_columns(board, column):
        for tile in col.get("items", []):
            if str(tile.get("label", "")).startswith(match):
                tile["n"] = str(n)
                if label is not None:
                    tile["label"] = label
                if tone is not None:
                    tile["tone"] = tone
                return True
    return False


def upsert_compare_tile(board, column, label, n, tone=None, href=None,
                        match=None):
    """Create-or-update a tile in the compare column whose title contains
    `column`. Matches an existing tile by `match` (default: `label`) as a
    prefix, so a collector can rename its own tile without orphaning the old
    one; appends when there is no match.

    set_compare_tile only ever updates — it is for wiring up tiles a human
    already placed. This is for a column a collector *fills*, where the tile
    may not exist yet. Returns True if a column was found."""
    cols = compare_columns(board, column)
    if not cols:
        return False
    prefix = match if match is not None else label
    for col in cols:
        items = col.setdefault("items", [])
        tile = next((t for t in items
                     if str(t.get("label", "")).startswith(prefix)), None)
        if tile is None:
            tile = {}
            items.append(tile)
        tile["n"] = str(n)
        tile["label"] = label
        # None clears: a tile that had a link last run but has none now must
        # not keep pointing at a stale run.
        for key, val in (("tone", tone), ("href", href)):
            if val is None:
                tile.pop(key, None)
            else:
                tile[key] = val
    return True


# Presentation a human sets on the board that a collector has no opinion about.
# A collector rebuilds its section from data every push, so anything hand-set
# on it is otherwise erased within the hour — which makes "put a logo on that
# section" an edit that silently doesn't stick.
PRESERVED_SECTION_KEYS = ("logo",)


def upsert_section(board, title, section, after_kind="compare"):
    """Replace the section with this title, or insert it after the first
    section of `after_kind` (top if none).

    Presentational keys the board already carried (PRESERVED_SECTION_KEYS) are
    carried over when the incoming section doesn't set them — a collector owns
    its numbers, not how the board chooses to label it."""
    secs = list(board.get("sections", []))
    at = next((i for i, s in enumerate(secs) if s.get("title") == title), None)

    if at is not None:
        for key in PRESERVED_SECTION_KEYS:
            if key in secs[at] and key not in section:
                section[key] = secs[at][key]
        # Replace WHERE IT ALREADY IS. `after_kind` places a section the board
        # has never carried; it is not a claim about where an existing one
        # belongs. Re-homing on every push made running order collector-driven
        # and un-authorable: each collector yanked its section back up to just
        # below the compare block, so hand-arranged order survived exactly
        # until the next status run.
        secs[at] = section
    else:
        i = next((idx for idx, s in enumerate(secs)
                  if s.get("kind") == after_kind), -1)
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
    # headSha is here for the "Last green" tile (ci_status.py), which names the
    # commit a repo was last green at. Extra fields are ignored by every other
    # caller, so this stays a superset rather than a second fetch.
    r = sh(["gh", "run", "list", "--repo", repo, "--limit", str(limit),
            "--json", "status,conclusion,headBranch,event,createdAt,url,headSha"])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


# Timing fields on top of gh_runs' set. `startedAt` is when the run actually
# began (a queued run's createdAt can precede it by minutes on a busy account),
# so duration is measured startedAt→updatedAt, not createdAt→updatedAt.
RUN_FIELDS = ("status,conclusion,headBranch,event,createdAt,startedAt,"
              "updatedAt,headSha,url,workflowName,displayTitle")


def gh_run_history(repo, limit=20, branch=None, event=None, workflow=None):
    """Runs for one repo, narrowed server-side by branch/event/workflow.

    ci_status.py wants "whatever ran last, anywhere" — this wants "the
    pipeline", i.e. one workflow on one branch, so successive entries are
    comparable to each other. Returns None when `gh` is unavailable or errors,
    which every caller treats as "leave the board alone"."""
    args = ["gh", "run", "list", "--repo", repo, "--limit", str(limit),
            "--json", RUN_FIELDS]
    if branch:
        args += ["--branch", branch]
    if event:
        args += ["--event", event]
    if workflow:
        args += ["--workflow", workflow]
    r = sh(args)
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def run_duration(run):
    """Seconds a run took, or None if it is unfinished or the stamps are
    unparseable. GitHub's stamps are UTC ISO-8601 with a literal Z, which
    fromisoformat only learned to parse in 3.11 — hence the +00:00 swap."""
    def parse(value):
        if not value:
            return None
        try:
            return __import__("datetime").datetime.fromisoformat(
                str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    start = parse(run.get("startedAt")) or parse(run.get("createdAt"))
    end = parse(run.get("updatedAt"))
    if start is None or end is None:
        return None
    secs = (end - start).total_seconds()
    return secs if secs >= 0 else None


def fmt_duration(secs):
    """Seconds → a compact human duration: 45s, 6m, 5m36s, 1h04m."""
    if secs is None:
        return None
    secs = int(round(secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        m, s = divmod(secs, 60)
        return f"{m}m" if s == 0 else f"{m}m{s:02d}s"
    h, rem = divmod(secs, 3600)
    return f"{h}h{rem // 60:02d}m"


def fmt_age(iso, now=None):
    """UTC ISO-8601 stamp → a compact age: "just now", "9m ago", "3h ago",
    "2d ago". None when unparseable, so callers can omit rather than print a
    misleading zero.

    Board tiles carry a plain string (no `ts` the renderer could localize, the
    way console lines do), so the age is baked here. It is relative, which is
    what makes it safe to bake — unlike an absolute time, it reads correctly in
    every timezone."""
    import datetime
    if not iso:
        return None
    try:
        then = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    secs = (now - then).total_seconds()
    if secs < 0:
        return "just now"
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def console_lines(sources):
    """sources: [(repo, label, limit)] or [(repo, label, limit, logo)] →
    statusgen console-section lines.

    The 4-tuple form tags every row with a stack mark. One merged feed beats
    two consoles for reading "what happened, in order" — but only once each row
    says which stack it belongs to."""
    lines = []
    for source in sources:
        repo, label, limit = source[0], source[1], source[2]
        logo = source[3] if len(source) > 3 else None
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
            if logo:
                line["logo"] = logo
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
            watch = {"status": "watch", "tone": "none", "text": label,
                     "cmd": f"gh run watch -R {repo}"}
            if logo:
                watch["logo"] = logo
            lines.append(watch)
    return lines
