#!/usr/bin/env python3
"""shipped_week.py — regenerate the board's "Shipped this week" cards from
the PRs actually merged in the last 7 days, so the section always reflects
what shipped instead of a hand-curated snapshot that goes stale.

One card per merged PR (newest first), title verbatim, first body line as
the note. Cards for PRs are the record; hand-written cards get replaced.

Config (~/.roostrc):
  ROOST_STATS_GH_REPO=Austin-MacWorks/Phoenix-Electron
  ROOST_STATS_BOARD=clauffice
  ROOST_SHIPPED_BASE=dev        # optional: base branch PRs merge into (default dev)
  ROOST_SHIPPED_MAX=12          # optional: max cards (default 12)

Non-fatal by contract: any failure → board untouched, exit 0.
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

SECTION = "Shipped this week"


def merged_prs(slug, base, since):
    out = subprocess.run(
        ["gh", "pr", "list", "-R", slug, "--state", "merged", "--base", base,
         "-L", "50", "--json", "number,title,body,mergedAt"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {out.stderr.strip()[:200]}")
    prs = [p for p in json.loads(out.stdout or "[]")
           if p.get("mergedAt") and p["mergedAt"] >= since]
    prs.sort(key=lambda p: p["mergedAt"], reverse=True)
    return prs


def card(pr):
    body = (pr.get("body") or "").strip()
    first = body.split("\n")[0].strip()
    if len(first) > 220:
        first = first[:217] + "..."
    day = pr["mergedAt"][5:10]  # MM-DD
    return {
        "q": f'{pr["title"]} (#{pr["number"]})',
        "note": first or "Merged.",
        "pill": {"text": f"Merged {day}", "tone": "done"},
    }


def main():
    cfg = lib.read_roostrc()
    slug = cfg.get("ROOST_STATS_GH_REPO", "")
    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    if not slug or not board_dir:
        print("shipped-week: ROOST_STATS_GH_REPO/ROOST_STATS_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"shipped-week: {board_path} not found — skipping")
        return 0

    base = cfg.get("ROOST_SHIPPED_BASE", "dev")
    limit = int(cfg.get("ROOST_SHIPPED_MAX", "12"))
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prs = merged_prs(slug, base, since)
    if not prs:
        print("shipped-week: no PRs merged in the last 7 days — leaving section as-is")
        return 0

    board = lib.load_board(board_path)
    for s in board.get("sections", []):
        if s.get("title") != SECTION:
            continue
        s["kind"] = "cards"
        s["count"] = f"{len(prs)} merged"
        s["desc"] = f"PRs merged into {base} in the last 7 days — regenerated from GitHub on every status push"
        s["items"] = [card(p) for p in prs[:limit]]
        if len(prs) > limit:
            s["desc"] += f" · showing {limit} of {len(prs)}"
        lib.save_board(board_path, board)
        print(f"shipped-week: {len(prs)} merged PRs (last 7d), newest #{prs[0]['number']} {prs[0]['mergedAt']}")
        return 0
    print(f"shipped-week: no '{SECTION}' section on board — nothing to patch")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"shipped-week: non-fatal error: {e}")
        sys.exit(0)
