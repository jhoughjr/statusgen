#!/usr/bin/env python3
"""ci_status.py — surface recent GitHub Actions runs on a board as a
"CI — recent runs" console section, pulled live via `gh`.

Config (~/.roostrc):
  ROOST_CI_BOARD=clauffice                      # board dir under the status site
  ROOST_CI_REPOS=owner/repo:Label:4,owner/other:Other:3

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib


def parse_sources(spec):
    out = []
    for part in spec.split(","):
        bits = part.strip().split(":")
        if len(bits) == 3:
            out.append((bits[0], bits[1], int(bits[2])))
        elif len(bits) == 2:
            out.append((bits[0], bits[1], 4))
        elif bits[0]:
            out.append((bits[0], bits[0].split("/")[-1], 4))
    return out


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

    lines = lib.console_lines(parse_sources(spec))
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
    for label in [lbl for _, lbl, _ in parse_sources(spec)]:
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
    lib.save_board(board_path, board)
    print(f"ci-status: {len(lines)} runs, latest {lines[0]['text']} = {lines[0]['status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"ci-status: non-fatal error: {e}")
        sys.exit(0)
