#!/usr/bin/env python3
"""test_detail.py — a Test results detail page, and links from the tiles to it.

A number on a board is the start of a question: "6,591 passed — which ones?
what's failing? since when?" The board could only answer the first half, so
this builds <slug>/tests/ from the same test-report.json the tiles come from,
and makes the tiles link to it.

Runs after repo_stats (which owns the "Test results" section and upserts it
wholesale) and re-applies the hrefs each push, so the link can't be lost to a
collector rewrite.

Config (~/.roostrc, all shared with repo_stats — nothing new to set up):
  ROOST_STATS_BOARD       board slug under the status site
  ROOST_STATS_STATE_DIR   dir of <branch>-test-report.json files
  ROOST_STATS_CI_BRANCH   branch whose report drives the page (default: dev)
  ROOST_STATS_GH_REPO     owner/repo, for the "view CI run" links
  ROOST_STATS_LABEL       display name (default: the board slug)

No state dir → print a skip note and exit 0, like every collector.

The trend reads every *-test-report.json in the state dir, so it picks up the
per-run archive CI leaves behind. Reports without a `generated_at` are dropped
rather than guessed at — an undated point can't be placed on a time axis.

`failures` (added by Phoenix-Electron's emit-report.sh / merge-e2e-report.sh) is
optional: without it the page shows counts and the section says so, rather than
implying nothing failed.
"""
import json
import os
import pathlib
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

TREND_MAX = 20        # points on the trend charts
WORST_MAX = 12        # rows in the least-covered table
FAIL_MAX = 40         # failing specs listed


def load_reports(state_dir):
    """(current-by-branch dict, [dated reports oldest-first]) from the state dir."""
    d = pathlib.Path(os.path.expanduser(state_dir))
    if not d.is_dir():
        return {}, []
    by_branch, dated = {}, []
    for p in sorted(d.glob("*-test-report.json")):
        try:
            r = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        r["_name"] = p.name[: -len("-test-report.json")]
        by_branch[r["_name"]] = r
        if r.get("generated_at"):
            dated.append(r)
    dated.sort(key=lambda r: r["generated_at"])
    return by_branch, dated


def commit_url(repo, sha):
    """A commit's checks page — derivable from the sha alone, unlike a run id,
    which the report doesn't carry. Lands on the run that produced these
    numbers."""
    return f"https://github.com/{repo}/commit/{sha}/checks" if repo and sha else None


def short(sha):
    return (sha or "")[:7]


def pct(v):
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "—"


def hero(report, run_url):
    """Top tile row — the same headline numbers as the board, plus a link out."""
    e2e = report.get("e2e") or {}
    passed = report.get("tests_passed")
    total = report.get("tests_total")
    skipped = (total - passed) if isinstance(total, int) and isinstance(passed, int) else None
    items = [
        {"n": f"{passed:,}" if isinstance(passed, int) else "—", "label": "Passed", "tone": "go"},
        {"n": f"{skipped:,}" if isinstance(skipped, int) else "—",
         "label": "Skipped / todo", "tone": "done"},
        {"n": f"{report.get('test_files', 0):,}", "label": "Test files", "tone": "none"},
        {"n": pct(report.get("coverage_lines_pct")), "label": "Coverage (lines)", "tone": "none"},
    ]
    if e2e:
        failed = e2e.get("failed") or 0
        items.append({"n": f"{e2e.get('passed', 0)}/{e2e.get('total', 0)}",
                      "label": "E2E passed", "tone": "go" if not failed else "err"})
    if run_url:
        for it in items:
            it["href"] = run_url
    return {"kind": "stats", "items": items}


def by_type_section(report):
    t = report.get("tests_by_type") or {}
    if not t:
        return None
    items = [
        {"n": f"{t.get('unit', 0):,}", "label": f"Unit · {t.get('unit_files', 0)} files", "tone": "go"},
        {"n": f"{t.get('integration', 0):,}",
         "label": f"Integration · {t.get('integration_files', 0)} files", "tone": "srv"},
    ]
    e2e = t.get("e2e")
    items.append({"n": "—" if e2e is None else f"{e2e:,}", "label": "E2E", "tone": "wip"})
    return {"kind": "stats", "icon": "🧪", "title": "By type",
            "desc": "passing tests, split by suite kind", "items": items}


