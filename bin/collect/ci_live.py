#!/usr/bin/env python3
"""ci_live.py — inject a self-refreshing "CI — running now" live-console
section that points at the ci-live endpoint, per board.

Unlike ci_status.py this collector does NOT call `gh`: it only drops a static
`live-console` section whose `poll.url` the board renderer fetches client-side.
The actual live queued/in-progress runs are pushed to that endpoint by the mini
poller (roost/bin/ci-live-report.sh); the renderer follows the endpoint's own
advertised intervalMs, so the interval here is only a first-load fallback.

Config (~/.roostrc):
  ROOST_CI_LIVE_BOARD=clauffice                       # board dir under the site
  ROOST_CI_LIVE_URL=https://ci.jimmyhoughjr.net/api/runs
  ROOST_CI_LIVE_PROJECT=phoenix                       # project slug
  ROOST_CI_LIVE_INTERVAL=30                            # seconds, fallback only

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def main():
    cfg = lib.read_roostrc()
    board_dir = cfg.get("ROOST_CI_LIVE_BOARD", "")
    url = cfg.get("ROOST_CI_LIVE_URL", "")
    project = cfg.get("ROOST_CI_LIVE_PROJECT", "")
    if not board_dir or not url or not project:
        print("ci-live: ROOST_CI_LIVE_BOARD/URL/PROJECT not configured — skipping")
        return 0
    try:
        interval = int(cfg.get("ROOST_CI_LIVE_INTERVAL", "30"))
    except ValueError:
        interval = 30

    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"ci-live: {board_path} not found — skipping")
        return 0

    poll_url = f"{url}?project={project}"
    section = {
        "kind": "live-console",
        "icon": "🔴",
        "title": "CI — running now",
        "desc": "live queued/in-progress runs",
        "poll": {"url": poll_url, "intervalMs": interval * 1000},
    }
    board = lib.load_board(board_path)
    # Place it just before the static "CI — recent runs" console section.
    # upsert_section inserts after the first `after_kind` section; the recent-runs
    # console is itself inserted after the compare block, so anchoring on
    # "compare" lands this live section immediately above it.
    lib.upsert_section(board, "CI — running now", section, after_kind="compare")
    lib.save_board(board_path, board)
    print(f"ci-live: live-console → {poll_url} (fallback every {interval}s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-live: non-fatal error: {e}")
        sys.exit(0)
