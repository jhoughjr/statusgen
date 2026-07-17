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

When the report carries a `tests_by_type` object (unit/integration counts, e2e
null until Playwright joins CI), also self-seeds two sections — a "Tests by
type" stat-tile row and a "Test mix" donut — upserted so a board that never had
them gets them without a hand-edit. Old reports without the object leave any
existing sections with their last-good numbers.

Also self-seeds a "Test results" stat row right under the compare headline:
passed / skipped counts, plus e2e pass/fail/flaky tiles when the run folded
an e2e report in (e2e is continue-on-error in CI, so its failures reach the
report of a green run — the only red the report can carry). Provenance (CI
branch@sha) rides in the section desc.

Config (~/.roostrc):
  ROOST_STATS_BOARD=clauffice                          # board dir under the status site
  ROOST_STATS_GH_REPO=Austin-MacWorks/Phoenix-Electron # repo slug for gh
  ROOST_STATS_CI_BRANCH=main                           # branch whose CI to trust (default main)
  ROOST_STATS_LABEL=Phoenix                            # optional stamp label
  ROOST_STATS_STATE_DIR=$HOME/.ci-state/phoenix        # optional runner-local report dir

When ROOST_STATS_STATE_DIR is set and the board writer shares a machine with a
CI runner, the collector also reads `<branch>-test-report.json` from that dir —
the copy CI's emit/merge steps drop locally on every run. Whichever source is
fresher (by `generated_at`) wins; the local copy is what survives GitHub
artifact-quota blackouts, which silently eat the artifact upload and would
otherwise drop the collector back to the pre-e2e log-line fallback.

Non-fatal by contract: no config → skip; any failure → board untouched (last
good numbers stay, with their original stamp date showing the staleness), exit 0.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

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


def local_report(state_dir, branch):
    """test-report.json from the runner-local state dir — the copy CI's
    emit/merge steps drop on this machine (`<branch>-test-report.json`,
    slashes flattened, same naming as the scripts). Returns dict or None;
    never raises. Trusted only for its own branch: a mis-keyed or hand-copied
    file must not feed another branch's tiles."""
    if not state_dir:
        return None
    path = pathlib.Path(state_dir) / (branch.replace("/", "-") + "-test-report.json")
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if "tests_passed" not in report:
        return None
    if str(report.get("branch") or branch) != branch:
        return None
    return report


def prefer_report(gh_report, local):
    """Pick between the gh-fetched report and the runner-local one: freshest
    `generated_at` wins (ties go local — same runs write both, and local can't
    be quota-eaten; a second runner elsewhere can still make gh newer).
    Returns (report, used_local)."""
    if local is None:
        return gh_report, False
    if gh_report is None:
        return local, True
    l_age, g_age = report_age_hours(local), report_age_hours(gh_report)
    if l_age is not None and (g_age is None or l_age <= g_age):
        return local, True
    return gh_report, False


