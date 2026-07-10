#!/usr/bin/env python3
"""repo_stats.py — refresh a board's test/coverage tiles from CI's test report.

Reads test-report.json (published as a workflow artifact by the repo's CI on
every green run) from the latest successful run on the configured branch.
CI's clean checkout is the single source of truth: numbers are pinned to the
SHA CI measured, so local checkout state, session worktrees, node versions,
and command variants can never skew what gets reported.

  - Tests green : tests_passed from the CI report
  - Added (7d)  : delta vs the board value as committed ~7 days ago
  - Coverage    : coverage_lines_pct from the CI report

Patches the FIRST column of the board's compare section (or is a no-op if the
board has none), and refreshes the top-of-board stamp.

Config (~/.roostrc):
  ROOST_STATS_BOARD=clauffice                          # board dir under the status site
  ROOST_STATS_GH_REPO=Austin-MacWorks/Phoenix-Electron # repo slug for gh
  ROOST_STATS_CI_BRANCH=main                           # branch whose CI to trust (default main)
  ROOST_STATS_LABEL=Phoenix                            # optional stamp label

Non-fatal by contract: no config → skip; any failure → board untouched (last
good numbers stay, with their original stamp date showing the staleness), exit 0.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

ARTIFACT = "test-report"


def ci_report(slug, branch):
    """test-report.json from the newest successful CI run on `branch` that
    published one. Returns (report_dict, run_id) or (None, None)."""
    out = subprocess.run(
        ["gh", "run", "list", "-R", slug, "-b", branch, "-s", "success",
         "-L", "10", "--json", "databaseId"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(f"repo-stats: gh run list failed: {out.stderr.strip()[:200]}")
        return None, None
    for run in json.loads(out.stdout or "[]"):
        rid = str(run["databaseId"])
        with tempfile.TemporaryDirectory() as td:
            dl = subprocess.run(
                ["gh", "run", "download", rid, "-R", slug, "-n", ARTIFACT, "-D", td],
                capture_output=True, text=True, timeout=120)
            if dl.returncode != 0:
                continue  # older run without the artifact — try the next
            path = pathlib.Path(td) / "test-report.json"
            if path.exists():
                return json.loads(path.read_text()), rid
    return None, None


def main():
    cfg = lib.read_roostrc()
    slug = cfg.get("ROOST_STATS_GH_REPO", "")
    board_dir = cfg.get("ROOST_STATS_BOARD", "")
    branch = cfg.get("ROOST_STATS_CI_BRANCH", "main")
    if not slug or not board_dir:
        print("repo-stats: ROOST_STATS_GH_REPO/ROOST_STATS_BOARD not configured — skipping")
        return 0
    site = lib.site_dir(cfg)
    rel = f"{board_dir}/board.json"
    board_path = site / rel
    if not board_path.exists():
        print(f"repo-stats: {board_path} not found — skipping")
        return 0

    report, run_id = ci_report(slug, branch)
    if report is None:
        print(f"repo-stats: no {ARTIFACT} artifact on recent green {branch} runs — leaving tiles as-is")
        return 0
    count = int(report["tests_passed"])
    cov = round(float(report["coverage_lines_pct"]))
    sha = str(report.get("sha", ""))[:7]

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
            elif "Coverage" in lbl:
                tile["n"] = f"{cov}%"
        patched = True

    if not patched:
        print("repo-stats: no compare section found — nothing to patch")
        return 0

    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    name = cfg.get("ROOST_STATS_LABEL") or slug.split("/")[-1]
    board["stamp"] = (f"Updated {ts} — {name} {count:,} tests green · {cov}% coverage "
                      f"· CI {branch}@{sha} · +{delta:,} added (7d)")

    lib.save_board(board_path, board)
    print(f"repo-stats: tests={count} coverage={cov}% (CI {branch}@{sha}, run {run_id}, Δ+{delta} vs 7d-ago {base})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"repo-stats: non-fatal error: {e}")
        sys.exit(0)
