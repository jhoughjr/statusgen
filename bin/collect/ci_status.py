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
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


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


def _scope(runs, trunks):
    """Runs to answer a tile from: the preferred trunk's, or all of them when
    no trunk filter is configured."""
    if not trunks:
        return runs
    return _trunk_pool(runs, trunks)[1]


def _ci_build_tile(board, label, runs, trunks):
    """✓/✗ for the newest settled run on the preferred trunk.

    When no trunk ran inside the window the tile is left exactly as it was
    rather than being set from whatever else happened to run — the collector's
    standing contract is that missing data leaves the board alone, and a badge
    driven by a feature branch is the bug this function exists to prevent.
    """
    branch, pool = _trunk_pool(runs, trunks) if trunks else (None, runs)
    if not pool:
        print(f"ci-status: {label}: nothing settled on {'/'.join(trunks)} in "
              "the window — leaving the CI build tile as-is")
        return
    latest = pool[0]
    ok = latest.get("conclusion") == "success"
    lib.upsert_compare_tile(board, label, "CI build", "✓" if ok else "✗",
                            tone="go" if ok else "you", href=latest.get("url"))


def _last_green_tile(board, repo, label, runs=None, trunks=None):
    """A "Last green" tile: the commit this repo was last successful at, and how
    long ago — shown whether the current build is green or red.

    The "CI build" tile above only says ✓/✗ right now. That is the one moment it
    is least useful: when a build goes red, the board stops saying anything about
    what still worked, so a red run reads as "everything is unknown" rather than
    "here is the last thing that wasn't". Worse, a repo whose tiles only refresh
    on green keeps showing the previous green's numbers with nothing admitting
    they are stale.

    Derived from Actions history rather than any runner-local state, so it is
    correct for every repo on the board, survives a runner rebuild, and does not
    depend on a particular CI script having written a file somewhere.
    """
    if runs is None:
        runs = lib.gh_runs(repo, 40)
    if not runs:
        return
    pool = _scope(runs, trunks)
    green = next((r for r in pool if r.get("conclusion") == "success"), None)
    if green is None:
        # Say so rather than leaving a stale tile claiming an old green.
        lib.upsert_compare_tile(board, label, "Last green", "none recent",
                                tone="you", href=None)
        return
    sha = str(green.get("headSha", ""))[:7] or "?"
    age = lib.fmt_age(green.get("createdAt"))
    lib.upsert_compare_tile(board, label, "Last green",
                            f"{sha} · {age}" if age else sha,
                            tone="go", href=green.get("url"))


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
    lines = lib.console_lines(sources, self_run=self_run)
    if not lines:
        print("ci-status: no CI data (gh unavailable?) — leaving board as-is")
        return 0

    section = {
        "kind": "console", "icon": "⚙️", "title": "CI — recent runs",
        "desc": "latest GitHub Actions runs",
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
    for repo, label, _, _ in sources:
        runs = lib.gh_runs(repo, 40)
        if not runs:
            continue
        # Same blind spot as the feed: without this the tiles would be decided
        # from a window in which the current run has no verdict yet, so a green
        # trunk build could not mark itself green.
        runs = lib.apply_self_run(repo, runs, self_run)
        _ci_build_tile(board, label, runs, trunks)
        _last_green_tile(board, repo, label, runs=runs, trunks=trunks)
    lib.save_board(board_path, board)
    print(f"ci-status: {len(lines)} runs, latest {lines[0]['text']} = {lines[0]['status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-status: non-fatal error: {e}")
        sys.exit(0)
