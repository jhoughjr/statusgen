#!/usr/bin/env python3
"""swift_test_report.py - test RESULTS and coverage for a Swift repo whose gate runs in CI.

This is the counterpart of swift_tests.py, and the two are mutually exclusive per repo.
swift_tests.py counts the test cases a source tree declares, because a repo with no gate has no result to report.
This one reads what a run actually reported, so its tiles say "green" rather than "written".

Move a repo from ROOST_SWIFT_TESTS to ROOST_SWIFT_REPORT on the day its gate starts emitting a report.
Leaving it in both makes the two collectors fight over the same tile on every push, and the winner is whichever ran last.

The report is `test-report.json`, the same shape the Phoenix pipeline emits, so one contract serves both sides of the estate.
It arrives as an artifact of the newest successful run, or from that run's log when an artifact-quota blackout ate the upload.

Config (~/.roostrc):
  ROOST_SWIFT_REPORT_BOARD=clauffice
  ROOST_SWIFT_REPORT=owner/repo:Column:branch[:Label], …

  Column    substring of the compare column title this repo owns
  branch    branch whose runs are read (default dev)
  Label     name that leads the section titles (default the repo name)

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import json
import subprocess
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

DEFAULT_BRANCH = "dev"
ARTIFACT = "test-report"
# A run list and an artifact download must not wedge an hourly push.
GH_TIMEOUT = 120

# The four llvm-cov metrics, in the order the coverage chart reads.
# Lines leads because it is the number the compare tile carries.
COVERAGE_METRICS = (
    ("coverage_lines_pct", "Lines"),
    ("coverage_regions_pct", "Regions"),
    ("coverage_functions_pct", "Functions"),
    ("coverage_branches_pct", "Branches"),
)


def parse_sources(spec):
    """"owner/repo:Column:branch[:Label], …" → list of dicts."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(":")]
        slug = bits[0]
        if not slug or "/" not in slug:
            continue
        column = bits[1] if len(bits) > 1 and bits[1] else slug.split("/")[-1]
        branch = bits[2] if len(bits) > 2 and bits[2] else DEFAULT_BRANCH
        label = bits[3] if len(bits) > 3 and bits[3] else slug.split("/")[-1]
        out.append({"slug": slug, "column": column, "branch": branch,
                    "label": label})
    return out


def gh(args, timeout=GH_TIMEOUT):
    """`gh` with output captured, or None when it fails."""
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def green_runs(slug, branch, limit=10):
    """Ids of the newest successful runs on `branch`, newest first."""
    out = gh(["run", "list", "-R", slug, "-b", branch, "-s", "success",
              "-L", str(limit), "--json", "databaseId,headSha,url"])
    if not out:
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def report_from_artifact(slug, run_id, work):
    """test-report.json downloaded from one run, or None."""
    target = work / str(run_id)
    if gh(["run", "download", str(run_id), "-R", slug, "-n", ARTIFACT,
           "-D", str(target)]) is None:
        return None
    for path in target.rglob("test-report.json"):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None
    return None


def report_from_log(slug, run_id):
    """The report as the Emit step printed it into the run log, or None.

    This is the path that survives an artifact-quota blackout, which eats the
    upload silently and would otherwise leave the tiles frozen with no cause
    visible on the board.
    """
    out = gh(["run", "view", str(run_id), "-R", slug, "--log"])
    if not out:
        return None
    for line in out.splitlines():
        if '"tests_passed"' not in line or "{" not in line:
            continue
        try:
            report = json.loads(line[line.index("{"):])
        except ValueError:
            continue
        if "tests_passed" in report:
            return report
    return None


def newest_report(slug, branch, work):
    """(report, run) from the newest green run that published one, or (None, None)."""
    for run in green_runs(slug, branch):
        run_id = run.get("databaseId")
        if run_id is None:
            continue
        report = report_from_artifact(slug, run_id, work)
        if report is None:
            report = report_from_log(slug, run_id)
        if report and "tests_passed" in report:
            return report, run
    return None, None


