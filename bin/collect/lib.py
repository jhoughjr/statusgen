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
    # Every collector's last act before the file lands, so a compare column
    # reaches the renderer in its declared order whichever collector wrote to
    # it last. See apply_column_order for why the board declares it.
    apply_column_order(board)
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


def compare_tile(board, column, label):
    """The first tile in `column` whose label starts with `label`, or None.

    This is how one collector asks what another collector already wrote into
    the column it shares. Two collectors that measure the same quantity use it
    to settle which number the column keeps."""
    for col in compare_columns(board, column):
        for tile in col.get("items", []):
            if str(tile.get("label", "")).startswith(label):
                return tile
    return None


def remove_compare_tile(board, column, label):
    """Delete every tile in `column` whose label starts with `label`.

    Returns how many tiles went. A tile no collector writes any more is worse
    than a missing tile: it holds the number its collector last wrote, no later
    run corrects it, and the board states it beside the live tiles with the
    same confidence."""
    removed = 0
    for col in compare_columns(board, column):
        items = col.get("items", [])
        keep = [t for t in items
                if not str(t.get("label", "")).startswith(label)]
        removed += len(items) - len(keep)
        col["items"] = keep
    return removed


def apply_column_order(board):
    """Sort every compare column's tiles into the order its section declares.

    A compare section is read ACROSS: "how does the client's coverage compare
    to the server's" is answered by two tiles sitting at the same height in two
    columns. Nothing held them at the same height. Each tile is written by a
    different collector, each appends when its tile is new, so a column's order
    was a fossil of the order the collectors first happened to run in — and the
    two columns fossilised differently. The reader was left hunting for the
    other half of each pair, which is the one thing the layout exists to spare
    them.

    The SECTION declares the order, not a collector: only the board knows what
    it is comparing, and a collector only ever sees its own tile. `order` is a
    list of label prefixes, matched the way every other tile lookup here
    matches. A label no prefix claims keeps its relative position at the end, so
    a new tile appears on the board without an edit here, and a board that
    declares no `order` is left exactly as it is.
    """
    for section in board.get("sections", []):
        if section.get("kind") != "compare":
            continue
        order = section.get("order")
        if not isinstance(order, list) or not order:
            continue

        def rank(tile, order=order):
            label = str(tile.get("label", ""))
            for i, prefix in enumerate(order):
                if label.startswith(str(prefix)):
                    return i
            return len(order)

        for col in section.get("columns", []):
            # Stable, so two tiles under one prefix ("CI build · dev" and
            # "CI build · master") keep the order their collector wrote them
            # in, which is the trunk preference order.
            col["items"] = sorted(col.get("items", []), key=rank)
    return board


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
                        match=None, since=None, meta=None):
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
        # `since` is a TIMESTAMP the renderer turns into an age at render time.
        # Never pass a pre-rendered "24m ago" as `n`: it is true only at the
        # instant it is written, and a board left open then insists on it for
        # hours while the run history below it says otherwise.
        # `meta` is the tile's provenance line: the evidence the headline was
        # read from — the SHA a verdict was measured at, say. It belongs on the
        # tile that states the headline, not on a tile of its own beside it,
        # because two tiles can drift apart and a reader has no way to tell
        # which one to believe.
        for key, val in (("tone", tone), ("href", href), ("since", since),
                         ("meta", meta)):
            if val is None:
                tile.pop(key, None)
            else:
                tile[key] = val
    return True


# Presentation a human sets on the board that a collector has no opinion about.
# A collector rebuilds its section from data every push, so anything hand-set
# on it is otherwise erased within the hour — which makes "put a logo on that
# section" an edit that silently doesn't stick.
# `collapsible`/`collapsed` are here for the same reason as `logo`, and the
# reason got sharper once collapsing worked on every section kind rather than
# only tables: "collapse that section" is a judgement about how the board reads,
# which a collector has no opinion about. Without these, hand-collapsing a
# collector-owned section (the CI console, say) works until the next status push
# and then silently reverts — an edit that appears to do nothing, which is
# exactly the failure this constant exists to prevent.
PRESERVED_SECTION_KEYS = ("logo", "collapsible", "collapsed")


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

# States that are not an OUTCOME — used where a verdict is being decided (the
# "CI build" and "Last green" tiles). A cancelled run is not evidence that
# anything passed or failed, so it must never set a badge.
#
# The push-based board update also runs INSIDE a CI run, so `gh run list`
# reports that very run as `in_progress`; treating that as a verdict would
# freeze a tile as "in progress" forever, since the update step cannot outlive
# the run it is reporting on.
CONSOLE_SKIP = {"in_progress", "queued", "waiting", "requested",
                "cancelled", "skipped"}

