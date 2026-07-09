#!/usr/bin/env python3
"""repo_stats.py — recompute a board's test/coverage tiles from a live repo,
so the tiles never go stale.

  - Tests green : passing count from a full test run
  - Added (7d)  : delta vs the board value as committed ~7 days ago
  - Coverage    : line % from coverage/coverage-summary.json (last run)

Patches the FIRST column of the board's compare section (or is a no-op if the
board has none), and refreshes the top-of-board stamp.

Config (~/.roostrc):
  ROOST_STATS_BOARD=clauffice                   # board dir under the status site
  ROOST_STATS_REPO=$HOME/repos/Phoenix-Electron # repo to measure
  ROOST_STATS_TEST_CMD=npx vitest run           # optional (this is the default)
  ROOST_STATS_LABEL=Phoenix                     # optional stamp label (default: repo dir name)

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import sys
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def main():
    cfg = lib.read_roostrc()
    repo = cfg.get("ROOST_STATS_REPO", "")
    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    if not repo or not board_dir:
        print("repo-stats: ROOST_STATS_REPO/ROOST_STATS_BOARD not configured — skipping")
        return 0
    site = lib.site_dir(cfg)
    rel = f"{board_dir}/board.json"
    board_path = site / rel
    if not board_path.exists():
        print(f"repo-stats: {board_path} not found — skipping")
        return 0

    count = lib.test_count(repo, cfg.get("ROOST_STATS_TEST_CMD", "npx vitest run"))
    if count is None:
        print("repo-stats: could not read test count — leaving tiles as-is")
        return 0
    cov = lib.line_coverage(repo)
    base = lib.find_stat(lib.board_at(site, rel), "Tests green")
    delta = count - base if base is not None else 0

    board = lib.load_board(board_path)
    patched = False
    for s in board.get("sections", []):
        if s.get("kind") != "compare":
            continue
        col = s["columns"][0]
        for tile in col["items"]:
            lbl = str(tile.get("label", ""))
            if lbl.startswith("Tests green"):
                tile["n"] = str(count)
            elif "added" in lbl.lower():
                tile["n"] = f"+{delta}" if delta >= 0 else str(delta)
                tile["label"] = "Added (7d)"  # rolling weekly window
            elif "Coverage" in lbl and cov is not None:
                tile["n"] = f"{cov}%"
        patched = True

    if not patched:
        print("repo-stats: no compare section found — nothing to patch")
        return 0

    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    cov_txt = f" · {cov}% coverage" if cov is not None else ""
    name = cfg.get("ROOST_STATS_LABEL") or pathlib.Path(repo).name
    board["stamp"] = (f"Updated {ts} — {name} {count:,} tests green{cov_txt} "
                      f"· +{delta:,} added (7d)")

    lib.save_board(board_path, board)
    print(f"repo-stats: tests={count} (Δ+{delta} vs 7d-ago {base}) coverage={cov}%")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"repo-stats: non-fatal error: {e}")
        sys.exit(0)
