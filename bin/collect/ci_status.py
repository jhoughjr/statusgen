#!/usr/bin/env python3
"""ci_status.py — surface recent GitHub Actions runs on a board as a
"CI — recent runs" console section, pulled live via `gh`.

Config (~/.roostrc):
  ROOST_CI_BOARD=clauffice                      # board dir under the status site
  ROOST_CI_REPOS=owner/repo:Label:4[:logo],owner/other:Other:3[:logo]

`logo` tags every one of that repo's rows with a stack mark (swift/ts/js), so
one merged chronological feed still says which side each run belongs to.

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import datetime
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

LEDGER_MAX = 200
CHART_DAYS = 14
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


def parse_trunks(cfg):
    """"dev,main" → ["dev", "main"]; unset → TRUNKS_DEFAULT."""
    spec = (cfg.get("ROOST_CI_TRUNKS") or "").strip()
    if not spec:
        return list(TRUNKS_DEFAULT)
    return [b.strip() for b in spec.split(",") if b.strip()]


def _trunk_pool(runs, trunks):
    """(branch, its settled runs, newest first) for the most-preferred trunk
    that has any — or (None, []) when none of them ran in the window.

    Both tiles are answered from ONE branch's runs rather than picked
    independently, so a column cannot end up reading "CI build ✗" from dev next
    to a "Last green" from main. The pair is meant to be read together.

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
    lib.upsert_compare_tile(board, label, name, "✓" if ok else "✗",
                            tone="go" if ok else "you", href=latest.get("url"),
                            match=match, meta=meta, since=since)


def apply_tiles(board, label, runs, trunks):
    """One repo's tile pass: every trunk with settled runs gets its build tile,
    the preferred one under the plain-renamed name, the rest branch-suffixed.

    No trunk in the window leaves the tiles exactly as they were rather than
    setting them from whatever else happened to run — the collector's standing
    contract is that missing data leaves the board alone, and a badge driven by
    a feature branch is the bug that contract prevents.
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
    for i, (branch, pool) in enumerate(pools):
        _build_tile(board, label, branch, pool, primary=(i == 0))


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
    return added, len(entries)


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

    sources = parse_sources(spec)
    trunks = parse_trunks(cfg)
    # The run we are executing inside, if CI told us — see lib.self_run_from.
    self_run = lib.self_run_from(cfg)
    # One `gh run list` per repo per push. The feed, the tiles, and the ledger
    # all read from this window; each takes a shallow copy because
    # apply_self_run runs once per consumer.
    window = {}
    for repo, _, _, _ in sources:
        runs = lib.gh_runs(repo, 40)
        if runs:
            window[repo] = runs
    lines = lib.console_lines(sources, self_run=self_run,
                              fetched={r: list(v) for r, v in window.items()})
    if not lines:
        print("ci-status: no CI data (gh unavailable?) — leaving board as-is")
        return 0

    section = {
        "kind": "console", "icon": "⚙️", "title": "CI — recent runs",
        "href": f"/{board_dir}/runs/",
        "desc": "latest GitHub Actions runs — the title links to the full ledger",
        "count": f"{len(lines)} runs",
        "lines": lines,
    }
    board = lib.load_board(board_path)
    lib.upsert_section(board, "CI — recent runs", section, after_kind="compare")
    # Wire each repo's pair of tiles to that repo's TRUNK state.
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
        apply_tiles(board, label, runs, trunks)
    lib.save_board(board_path, board)
    if ledger_sources:
        added, total = update_ledger(lib.site_dir(cfg), board_dir, ledger_sources)
        print(f"ci-status: ledger +{added}, {total} runs on record")
    print(f"ci-status: {len(lines)} runs, latest {lines[0]['text']} = {lines[0]['status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-status: non-fatal error: {e}")
        sys.exit(0)