# States the FEED hides — a strictly smaller set, and the difference matters.
#
# The feed answers "what happened, in order"; the tiles answer "is it green".
# Those are different questions and used to share one filter, so a run
# cancelled by `cancel-in-progress` was dropped from the feed entirely. From
# the outside that reads as a build vanishing: you push, the run appears in
# "CI — running now", a newer push supersedes it, and it never lands in
# history. Reported exactly that way — "it did appear there and vanished".
#
# Superseded runs are now shown, toned down and labelled, so the record is
# complete. Still hidden: queued/in-progress, which have not happened yet and
# have their own live section.
FEED_SKIP = {"in_progress", "queued", "waiting", "requested"}

# A skipped run built nothing. Its jobs' conditions were false, so it never
# reached a runner. A comment on a pull request can produce one, and three
# comments in a minute produced three of them on 2026-08-18, which filled a
# repo's whole allowance in this feed and pushed every real build out of sight.
# `cancelled` is deliberately not here: that run WAS building and something
# retired it, which is a fact about builds and belongs in the feed.
FEED_NON_BUILD = {"skipped"}


def gh_runs(repo, limit):
    # headSha is here for the "Last green" tile (ci_status.py), which names the
    # commit a repo was last green at. Extra fields are ignored by every other
    # caller, so this stays a superset rather than a second fetch.
    r = sh(["gh", "run", "list", "--repo", repo, "--limit", str(limit),
            "--json", "status,conclusion,headBranch,event,createdAt,updatedAt,url,headSha,databaseId,workflowName"])
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


def self_run_from(cfg):
    """The run this collector is executing INSIDE, if any, as
    (repo, id, conclusion) — else None.

    Set by CI immediately before the board push (see Phoenix's
    scripts/ci/update-board.sh). It exists because of a blind spot that is
    invisible until you look for it: the board step runs *within* the job it is
    reporting on, so `gh run list` reports that job as `in_progress` and every
    filter drops it. A run therefore can never appear in the board it
    publishes — it surfaces only when some later push happens to refresh the
    feed, and if nothing else pushes for hours it looks like the build simply
    vanished. Which is exactly how it was reported.

    CI already knows the answer `gh` cannot give yet: its own run id and its own
    outcome. Passing them in lets the feed show the run that wrote it.
    """
    repo = (cfg.get("ROOST_CI_SELF_REPO") or "").strip()
    run_id = (cfg.get("ROOST_CI_SELF_RUN_ID") or "").strip()
    outcome = (cfg.get("ROOST_CI_SELF_OUTCOME") or "").strip()
    if not (repo and run_id and outcome):
        return None
    return (repo, run_id, outcome)


def apply_self_run(repo, runs, self_run):
    """Stamp the in-flight run with the outcome CI told us, so it stops looking
    like an unfinished run to every downstream filter. Returns `runs`
    unchanged when there is nothing to apply."""
    if not self_run or not runs:
        return runs
    self_repo, self_id, outcome = self_run
    if self_repo != repo:
        return runs
    out = []
    for r in runs:
        if str(r.get("databaseId", "")) == str(self_id):
            r = {**r, "status": "completed", "conclusion": outcome}
        out.append(r)
    return out


# A run's runner never changes once assigned, so names persist across pushes.
# Without the file, every push re-paid one REST call per feed row for runs that
# finished days ago. Only real names persist: an empty answer can mean "still
# unassigned", so it stays process-local and is asked again next push.
_RUNNER_CACHE_FILE = os.path.expanduser("~/.cache/statusgen/runner-names.json")
_RUNNER_CACHE = None


def _runner_cache():
    global _RUNNER_CACHE
    if _RUNNER_CACHE is None:
        try:
            _RUNNER_CACHE = {tuple(k.split("\x1f", 1)): v
                             for k, v in json.load(open(_RUNNER_CACHE_FILE)).items()}
        except (OSError, ValueError):
            _RUNNER_CACHE = {}
    return _RUNNER_CACHE


def _runner_cache_save(cache):
    try:
        os.makedirs(os.path.dirname(_RUNNER_CACHE_FILE), exist_ok=True)
        json.dump({"\x1f".join(k): v for k, v in cache.items() if v},
                  open(_RUNNER_CACHE_FILE, "w"))
    except OSError:
        pass