def e2e_section(report):
    e = report.get("e2e")
    if not e:
        return None
    secs = (e.get("duration_ms") or 0) / 1000
    return {"kind": "stats", "icon": "🎭", "title": "End-to-end",
            "desc": f"Playwright, {secs:.0f}s" if secs else "Playwright",
            "count": "green" if e.get("green") else f"{e.get('failed', 0)} failing",
            "items": [
                {"n": str(e.get("passed", 0)), "label": "Passed", "tone": "go"},
                {"n": str(e.get("failed", 0)), "label": "Failed",
                 "tone": "err" if e.get("failed") else "done"},
                {"n": str(e.get("flaky", 0)), "label": "Flaky", "tone": "you"},
                {"n": str(e.get("skipped", 0)), "label": "Skipped", "tone": "done"},
            ]}


def failures_section(report, run_url):
    """Named failures when the report carries them; an honest note when it
    doesn't. An empty list here would read as 'nothing failed', which is a
    different claim from 'this build didn't record what failed'."""
    fails = report.get("failures")
    if fails is None:
        counted = (report.get("e2e") or {}).get("failed") or 0
        if not counted:
            return None
        return {"kind": "banner", "tone": "you",
                "text": f"{counted} failing test(s) this run, but this report predates "
                        "per-test detail — open the CI run for the names."}
    if not fails:
        return {"kind": "banner", "tone": "go", "text": "No failing tests in this run."}
    lines = []
    for f in fails[:FAIL_MAX]:
        line = {"status": f.get("type", "test"), "tone": "err",
                "text": f.get("title") or f.get("file") or "(unnamed)"}
        if f.get("file") and f.get("title"):
            line["meta"] = f"· {f['file']}"
        if run_url:
            line["href"] = run_url
        lines.append(line)
    sec = {"kind": "console", "icon": "🔴", "title": "Failing tests",
           "count": f"{len(fails)} failing", "lines": lines}
    if len(fails) > FAIL_MAX:
        sec["desc"] = f"showing {FAIL_MAX} of {len(fails)}"
    return sec


def coverage_section(report):
    c = report.get("coverage") or {}
    worst = c.get("worst") or []
    if not worst:
        return None
    rows = [[w.get("file", ""), f"{w.get('uncovered_lines', 0):,}", pct(w.get("lines_pct"))]
            for w in worst[:WORST_MAX]]
    return {"kind": "table", "icon": "📉", "title": "Least covered",
            "count": f"{c.get('files_zero', 0)} files at 0%",
            "desc": "ranked by uncovered lines — the biggest wins first, "
                    "not the lowest percentages",
            "columns": ["File", "Uncovered lines", "Line coverage"], "rows": rows}


def trend_sections(dated):
    """Passing-test and coverage trends over the archived reports."""
    pts = dated[-TREND_MAX:]
    if len(pts) < 2:
        return []
    def label(r):
        return (r.get("generated_at") or "")[5:10] + " " + short(r.get("sha"))[:4]
    out = [{
        "kind": "barchart", "icon": "📈", "title": "Tests over time",
        "desc": f"passing tests, last {len(pts)} recorded runs",
        "series": [{"label": label(r), "value": r.get("tests_passed") or 0, "fill": "code"}
                   for r in pts],
        "note": "Each bar is one CI run that published a report. Bars are not "
                "evenly spaced in time — runs happen when pushes do.",
    }]
    cov = [r for r in pts if isinstance(r.get("coverage_lines_pct"), (int, float))]
    if len(cov) >= 2:
        out.append({
            "kind": "barchart", "icon": "🛡️", "title": "Coverage over time",
            "desc": f"line coverage, last {len(cov)} runs that measured it",
            "series": [{"label": label(r), "value": round(r["coverage_lines_pct"], 1),
                        "fill": "gen"} for r in cov],
        })
    return out


