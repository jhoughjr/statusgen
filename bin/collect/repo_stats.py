#!/usr/bin/env python3
"""repo_stats.py — refresh a board's test/coverage tiles from CI's test report.

Reads test-report.json (published as a workflow artifact by the repo's CI on
every green run) from the latest successful run on the configured branch.
CI's clean checkout is the single source of truth: numbers are pinned to the
SHA CI measured, so local checkout state, session worktrees, node versions,
and command variants can never skew what gets reported.

When the artifact is missing (uploads are best-effort — GitHub's artifact
storage quota can block them for hours after a cleanup), falls back to the
same report JSON that CI's "Emit test report" step prints to the run log.

  - Tests green : tests_passed from the CI report
  - Added (7d)  : delta vs the board value as committed ~7 days ago
  - Coverage    : coverage_lines_pct from the CI report

Patches the FIRST column of the board's compare section (or is a no-op if the
board has none), and refreshes the top-of-board stamp.

When the report carries the richer `coverage` object (emitted by newer CI),
also patches a "Test Coverage" barchart section: the four metric bars
(Lines/Statements/Functions/Branches, matched by label) and a note with the
zero-coverage file count and top worst-offenders by uncovered lines. Old
reports without the object leave the chart untouched.

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


def log_report(slug, rid):
    """The report JSON as printed to the run log by the Emit step — reachable
    even when the artifact upload was quota-blocked. Returns dict or None."""
    out = subprocess.run(
        ["gh", "run", "view", rid, "-R", slug, "--log"],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if '"tests_passed"' not in line or "{" not in line:
            continue
        try:
            report = json.loads(line[line.index("{"):])
        except ValueError:
            continue
        if "coverage_lines_pct" in report:
            return report
    return None


def ci_report(slug, branch):
    """test-report.json from the newest successful CI run on `branch` that
    published one — from the artifact, or the run log when the artifact is
    missing. Returns (report_dict, run_id) or (None, None)."""
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
            if dl.returncode == 0:
                path = pathlib.Path(td) / "test-report.json"
                if path.exists():
                    return json.loads(path.read_text()), rid
        report = log_report(slug, rid)
        if report is not None:
            print(f"repo-stats: no artifact on run {rid} — using report from its log")
            return report, rid
        # older run without the report — try the next
    return None, None


def head_sha(slug, branch):
    """Current HEAD sha (7-char) of `branch`, or None. Best-effort — a failure
    just means we can't judge staleness, never that the board is touched."""
    out = subprocess.run(
        ["gh", "api", f"repos/{slug}/commits/{branch}", "--jq", ".sha"],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.strip()[:7]


def patch_coverage_chart(board, covd, count):
    """Patch a "Test Coverage" barchart from the report's `coverage` object:
    metric bars matched by label, note rebuilt with the zero-coverage file
    count and top-3 worst offenders (ranked upstream by uncovered lines).
    Returns True when a matching section was patched."""
    keys = {"Lines": "lines_pct", "Statements": "statements_pct",
            "Functions": "functions_pct", "Branches": "branches_pct"}
    for s in board.get("sections", []):
        if s.get("kind") != "barchart" or s.get("title") != "Test Coverage":
            continue
        for bar in s.get("series", []):
            k = keys.get(str(bar.get("label", "")))
            if k and k in covd:
                bar["value"] = round(float(covd[k]), 1)
        bits = [f"{count:,} tests green"]
        if covd.get("files_total"):
            bits.append(f"{covd.get('files_zero', 0)} of {covd['files_total']} "
                        f"files at 0%")
        worst = [f"{w['file'].rsplit('/', 1)[-1]} ({w['uncovered_lines']})"
                 for w in (covd.get("worst") or [])[:3]]
        if worst:
            bits.append("most uncovered lines: " + ", ".join(worst))
        s["note"] = " · ".join(bits)
        return True
    return False


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

    covd = report.get("coverage") or {}
    chart = patch_coverage_chart(board, covd, count) if covd else False

    if not (patched or chart):
        print("repo-stats: no compare or Test Coverage section found — nothing to patch")
        return 0

    # Optional second branch (e.g. main while the headline tracks dev):
    # shown in the stamp as the stable record, without touching the tiles.
    extra = ""
    branch2 = cfg.get("ROOST_STATS_CI_BRANCH2", "")
    if branch2 and branch2 != branch:
        r2, _ = ci_report(slug, branch2)
        if r2 is not None:
            extra = (f" · {branch2}@{str(r2.get('sha',''))[:7]} "
                     f"{int(r2['tests_passed']):,}")

    # Staleness — the numbers come from the newest GREEN run's report, so a red
    # streak (or a build not yet reported) leaves them behind the branch's real
    # HEAD while the stamp still reads "CI dev@<sha>", looking current. Say so
    # plainly: mark the tiles and stamp when the report trails HEAD, so a frozen
    # board is obviously frozen rather than mistaken for up to date.
    head = head_sha(slug, branch)
    stale = bool(head and sha and head != sha)
    stale_note = ""
    if stale:
        stale_note = f" · ⚠ STALE — {branch} is at {head}, numbers as of {sha}"
        for s in board.get("sections", []):
            if s.get("kind") != "compare":
                continue
            for tile in s["columns"][0]["items"]:
                if str(tile.get("label", "")).startswith(("Tests green", "Coverage")):
                    tile["stale"] = True

    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    name = cfg.get("ROOST_STATS_LABEL") or slug.split("/")[-1]
    board["stamp"] = (f"Updated {ts} — {name} {count:,} tests green · {cov}% coverage "
                      f"· CI {branch}@{sha}{extra} · +{delta:,} added (7d){stale_note}")

    lib.save_board(board_path, board)
    print(f"repo-stats: tests={count} coverage={cov}% chart={'patched' if chart else 'n/a'} "
          f"(CI {branch}@{sha}, run {run_id}, Δ+{delta} vs 7d-ago {base}){extra and ' |' + extra}"
          f"{' STALE vs HEAD ' + head if stale else ''}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"repo-stats: non-fatal error: {e}")
        sys.exit(0)