def gh_run_runner(repo, run_id):
    """Short name of the machine a run executed on — "mini", "macbook" — or
    None when it cannot be determined.

    `gh run list` does not carry this, and neither does `gh run view --json
    jobs`; only the REST jobs endpoint does. That is one extra call per row, so
    results are cached for the life of the process (a collector run), and any
    failure returns None rather than costing the whole feed.

    Worth the call: with two runners, "which box ran this" is the first
    question asked about a build that behaved differently from its neighbour —
    and a job that never got assigned shows no runner at all, which is itself
    the answer.
    """
    if not run_id:
        return None
    cache = _runner_cache()
    key = (repo, str(run_id))
    if key in cache:
        return cache[key]
    r = sh(["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs",
            "-q", ".jobs[0].runner_name // empty"], timeout=20)
    name = r.stdout.strip() if r.returncode == 0 else ""
    # "jimmys-mac-mini" -> "mini"; the shared prefix is noise on every row.
    short = name.rsplit("-", 1)[-1] if name else None
    cache[key] = short
    if short:
        _runner_cache_save(cache)
    return short


def newer_run_exists(run, runs):
    """A newer run on the same branch and workflow is the only evidence that this run was superseded,
    and it must have started while this run was still in progress - that is what cancel-in-progress does.
    A push hours after a timeout is not a replacement, and without `updatedAt` the overlap is unknowable,
    so both cases keep the plain label."""
    ended = run.get("updatedAt") or ""
    if not ended:
        return False
    for other in runs:
        if other is run:
            continue
        if other.get("headBranch") != run.get("headBranch"):
            continue
        if other.get("workflowName") != run.get("workflowName"):
            continue
        started = other.get("createdAt") or ""
        if (run.get("createdAt") or "") < started <= ended:
            return True
    return False


def console_lines(sources, self_run=None, fetched=None):
    """sources: [(repo, label, limit)] or [(repo, label, limit, logo)] →
    statusgen console-section lines.

    The 4-tuple form tags every row with a stack mark. One merged feed beats
    two consoles for reading "what happened, in order" — but only once each row
    says which stack it belongs to.

    "In order" is load-bearing and used not to be true. Rows were appended one
    repo at a time, so the feed read as per-repo blocks: a server build from an
    hour ago sat BELOW a client build from yesterday, purely because the client
    repo was configured first. Read top-down — which is the only way anyone
    reads a feed titled "recent runs" — that looks like this morning's builds
    never happened. Runs are now interleaved by timestamp across every source.

    The per-repo `limit` still applies before merging: it means "the last N from
    this repo", so a busy repo cannot crowd a quiet one out of the feed
    entirely. The watch chips stay at the end, after the runs, since they are
    controls rather than events."""
    lines = []
    watches = []
    for source in sources:
        repo, label, limit = source[0], source[1], source[2]
        logo = source[3] if len(source) > 3 else None
        # Over-fetch: on a busy branch many recent runs are still in progress,
        # so pull well past `limit` to still land `limit` rows after filtering.
        # A caller that already fetched the repo's window passes it in, so one
        # push costs one `gh run list` per repo instead of two.
        data = (fetched or {}).get(repo) or gh_runs(repo, max(limit * 6, 30))
        if data is None:
            continue
        data = apply_self_run(repo, data, self_run)
        shown = 0
        for r in data:
            state = r.get("conclusion") or r.get("status") or ""
            if state in FEED_SKIP or state in FEED_NON_BUILD:
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
            # Say WHY a run has no result, rather than showing a bare "cancelled" the reader has to account for.
            # A `cancel-in-progress` retirement leaves a newer run on the same branch and workflow, so that newer run is the required evidence.
            # A timeout or a hand cancel leaves no newer run.
            # The old label called those "superseded" too, and a 2026-08-19 release timeout read as "a newer push replaced this".
            if state == "cancelled" and newer_run_exists(r, data):
                line["meta"] = f"· superseded · {event}" if event else "· superseded"
            elif event:
                line["meta"] = f"· {event}"
            # Which box ran it. Absent means the job never reached a runner —
            # which is exactly what a GitHub-side assignment failure looks like,
            # and is worth being able to see rather than infer.
            runner = gh_run_runner(repo, r.get("databaseId"))
            if runner:
                line["meta"] = f"{line.get('meta', '')} · {runner}".strip()
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
            watches.append(watch)
    # Newest first, across repos. A row with no timestamp sorts last rather
    # than crashing the sort or silently jumping to the top.
    lines.sort(key=lambda l: l.get("ts") or "", reverse=True)
    return lines + watches