def build_detail(report, dated, label, run_url):
    stamp_sha = short(report.get("sha"))
    branch = report.get("branch") or "?"
    gen = (report.get("generated_at") or "")[:16].replace("T", " ")
    sections = [hero(report, run_url)]
    for s in (by_type_section(report), e2e_section(report),
              failures_section(report, run_url), coverage_section(report)):
        if s:
            sections.append(s)
    sections.extend(trend_sections(dated))
    board = {
        "title": f"{label} — Test results",
        "eyebrow": "status.jimmyhoughjr.net",
        "stamp": f"From CI {branch}@{stamp_sha}"
                 + (f", reported {gen} UTC" if gen else "")
                 + " — the same test-report.json the board's tiles read.",
        "links": [{"label": "← Board", "href": "../"}],
        "sections": sections,
    }
    if run_url:
        board["links"].append({"label": "View CI run →", "href": run_url})
    return board


def write_shell(site, rel_dir, page_title):
    """Thin renderer shell so <site>/<rel_dir>/ is browsable; sync-renderer
    stamps the asset version on deploy. Same pattern as history.py."""
    template = pathlib.Path(__file__).resolve().parents[2] / "renderer" / "board.template.html"
    d = pathlib.Path(site) / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(template.read_text().replace("PLACEHOLDER", page_title))


def link_board_tiles(board, href, run_url):
    """Point the board's Test-results tiles at the detail page, and the compare
    headline's test tiles too. Re-applied every push because repo_stats upserts
    that section wholesale."""
    touched = 0
    for s in board.get("sections", []):
        if s.get("kind") == "stats" and s.get("title") == "Test results":
            s["href"] = href
            for it in s.get("items", []):
                it["href"] = href
            touched += 1
        elif s.get("kind") == "compare":
            for col in s.get("columns", []):
                for it in col.get("items", []):
                    lbl = str(it.get("label", ""))
                    # Deliberately not "Test files": that tile is the SERVER
                    # column's count, and this page is the client's suite.
                    if lbl.startswith(("Tests green", "Coverage")):
                        it["href"] = href
                        touched += 1
                    elif lbl.startswith("CI build") and run_url:
                        it["href"] = run_url
                        touched += 1
    return touched


def main():
    cfg = lib.read_roostrc()
    state_dir = cfg.get("ROOST_STATS_STATE_DIR")
    slug = cfg.get("ROOST_STATS_BOARD")
    if not state_dir or not slug:
        print("test-detail: ROOST_STATS_STATE_DIR/ROOST_STATS_BOARD not set — skipping")
        return 0

    by_branch, dated = load_reports(state_dir)
    branch = cfg.get("ROOST_STATS_CI_BRANCH", "dev")
    report = by_branch.get(branch.replace("/", "-"))
    if not report:
        print(f"test-detail: no {branch}-test-report.json in {state_dir} — skipping")
        return 0

    site = lib.site_dir(cfg)
    board_path = site / slug / "board.json"
    if not board_path.exists():
        print(f"test-detail: {board_path} not found — skipping")
        return 0

    label = cfg.get("ROOST_STATS_LABEL", slug)
    run_url = commit_url(cfg.get("ROOST_STATS_GH_REPO"), report.get("sha"))

    detail = build_detail(report, dated, label, run_url)
    out = site / slug / "tests"
    out.mkdir(parents=True, exist_ok=True)
    lib.save_board(out / "board.json", detail)
    write_shell(site, f"{slug}/tests", f"{label} — Test results")

    board = lib.load_board(board_path)
    touched = link_board_tiles(board, "tests/", run_url)
    lib.save_board(board_path, board)

    charted = min(len(dated), TREND_MAX)
    print(f"test-detail: {slug}/tests/ built from {branch}@{short(report.get('sha'))} "
          f"({len(detail['sections'])} sections, {charted} of {len(dated)} reports charted); "
          f"linked {touched} tiles")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"test-detail: non-fatal error: {e}")
        sys.exit(0)
