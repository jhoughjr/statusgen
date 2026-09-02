#!/usr/bin/env python3
"""ci_status.py — surface CI runs on a board as a scrolling "CI — runs" console
section, pulled live from GitHub via `gh` and from Forgejo via its API.

The console is rendered from the run ledger, so it holds every run on record
rather than a window of the last few per repo, and it is capped at RUNS_ROWS
rows so carrying the record costs it no more space than the window did.

Config (~/.roostrc):
  ROOST_CI_BOARD=clauffice                      # board dir under the status site
  ROOST_CI_REPOS=owner/repo:Label:4[:logo],owner/other:Other:3[:logo]

  # Repos whose CI runs on the Forgejo instance instead. Same spec syntax, and
  # they join the same feed, so one board reports both forges. All three keys
  # are needed together, and unset means the board behaves as it always did.
  ROOST_CI_FORGEJO_URL=https://forgejo.example.net
  ROOST_CI_FORGEJO_TOKEN=...                    # an API token for that instance
  ROOST_CI_FORGEJO_REPOS=owner/repo:Label:4[:logo]

`logo` tags every one of that repo's rows with a stack mark (swift/ts/js), so
one merged chronological feed still says which side each run belongs to.

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import datetime
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

LEDGER_MAX = 200
CHART_DAYS = 14

# The board's runs console. It was "CI — recent runs" over a sliding window of
# the last few runs per repo; it now carries the record itself and scrolls.
# `upsert_section` finds a section by title, so the old name has to be renamed
# in place rather than left behind, or the board grows a second copy.
RUNS_TITLE = "CI — runs"
RUNS_TITLE_WAS = "CI — recent runs"
# Rows shown before the console scrolls. Ten is what the window used to render
# (eight runs and two watch chips), so the block keeps the height it had.
RUNS_ROWS = 10
# How far back to look on a trunk the main window missed. A branch that builds
# rarely still collects bot runs — MWServer's master carries dozens on issue
# comments, all skipped — and the filter that drops them runs after this fetch,
# so the reach has to clear them to find the build underneath.
QUIET_TRUNK_DEPTH = 60
TEMPLATE = pathlib.Path(__file__).resolve().parent.parent.parent / "renderer" / "board.template.html"


def parse_sources(spec):
    """"owner/repo[:Label[:limit[:logo]]], …" → [(repo, label, limit, logo)]."""
    out = []
    for part in spec.split(","):
        bits = [b.strip() for b in part.strip().split(":")]
        if not bits or not bits[0]:
            continue
        repo = bits[0]
        label = bits[1] if len(bits) > 1 and bits[1] else repo.split("/")[-1]
        try:
            limit = int(bits[2]) if len(bits) > 2 and bits[2] else 4
        except ValueError:
            limit = 4
        logo = bits[3] if len(bits) > 3 and bits[3] else None
        out.append((repo, label, limit, logo))
    return out


# Branches whose result is the project's headline, in preference order.
#
# The "CI build" tile used to be set from the newest run on ANY branch, so a
# single failing pull request turned the board's badge to ✗ — the project read
# as broken when nothing on a trunk had broken at all. (Observed 2026-08-05:
# PR #235's red run sat at the top of the feed and flipped the badge, while
# dev's newest run was green.)
#
# Order beats recency on purpose, and dev leads: dev is the working default and
# the board headline, main is the stable record. main also runs on a daily
# schedule at a SHA that may not have moved in days, so ranking by recency
# alone would let a nightly cron on main paint over a red dev.
TRUNKS_DEFAULT = ("dev", "main", "master")


def trunks_key(name):
    """The config key for a source or a label: "MWServer" → the suffix of
    ROOST_CI_TRUNKS_MWSERVER, "jimmy/MWServer-Mirror" → ..._JIMMY_MWSERVER_MIRROR.
    Anything not a letter or digit becomes `_`, so a name with a slash, a space
    or a dash still names a key a shell-style file can hold."""
    return "ROOST_CI_TRUNKS_" + re.sub(r"[^A-Za-z0-9]", "_", name or "").upper()


def parse_trunks(cfg, label=None, repo=None):
    """"dev,main" → ["dev", "main"]; unset → TRUNKS_DEFAULT.

    Resolved per SOURCE first, then per label, then globally.

    Per source because one project's trunks can come from two forges. MWServer
    builds dev on the Forgejo mirror and master on GitHub, and both sources
    write into one column under one label — so a per-label answer cannot give
    them different trunks, and whichever ran last would take the column.

        ROOST_CI_TRUNKS_JIMMY_MWSERVER_MIRROR=dev
        ROOST_CI_TRUNKS_AUSTIN_MACWORKS_MWSERVER=master

    The label form stays for the ordinary case, where a project has one source
    and naming the repo would be noise.

    A key of its own rather than a nested syntax inside ROOST_CI_TRUNKS:
    ~/.roostrc is a flat KEY=VALUE file, and a second delimiter inside one value
    is a thing to get wrong for no gain.
    """
    spec = ""
    for name in (repo, label):
        if not name:
            continue
        spec = (cfg.get(trunks_key(name)) or "").strip()
        if spec:
            break
    if not spec:
        spec = (cfg.get("ROOST_CI_TRUNKS") or "").strip()
    if not spec:
        return list(TRUNKS_DEFAULT)
    return [b.strip() for b in spec.split(",") if b.strip()]


def _trunk_pool(runs, trunks):
    """(branch, its settled runs, newest first) for the most-preferred trunk
    that has any — or (None, []) when none of them ran in the window.

    The verdict and its evidence are answered from ONE branch's runs rather
    than picked independently, so a tile cannot end up reading ✗ from dev over
    a SHA from main. They are one statement about one trunk; keeping them in
    one pool is what makes that true rather than merely likely.

    `settled` applies the same filter the console feed uses: queued/in-progress
    runs have not said anything yet, and a concurrency-cancelled run is not
    evidence of anything either way.
    """
    settled = [r for r in runs
               if (r.get("conclusion") or r.get("status") or "")
               not in lib.CONSOLE_SKIP]
    for branch in trunks:
        on_branch = [r for r in settled if r.get("headBranch") == branch]
        if on_branch:
            return branch, on_branch
    return None, []


def settled_pools(runs, trunks):
    """[(branch, its settled runs, newest first)] for EVERY trunk that has any,
    in preference order. The first entry keeps the plain tile names; each later
    one gets branch-suffixed tiles beside them, so two trunks read side by side
    (ruled 2026-08-20: dev and master together, after a trunk switch left the
    dev tile asserting a two-day silence while master went green below it)."""
    settled = [r for r in runs
               if (r.get("conclusion") or r.get("status") or "")
               not in lib.CONSOLE_SKIP]
    if not trunks:
        return [("", settled)] if settled else []
    pools = []
    for branch in trunks:
        on_branch = [r for r in settled if r.get("headBranch") == branch]
        if on_branch:
            pools.append((branch, on_branch))
    return pools


def _tile_names(base, branch, primary):
    """(label, match) for a tile. The primary trunk matches the legacy plain
    label so the existing tile renames in place instead of orphaning."""
    if not branch:
        return base, base
    label = f"{base} · {branch}"
    return label, (base if primary else label)


def _build_tile(board, label, branch, pool, primary):
    """One trunk's build state as a single tile: the verdict, what it is a
    verdict on, and the commit it was measured at.

    This was two tiles until 2026-08-25 — a "CI build" ✓/✗ beside a "Last green"
    SHA — and two tiles can disagree. They were already answered from one
    branch's runs precisely so they could not, which is the tell that they were
    always one fact: a trunk's build state is a verdict plus its evidence, and
    splitting it filed half the answer under each of two headings.

    The verdict is the headline because "is the trunk green" is the question a
    reader brings to the board. The SHA and its age go to the tile's `meta`
    line, where they read as the evidence behind the headline instead of
    competing with it for the reader's eye.

    A red trunk is the case the evidence exists for. ✓/✗ alone says nothing
    about what still worked, so a red build reads as "everything is unknown"
    rather than "here is the last thing that was not". The meta line names the
    last green explicitly there, because a bare SHA under a ✗ reads as the SHA
    that failed.

    The link follows the headline: the newest settled run, which under a ✗ is
    the failing one the reader wants open. The green run stays one click away in
    the runs feed below, and its SHA is on the tile.

    Derived from Actions history rather than any runner-local state, so it is
    correct for every repo on the board, survives a runner rebuild, and does not
    depend on a particular CI script having written a file somewhere.
    """
    latest = pool[0]
    ok = latest.get("conclusion") == "success"
    name, match = _tile_names("CI build", branch, primary)
    green = next((r for r in pool if r.get("conclusion") == "success"), None)
    if green is None:
        # Say it rather than leaving the line off. An absent meta reads as "not
        # measured yet"; this is a measurement, and its answer is bad news.
        meta, since = "no green in the window", None
    else:
        sha = str(green.get("headSha", ""))[:7] or "?"
        meta = sha if ok else f"last green {sha}"
        # The SHA is a fact; the age is not — it is only true at the instant it
        # is written. Baking "24m ago" into board.json meant a board sitting
        # open kept asserting a build had gone green 24 minutes ago, hours
        # later, with no such run in the history right below it. Hand the
        # renderer the timestamp and let it compute the age at render time,
        # where it can decay honestly.
        since = green.get("createdAt")
    # Where the verdict was measured, read off the run the headline states.
    #
    # Two build tiles in one column can now come from two different CI systems.
    # MWServer's dev is green on the Forgejo instance today and its master is
    # green on GitHub from a fortnight ago, and unmarked they read as one
    # project's two branches rather than as two pipelines, one of which nobody
    # runs. A ✓ that does not say where it came from is the badge asserting more
    # than it knows.
    forge = lib.run_forge(latest.get("url"))
    where = f"on {forge}" if forge else None
    lib.upsert_compare_tile(board, label, name, "✓" if ok else "✗",
                            tone="go" if ok else "you", href=latest.get("url"),
                            match=match, meta=meta, since=since, where=where)


def _reach_quiet_trunks(repo, runs, trunks, from_forge=False):
    """Extra runs for declared trunks the window did not reach.

    The window is the repo's newest runs across every workflow, so a trunk that
    builds rarely falls out of it while noisier things stay in. MWServer's
    master last built on 2026-08-19 and the repo has run a bot workflow on
    issue comments many times since, so master was nowhere in the newest forty
    and its tile could not be written at all.

    One targeted fetch per missing trunk, and only for a trunk that has none —
    a busy trunk costs nothing. `gh run list --branch` narrows server-side, so
    this reaches back as far as the branch's own history rather than paging the
    repo's.

    The depth is what it is because a quiet trunk is not quiet in `gh run list`:
    MWServer's master carries dozens of bot runs on issue comments, every one of
    them skipped, and a shallow fetch returns those and nothing that built. The
    filter that drops them is downstream, so the reach has to clear them first.

    Forge sources are skipped: the fetch is a `gh` call against a repo path
    that exists only on the forge, so it could only ever fail.
    """
    if from_forge:
        return []
    seen = {r.get("headBranch") for r in runs}
    extra = []
    for branch in trunks:
        if branch in seen:
            continue
        found = lib.gh_run_history(repo, limit=QUIET_TRUNK_DEPTH, branch=branch)
        if found:
            extra += found
    return extra


def apply_tiles(board, label, runs, trunks, column_trunks=None):
    """One SOURCE's tile pass: every trunk with settled runs gets its build
    tile, the preferred one under the plain-renamed name, the rest
    branch-suffixed.

    No trunk in the window leaves the tiles exactly as they were rather than
    setting them from whatever else happened to run — the collector's standing
    contract is that missing data leaves the board alone, and a badge driven by
    a feature branch is the bug that contract prevents.

    `column_trunks` is every trunk the COLUMN carries, across all sources
    feeding it, and only the retirement uses it. A column can be fed by two
    sources: MWServer's dev comes from the Forgejo mirror and its master from
    GitHub. Retiring against this source's own trunks would then have each
    source delete the other's tile, and the column would flip between them by
    whichever collector ran last. Defaults to `trunks`, which is the same thing
    wherever a column has one source.
    """
    pools = settled_pools(runs, trunks)
    if not pools:
        print(f"ci-status: {label}: nothing settled on {'/'.join(trunks)} in "
              "the window — leaving the tiles as-is")
        return
    # Retire the "Last green" tiles this collector used to write beside the
    # verdict. An upsert never removes, so without this the old tile would keep
    # the SHA it last held while the merged tile moved on, and no later run
    # would correct it. A tile no collector writes any more is worse than a
    # missing one: it states a stale number beside the live ones, in the same
    # type, with the same confidence.
    folded = lib.remove_compare_tile(board, label, "Last green")
    if folded:
        print(f"ci-status: {label}: folded {folded} 'Last green' tile(s) "
              "into the build tile")
    # Retire build tiles for branches the COLUMN no longer calls a trunk, for
    # the same reason: a tile no collector writes any more states a stale
    # verdict beside the live ones, in the same type, and no later run corrects
    # it.
    #
    # Driven by declared trunks, never by what the window happened to hold. The
    # window is the last runs per repo, so a busy dev can push a quiet main out
    # of it, and retiring on absence would delete a healthy tile on a slow day.
    # A branch stops being a trunk because someone says so.
    retired = _retire_untrunked_tiles(board, label,
                                      column_trunks if column_trunks is not None
                                      else trunks)
    if retired:
        print(f"ci-status: {label}: retired {retired} build tile(s) for "
              f"branches no longer declared a trunk")
    for i, (branch, pool) in enumerate(pools):
        _build_tile(board, label, branch, pool, primary=(i == 0))


def _retire_untrunked_tiles(board, label, trunks):
    """Remove `CI build · <branch>` tiles whose branch is not a trunk here.

    The unsuffixed `CI build` tile is never touched: it is the primary trunk's,
    whichever branch that currently is, and removing it would delete the tile
    this pass is about to write.
    """
    keep = {f"CI build · {b}" for b in trunks}
    removed = 0
    for col in lib.compare_columns(board, label):
        items = col.get("items", [])
        kept = [t for t in items
                if not (str(t.get("label", "")).startswith("CI build · ")
                        and t.get("label") not in keep)]
        removed += len(items) - len(kept)
        col["items"] = kept
    return removed


def _ledger_line(entry, repo_entries):
    """A ledger entry as a console line, in the feed's own vocabulary.
    The superseded evidence check runs against the entry's whole repo history,
    so the label stays honest however far the run has scrolled."""
    state = entry.get("conclusion") or "unknown"
    line = {"status": state.replace("_", " "),
            "tone": lib.TONE.get(state, "none"),
            "text": f"{entry.get('label', '?')} · {entry.get('headBranch', '?')}"}
    if entry.get("logo"):
        line["logo"] = entry["logo"]
    event = entry.get("event", "")
    if state in ("cancelled", "skipped") and lib.newer_run_exists(entry, repo_entries):
        line["meta"] = f"· superseded · {event}" if event else "· superseded"
    elif event:
        line["meta"] = f"· {event}"
    # Where it ran, the same way the feed says it: the forge, then the box.
    #
    # The forge comes off the entry's own URL, so it lands on every run already
    # on record rather than only on the ones collected from here on. The box is
    # read from the cache alone: the ledger holds every run ever seen, and
    # asking the API about all of them would spend hundreds of calls on runs
    # whose jobs GitHub has aged out, every single collector run. The feed pays
    # that call while a run is recent, and this reads what it learned.
    forge = lib.run_forge(entry.get("url"))
    if forge:
        line["meta"] = f"{line.get('meta', '')} · on {forge}".strip()
    if forge in ("github", None):
        repo, run_id = entry.get("repo", ""), entry.get("id")
        # Box then architecture, the same order and wording the feed uses. The
        # two surfaces describe one run, so they must not describe it
        # differently.
        for fact in (lib.gh_run_runner(repo, run_id, lookup=False),
                     lib.gh_run_arch(repo, run_id, lookup=False)):
            if fact:
                line["meta"] = f"{line.get('meta', '')} · {fact}".strip()
    if entry.get("createdAt"):
        line["ts"] = entry["createdAt"]
    if entry.get("url"):
        line["href"] = entry["url"]
    return line


def _write_ledger_page(led_dir, board_dir, entries):
    """The runs page: stats, a runs-per-day chart, and the full record capped
    at LEDGER_MAX rendered lines. The ledger file itself is never capped."""
    by_repo = {}
    for e in entries:
        by_repo.setdefault(e.get("repo"), []).append(e)
    lines = [_ledger_line(e, by_repo[e.get("repo")]) for e in entries[:LEDGER_MAX]]
    today = datetime.date.today()
    days = [today - datetime.timedelta(days=i) for i in range(CHART_DAYS - 1, -1, -1)]
    per_day = {}
    for e in entries:
        ts = (e.get("createdAt") or "")[:10]
        per_day[ts] = per_day.get(ts, 0) + 1
    series = [{"label": d.strftime("%m-%d"),
               "value": per_day.get(d.isoformat(), 0), "fill": "code"}
              for d in days]
    page = {
        "title": "CI runs — the ledger",
        "eyebrow": "⚙️ status.jimmyhoughjr.net",
        "stamp": f"Every completed run the collector has seen, kept forever — {len(entries)} in all. "
                 "The board's recent-runs feed is a sliding window; this page is the record behind it.",
        "links": [{"label": "← board", "href": "../"}],
        "sections": [
            {"kind": "stats", "items": [
                {"n": str(len(entries)), "label": "Runs on record", "tone": "go"},
                {"n": str(per_day.get(today.isoformat(), 0)), "label": "Today", "tone": "you"},
                {"n": str(len(by_repo)), "label": "Repos", "tone": "done"},
            ]},
            {"kind": "barchart", "icon": "📈", "title": "Activity",
             "desc": f"runs per day, last {CHART_DAYS} days", "series": series},
            {"kind": "console", "icon": "⚙️", "title": "Every run",
             "desc": "all repos merged, newest first",
             "count": f"{min(LEDGER_MAX, len(entries))} of {len(entries)}",
             "lines": lines},
        ],
    }
    (led_dir / "board.json").write_text(json.dumps(page, indent=2, ensure_ascii=False))
    if TEMPLATE.exists():
        html = TEMPLATE.read_text().replace("PLACEHOLDER", "CI runs — the ledger")
        (led_dir / "index.html").write_text(html)


def _runs_section(board_dir, entries, feed_lines):
    """The board's runs console, rendered from the ledger.

    Built with `_ledger_line`, the same function the runs page uses, so the two
    surfaces cannot drift into describing the same run differently.

    `feed_lines` supplies the watch chips, which are controls rather than runs
    and so are not in the ledger. They lead, because in a scrolling block
    anything after the rows is below the fold and unreachable without hunting
    for it. The rule they were moved for still holds: a chip must not sit
    BETWEEN runs, where it reads as something that happened at that time.

    An empty ledger falls back to the live window, so a board collecting for
    the first time still shows its runs.
    """
    if entries:
        by_repo = {}
        for entry in entries:
            by_repo.setdefault(entry.get("repo"), []).append(entry)
        chips = [ln for ln in feed_lines if "cmd" in ln]
        rows = [_ledger_line(e, by_repo[e.get("repo")])
                for e in entries[:LEDGER_MAX]]
        lines = chips + rows
        shown = len(rows)
    else:
        lines = feed_lines
        shown = len(feed_lines)
    count = f"{shown} run" if shown == 1 else f"{shown} runs"
    return {
        "kind": "console", "icon": "⚙️", "title": RUNS_TITLE,
        "href": f"/{board_dir}/runs/",
        # Not "GitHub Actions runs" any more. MWServer's CI runs on the Forgejo
        # instance, so a feed that names one forge while showing two describes
        # itself wrongly on the surface whose whole job is to be trusted.
        "desc": "every run on record, newest first — the title links to the ledger",
        "count": count,
        "scroll": RUNS_ROWS,
        "lines": lines,
    }


def rename_legacy_runs_section(board):
    """Rename the console in place, rather than leaving two of them.

    `upsert_section` finds a section by title, so under the new name it would
    not see the old section at all: it would insert a second console and the
    board would carry both, the stale one frozen at whatever it last held.
    Renaming in place also keeps the section where it was hand-arranged, which
    inserting after the compare block would not.
    """
    for section in board.get("sections", []):
        if section.get("title") == RUNS_TITLE_WAS:
            section["title"] = RUNS_TITLE
            return True
    return False


def update_ledger(site, board_dir, sources_runs):
    """Append every settled run to <board>/runs/ledger.json and regenerate the
    runs page. Append-only by run id: a run that scrolls out of the feed's
    window stays here, because the feed answers "what just happened" and the
    ledger answers "everything that happened" (asked for 2026-08-20, after a
    day's builds vanished from a 3-line window)."""
    led_dir = site / board_dir / "runs"
    led_dir.mkdir(parents=True, exist_ok=True)
    led_path = led_dir / "ledger.json"
    try:
        ledger = json.loads(led_path.read_text())
    except (OSError, ValueError):
        ledger = {"runs": []}
    entries = ledger["runs"]
    seen = {e.get("id") for e in entries}
    added = 0
    for repo, label, logo, runs in sources_runs:
        # Re-stamp what the source, not the run, decides: its label and its
        # stack mark. The ledger dedupes by run id, so a run recorded under an
        # older spec would otherwise keep that spec's presentation for good.
        #
        # MWServer is why. Moving it to the forge rewrote its source line, the
        # new one was written without the `:swift` mark, and every run collected
        # after that lost the stack logo the rest of its history carries. A
        # config fix has to reach the record, or the gap stays visible forever.
        #
        # Matched on the LABEL as well as the repo, because a project that moves
        # forge keeps its label and changes its repo. MWServer's runs are split
        # across the GitHub repo and the forge mirror; they are one project on
        # the board, so they wear one mark. Matching the repo alone would leave
        # the half collected before the move behind, and no later run could
        # reach it — the mirror's id never appears on those entries again.
        for entry in entries:
            if entry.get("repo") != repo and entry.get("label") != label:
                continue
            entry["label"] = label
            if logo:
                entry["logo"] = logo
            else:
                entry.pop("logo", None)
        for r in runs:
            if not r.get("conclusion"):
                continue
            rid = r.get("databaseId")
            if rid is None or rid in seen:
                continue
            entry = {"id": rid, "repo": repo, "label": label,
                     "conclusion": r.get("conclusion"),
                     "headBranch": r.get("headBranch"),
                     "event": r.get("event"),
                     "workflowName": r.get("workflowName"),
                     "createdAt": r.get("createdAt"),
                     "updatedAt": r.get("updatedAt"),
                     "url": r.get("url")}
            if logo:
                entry["logo"] = logo
            entries.append(entry)
            seen.add(rid)
            added += 1
    entries.sort(key=lambda e: e.get("createdAt") or "", reverse=True)
    led_path.write_text(json.dumps(ledger, indent=1, ensure_ascii=False))
    _write_ledger_page(led_dir, board_dir, entries)
    return added, entries


def main():
    cfg = lib.read_roostrc()
    spec = cfg.get("ROOST_CI_REPOS", "")
    board_dir = cfg.get("ROOST_CI_BOARD", "")
    if not spec or not board_dir:
        print("ci-status: ROOST_CI_REPOS/ROOST_CI_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"ci-status: {board_path} not found — skipping")
        return 0

    # Repos whose CI runs on the Forgejo instance rather than on GitHub. They
    # take the same spec syntax and join the same window, so a board can report
    # both forges at once. This matters during a migration: a repo whose real
    # pipeline has moved would otherwise keep showing its abandoned GitHub runs,
    # and the badge would report a project as red while it is green in house.
    #
    # Unset means unchanged. A board with no Forgejo config behaves exactly as
    # it did before, by the "no config, no effect" rule at the top of lib.
    forge_spec = cfg.get("ROOST_CI_FORGEJO_REPOS", "")
    forge_url = cfg.get("ROOST_CI_FORGEJO_URL", "")
    forge_token = cfg.get("ROOST_CI_FORGEJO_TOKEN", "")

    sources = parse_sources(spec)
    forge_sources = parse_sources(forge_spec) if forge_spec else []
    if forge_sources and not (forge_url and forge_token):
        print("ci-status: ROOST_CI_FORGEJO_REPOS set without "
              "ROOST_CI_FORGEJO_URL/TOKEN — skipping the forge")
        forge_sources = []
    sources = sources + forge_sources
    # The run we are executing inside, if CI told us — see lib.self_run_from.
    self_run = lib.self_run_from(cfg)
    # One `gh run list` per repo per push. The feed, the tiles, and the ledger
    # all read from this window; each takes a shallow copy because
    # apply_self_run runs once per consumer.
    window = {}
    forge_repos = {repo for repo, _, _, _ in forge_sources}
    for repo, _, _, _ in sources:
        from_forge = repo in forge_repos
        if from_forge:
            runs = lib.forgejo_runs(forge_url, forge_token, repo, 40)
        else:
            runs = lib.gh_runs(repo, 40)
        if runs:
            window[repo] = runs
        else:
            # Silence leaves the tiles holding their last verdict, which is how
            # a board goes on reporting a green that stopped being true.
            print(lib.quiet_repo_note(repo, runs, from_forge=from_forge))
    lines = lib.console_lines(sources, self_run=self_run,
                              fetched={r: list(v) for r, v in window.items()})
    if not lines:
        print("ci-status: no CI data (gh unavailable?) — leaving board as-is")
        return 0

    board = lib.load_board(board_path)
    rename_legacy_runs_section(board)
    # Wire each repo's build tiles to that repo's TRUNK state.
    #
    # Scoped per column on purpose. This used to set the first "CI build" tile
    # in any column from the newest run across all repos, which on a two-repo
    # board is one repo's build state shown under the other repo's heading;
    # it only looked right because the busier repo happened to sort first.
    #
    # Scoped per branch for the same class of reason: the tiles were then read
    # off the repo's newest console line whatever branch it came from, so a red
    # pull request published a ✗ badge for a project whose trunks were green.
    # The console feed below still carries every branch — seeing your PR fail
    # there is the point — but the badge answers "is the project green", and
    # only a trunk can answer that. See TRUNKS_DEFAULT.
    # Every trunk a COLUMN carries, across the sources feeding it. Only the
    # retirement uses this: a column fed by two forges must not have each
    # source delete the other's tile. Built before the loop so the first source
    # already knows what the last one will contribute.
    column_trunks = {}
    for repo, label, _, _ in sources:
        for branch in parse_trunks(cfg, label, repo):
            column_trunks.setdefault(label, []).append(branch)

    ledger_sources = []
    for repo, label, _, logo in sources:
        runs = window.get(repo)
        if not runs:
            continue
        runs = list(runs)
        # Same blind spot as the feed: without this the tiles would be decided
        # from a window in which the current run has no verdict yet, so a green
        # trunk build could not mark itself green.
        runs = lib.apply_self_run(repo, runs, self_run)
        ledger_sources.append((repo, label, logo, runs))
        # Per source: one project's trunks can come from two forges, and two
        # projects on one board do not share a trunk set either way.
        source_trunks = parse_trunks(cfg, label, repo)
        apply_tiles(board, label,
                    runs + _reach_quiet_trunks(repo, runs, source_trunks,
                                               from_forge=repo in forge_repos),
                    source_trunks,
                    column_trunks=column_trunks.get(label))

    # The ledger is written first because the console below is now rendered
    # FROM it. The section used to show a sliding window of the last few runs
    # per repo, so a day's builds could scroll out of it and read as never
    # having happened, with the whole record one click away on another page.
    # It now carries the record and scrolls, which is the same information in
    # the same space.
    entries = []
    if ledger_sources:
        added, entries = update_ledger(lib.site_dir(cfg), board_dir, ledger_sources)
        print(f"ci-status: ledger +{added}, {len(entries)} runs on record")

    lib.upsert_section(board, RUNS_TITLE, _runs_section(board_dir, entries, lines),
                       after_kind="compare")
    lib.save_board(board_path, board)
    runs_shown = entries[:LEDGER_MAX] if entries else lines
    print(f"ci-status: {len(runs_shown)} runs, "
          f"latest {lines[0]['text']} = {lines[0]['status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-status: non-fatal error: {e}")
        sys.exit(0)