def report_age_hours(report):
    """Hours since the report's `generated_at`, or None if absent/unparseable.
    Staleness uses this so a report that merely trails a fast-moving branch by a
    commit or two (normal CI lag on every push) isn't cried as stale — only a
    genuinely OLD newest-green report (a red streak, stalled reporting) is."""
    raw = str(report.get("generated_at", "")).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def head_sha(slug, branch):
    """Current HEAD sha (7-char) of `branch`, or None. Best-effort — a failure
    just means we can't judge staleness, never that the board is touched."""
    out = subprocess.run(
        ["gh", "api", f"repos/{slug}/commits/{branch}", "--jq", ".sha"],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.strip()[:7]


def build_test_type_sections(tbt):
    """From the report's `tests_by_type` object, build the "Tests by type" stat
    tiles and the "Test mix" donut. Unit and integration both run under vitest,
    so both carry real numbers; e2e is Playwright, runs on dev pushes only, and
    is null in reports from runs that never measured it — a null tile reads
    "n/a" (a reported 0 would look like a passing e2e suite) and gets no pie
    slice. Returns (stats_section, pie_section)."""
    unit = int(tbt.get("unit") or 0)
    integ = int(tbt.get("integration") or 0)
    e2e = tbt.get("e2e")
    uf, ifi = tbt.get("unit_files"), tbt.get("integration_files")

    tiles = [
        {"n": f"{unit:,}", "label": "Unit", "tone": "go"},
        {"n": f"{integ:,}", "label": "Integration", "tone": "you"},
        {"n": "n/a" if e2e is None else f"{int(e2e):,}",
         "label": "E2E", "tone": "wip" if e2e is None else "go"},
    ]
    stats_section = {
        "kind": "stats", "icon": "🧪", "title": "Tests by type",
        "desc": ("passing vitest tests by suite · e2e (Playwright) pending CI"
                 if e2e is None else
                 "passing tests by suite · e2e = Playwright on dev CI"),
        "count": f"{unit + integ:,} green",
        "items": tiles,
    }

    note_bits = []
    if uf is not None:
        note_bits.append(f"{unit:,} unit across {uf} files")
    else:
        note_bits.append(f"{unit:,} unit")
    if ifi is not None:
        note_bits.append(f"{integ:,} integration across {ifi} files")
    else:
        note_bits.append(f"{integ:,} integration")
    e2e_note = (" E2E (Playwright) not yet run in CI." if e2e is None
                else f" E2E: {int(e2e):,} passing (Playwright, dev CI).")
    note = "Passing tests by suite: " + ", ".join(note_bits) + "." + e2e_note
    slices = [
        {"label": "Unit", "value": unit, "tone": "go"},
        {"label": "Integration", "value": integ, "tone": "you"},
    ]
    if e2e is not None:
        slices.append({"label": "E2E", "value": int(e2e), "tone": "wip"})
    pie_section = {
        "kind": "pie", "icon": "🧪", "title": "Test mix",
        "slices": slices,
        "note": note,
    }
    return stats_section, pie_section


def last_good_e2e(board):
    """The numeric value of the board's current E2E tile in "Tests by type",
    or None when absent / still "n/a". Feeds the null-e2e carry-forward."""
    for s in board.get("sections", []):
        if s.get("kind") != "stats" or s.get("title") != "Tests by type":
            continue
        for tile in s.get("items", []):
            if tile.get("label") == "E2E":
                raw = str(tile.get("n", "")).replace(",", "")
                return int(raw) if raw.isdigit() else None
    return None


def patch_test_types(board, tbt):
    """Seed/refresh the "Tests by type" tiles and "Test mix" donut from the
    report's `tests_by_type` object. Upserts (self-seeds on first run), so a
    board that has never carried them gets them without a hand-edit. A no-op
    that returns False for old reports without the breakdown — the sections,
    if already present, keep their last-good numbers. A report whose e2e is
    null means "not measured by this run" (PR/main runs, or a dev run that died
    before Playwright) — carry the board's last-good E2E number forward instead
    of resetting the tile to n/a. Returns True when patched."""
    if not tbt or ("unit" not in tbt and "integration" not in tbt):
        return False
    if tbt.get("e2e") is None:
        carry = last_good_e2e(board)
        if carry is not None:
            tbt = {**tbt, "e2e": carry}
    stats_sec, pie_sec = build_test_type_sections(tbt)
    # upsert inserts each right after the compare section, so the LAST upsert
    # lands first — do the donut first, tiles second, to read tiles → donut.
    lib.upsert_section(board, "Test mix", pie_sec, after_kind="compare")
    lib.upsert_section(board, "Tests by type", stats_sec, after_kind="compare")
    return True


def build_test_results_section(report):
    """From the report's headline counts (and its `e2e` object when the run
    folded one in), build the "Test results" stat row: passed, skipped, and —
    the only red CI can report today — how e2e did. Reports publish only from
    green runs (the vitest step gates the emit step), so there is no vitest
    "failed" tile to build: a failing unit test means no report at all, which
    the STALE flag already surfaces. E2E runs with continue-on-error, so its
    failures DO reach the report — those get the err tone."""
    passed = int(report["tests_passed"])
    total = report.get("tests_total")
    e2e = report.get("e2e") or {}
    sha = str(report.get("sha", ""))[:7]
    branch = str(report.get("branch", "")).strip() or "CI"

    items = [{"n": f"{passed:,}", "label": "Passed", "tone": "go"}]
    if total is not None:
        skipped = max(int(total) - passed, 0)
        items.append({"n": f"{skipped:,}", "label": "Skipped / todo",
                      "tone": "done"})

    failing = 0
    if e2e.get("total") is not None:
        e2e_failed = int(e2e.get("failed") or 0)
        e2e_flaky = int(e2e.get("flaky") or 0)
        green = bool(e2e.get("green", e2e_failed == 0))
        items.append({"n": f"{int(e2e.get('passed') or 0)}/{int(e2e['total'])}",
                      "label": "E2E passed", "tone": "go" if green else "err"})
        if e2e_failed:
            items.append({"n": f"{e2e_failed:,}", "label": "E2E failed",
                          "tone": "err"})
        if e2e_flaky:
            items.append({"n": f"{e2e_flaky:,}", "label": "E2E flaky",
                          "tone": "you"})
        if not green:
            failing = e2e_failed or 1

    desc = f"from CI {branch}@{sha}" if sha else "from CI"
    if e2e.get("total") is None:
        desc += " · no e2e in this run"
    return {
        "kind": "stats", "icon": "✅", "title": "Test results",
        "desc": desc,
        "count": "all green" if not failing else f"{failing} e2e failing",
        "items": items,
    }


def patch_test_results(board, report):
    """Upsert the "Test results" row right after the compare headline (above
    the tests-by-type tiles — main() calls this after patch_test_types, and
    the last upsert lands first). Boards self-seed on first run. A report
    without the headline count (shouldn't happen — tests_passed is required
    upstream) is a no-op. Returns True when patched."""
    if "tests_passed" not in report:
        return False
    lib.upsert_section(board, "Test results",
                       build_test_results_section(report),
                       after_kind="compare")
    return True


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
    report, used_local = prefer_report(
        report, local_report(cfg.get("ROOST_STATS_STATE_DIR", ""), branch))
    if used_local:
        run_id = "local-state"
        print(f"repo-stats: runner-local state report is freshest for {branch} — using it")
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

    # Wire the once-hardcoded "Tests · N files" tile to the real test-file
    # count from the CI report (it used to read a stale "346 · 94 files").
    tf = report.get("test_files")
    if tf is not None:
        lib.set_compare_tile(board, "Tests ·", f"{int(tf):,}", label="Test files")

    covd = report.get("coverage") or {}
    chart = patch_coverage_chart(board, covd, count) if covd else False

    tbt = report.get("tests_by_type") or {}
    types = patch_test_types(board, tbt)

    # After patch_test_types so this upsert lands first: compare → Test
    # results → Tests by type → Test mix.
    results = patch_test_results(board, report)

    if not (patched or chart or types or results):
        print("repo-stats: nothing to patch — no compare, Test Coverage, "
              "tests_by_type, or test results")
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
    behind = bool(head and sha and head != sha)
    # Only cry stale when the newest green report is genuinely OLD — a busy
    # branch sits a commit or two ahead of the last green run constantly, and
    # that lag isn't staleness. Default 4h; tune via ROOST_STATS_STALE_HOURS.
    # If the report has no readable timestamp, fall back to behind-HEAD.
    try:
        stale_hours = float(cfg.get("ROOST_STATS_STALE_HOURS", "4") or 4)
    except ValueError:
        stale_hours = 4.0
    age_h = report_age_hours(report)
    stale = behind and (age_h is None or age_h > stale_hours)
    stale_note = ""
    if stale:
        aged = f", {age_h:.0f}h old" if age_h is not None else ""
        stale_note = f" · ⚠ STALE — {branch} is at {head}, numbers as of {sha}{aged}"
    # Always write the CURRENT staleness onto the tiles — set when stale, and
    # clear a flag a past (stricter) run left behind when we're now fresh, so
    # the ⚠ badge actually goes away instead of sticking forever.
    for s in board.get("sections", []):
        if s.get("kind") == "compare":
            for tile in s["columns"][0]["items"]:
                if str(tile.get("label", "")).startswith(("Tests green", "Coverage")):
                    if stale:
                        tile["stale"] = True
                    else:
                        tile.pop("stale", None)
        elif s.get("kind") == "stats" and s.get("title") == "Test results":
            # Freshly upserted above (no lingering flags to clear) — but the
            # fresh numbers still come from an old report when stale.
            for tile in s.get("items", []):
                if stale:
                    tile["stale"] = True

    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    name = cfg.get("ROOST_STATS_LABEL") or slug.split("/")[-1]
    board["stamp"] = (f"Updated {ts} — {name} {count:,} tests green · {cov}% coverage "
                      f"· CI {branch}@{sha}{extra} · +{delta:,} added (7d){stale_note}")

    lib.save_board(board_path, board)
    print(f"repo-stats: tests={count} coverage={cov}% chart={'patched' if chart else 'n/a'} "
          f"types={'patched' if types else 'n/a'} results={'patched' if results else 'n/a'} "
          f"(CI {branch}@{sha}, run {run_id}, Δ+{delta} vs 7d-ago {base}){extra and ' |' + extra}"
          f"{' STALE vs HEAD ' + head if stale else ''}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"repo-stats: non-fatal error: {e}")
        sys.exit(0)