def suites_section(title, report, logo):
    """The per-suite stats section, or None when the report names no suite."""
    suites = [s for s in report.get("suites", [])
              if isinstance(s, dict) and "name" in s and "tests" in s]
    if not suites:
        return None
    total = sum(int(s["tests"]) for s in suites)
    return {
        "kind": "stats",
        "icon": "\U0001f9ea",
        "title": title,
        "desc": "passing tests by suite, as the gate ran them",
        "count": f"{total:,} green",
        "items": [{"n": f"{int(s['tests']):,}", "label": s["name"], "tone": "go"}
                  for s in suites],
        "logo": logo,
    }


def coverage_section(title, report, logo, note):
    """The coverage bar chart, or None when the report carries no coverage.

    An absent chart is the honest state for a gate that does not measure
    coverage, and it must never render as a zero.
    """
    series = [{"label": name, "value": float(report[key]), "fill": "code"}
              for key, name in COVERAGE_METRICS if key in report]
    if not series:
        return None
    return {
        "kind": "barchart",
        "icon": "\U0001f9ea",
        "title": title,
        "desc": "percent of hand-written code exercised, test tree and dependency checkouts excluded",
        "series": series,
        "note": note,
        "logo": logo,
    }


def apply_source(board, source, work):
    """Patch one repo's results into `board`; returns a log line or None."""
    report, run = newest_report(source["slug"], source["branch"], work)
    if report is None:
        return None

    passed = int(report["tests_passed"])
    sha = str(report.get("sha", ""))[:7]
    url = run.get("url") if isinstance(run, dict) else None
    label = source["label"]

    # `match` carries the rename: a column that swift_tests.py used to fill
    # holds a "Tests written" tile, and this replaces it in place rather than
    # leaving both to contradict each other.
    lib.upsert_compare_tile(board, source["column"], "Tests green",
                            f"{passed:,}", tone="go", href=url, match="Tests")

    covered = report.get("coverage_lines_pct")
    if isinstance(covered, (int, float)):
        lib.upsert_compare_tile(board, source["column"], "Coverage (lines)",
                                f"{round(float(covered))}%", tone="none",
                                href=url, match="Coverage")

    suites = suites_section(f"{label} — tests by type", report, "swift")
    if suites:
        lib.upsert_section(board, suites["title"], suites)

    note = f"{passed:,} tests green at {sha}" if sha else f"{passed:,} tests green"
    coverage = coverage_section(f"{label} — test coverage", report, "swift", note)
    if coverage:
        lib.upsert_section(board, coverage["title"], coverage)

    covered_text = f"{round(float(covered))}% lines" if isinstance(covered, (int, float)) else "no coverage"
    return f"{source['column']}: {passed:,} green, {covered_text} @{sha or 'unknown'}"


def main():
    cfg = lib.read_roostrc()
    spec = cfg.get("ROOST_SWIFT_REPORT", "")
    board_dir = cfg.get("ROOST_SWIFT_REPORT_BOARD", "")
    if not spec or not board_dir:
        print("swift-report: ROOST_SWIFT_REPORT/ROOST_SWIFT_REPORT_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"swift-report: {board_path} not found — skipping")
        return 0

    sources = parse_sources(spec)
    if not sources:
        print("swift-report: ROOST_SWIFT_REPORT parsed to nothing — skipping")
        return 0

    import tempfile
    board = lib.load_board(board_path)
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        reports = [msg for msg in
                   (apply_source(board, s, work) for s in sources) if msg]
    if not reports:
        print("swift-report: no green run published a report — leaving board as-is")
        return 0

    lib.save_board(board_path, board)
    for msg in reports:
        print(f"swift-report: {msg}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # never break a status push
        print(f"swift-report: non-fatal error: {error}")
        sys.exit(0)
