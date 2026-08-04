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


def _last_green_tile(board, repo, label):
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
    runs = lib.gh_runs(repo, 40)
    if not runs:
        return
    green = next((r for r in runs if r.get("conclusion") == "success"), None)
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
    lines = lib.console_lines(sources)
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
    # Wire each repo's "CI build" tile to that repo's latest real outcome (its
    # first non-watch console line — console_lines already dropped in-progress
    # and superseded-cancelled runs).
    #
    # Scoped per column on purpose. This used to set the first "CI build" tile
    # in any column from the newest run across all repos, which on a two-repo
    # board is one repo's build state shown under the other repo's heading;
    # it only looked right because the busier repo happened to sort first.
    for repo, label, _, _ in sources:
        latest = next((l for l in lines
                       if "cmd" not in l
                       and str(l.get("text", "")).startswith(f"{label} ")), None)
        if not latest:
            continue
        ok = latest.get("status") == "success"
        lib.upsert_compare_tile(board, label, "CI build",
                                "✓" if ok else "✗",
                                tone="go" if ok else "you",
                                href=latest.get("href"))
        _last_green_tile(board, repo, label)
    lib.save_board(board_path, board)
    print(f"ci-status: {len(lines)} runs, latest {lines[0]['text']} = {lines[0]['status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-status: non-fatal error: {e}")
        sys.exit(0)
