#!/usr/bin/env python3
"""Unit tests for repo_stats.patch_coverage_chart — the rich-coverage board
patch. The gh-driven fetch path isn't exercised here; these pin the pure
board transformation: bars matched by label, note rebuilt (zero-count +
worst offenders), unknown labels and foreign sections untouched, and the
no-matching-section / old-report shapes.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bin", "collect"))
import repo_stats

COVD = {
    "lines_pct": 63.04, "statements_pct": 61.82,
    "functions_pct": 55.0, "branches_pct": 50.0,
    "files_total": 312, "files_zero": 41,
    "worst": [
        {"file": "src/renderer/views/Big.tsx", "uncovered_lines": 400, "lines_pct": 20},
        {"file": "src/main/services/Zero.ts", "uncovered_lines": 200, "lines_pct": 0},
        {"file": "src/shared/tiny.ts", "uncovered_lines": 10, "lines_pct": 0},
        {"file": "src/shared/fourth.ts", "uncovered_lines": 5, "lines_pct": 50},
    ],
}


def chart(series_labels=("Lines", "Statements", "Functions", "Branches")):
    return {"kind": "barchart", "title": "Test Coverage",
            "note": "stale hand-written note",
            "series": [{"label": l, "value": 1.0, "fill": "code"}
                       for l in series_labels]}


class PatchCoverageChartTest(unittest.TestCase):
    def test_bars_patched_by_label(self):
        board = {"sections": [chart()]}
        self.assertTrue(repo_stats.patch_coverage_chart(board, COVD, 3902))
        values = {b["label"]: b["value"] for b in board["sections"][0]["series"]}
        self.assertEqual(values, {"Lines": 63.0, "Statements": 61.8,
                                  "Functions": 55.0, "Branches": 50.0})

    def test_note_has_counts_and_top3_worst(self):
        board = {"sections": [chart()]}
        repo_stats.patch_coverage_chart(board, COVD, 3902)
        note = board["sections"][0]["note"]
        self.assertIn("3,902 tests green", note)
        self.assertIn("41 of 312 files at 0%", note)
        self.assertIn("Big.tsx (400), Zero.ts (200), tiny.ts (10)", note)
        self.assertNotIn("fourth.ts", note)  # top-3 only

    def test_unknown_label_and_missing_metric_untouched(self):
        board = {"sections": [chart(("Lines", "Mutation"))]}
        covd = {"lines_pct": 63.04, "files_total": 312, "files_zero": 41}
        repo_stats.patch_coverage_chart(board, covd, 10)
        lines, mutation = board["sections"][0]["series"]
        self.assertEqual(lines["value"], 63.0)
        self.assertEqual(mutation["value"], 1.0)
        self.assertNotIn("most uncovered", board["sections"][0]["note"])

    def test_other_sections_never_touched(self):
        other = {"kind": "barchart", "title": "Codebase",
                 "series": [{"label": "Lines", "value": 9.0}]}
        board = {"sections": [copy.deepcopy(other), chart()]}
        self.assertTrue(repo_stats.patch_coverage_chart(board, COVD, 1))
        self.assertEqual(board["sections"][0], other)

    def test_no_matching_section_returns_false(self):
        board = {"sections": [{"kind": "compare", "columns": []}]}
        before = copy.deepcopy(board)
        self.assertFalse(repo_stats.patch_coverage_chart(board, COVD, 1))
        self.assertEqual(board, before)


TBT = {"unit": 5830, "integration": 132, "e2e": None,
       "unit_files": 315, "integration_files": 8}


class TestTypeSectionsTest(unittest.TestCase):
    def test_stat_tiles_and_donut_built(self):
        stats, pie = repo_stats.build_test_type_sections(TBT)
        self.assertEqual(stats["kind"], "stats")
        self.assertEqual(stats["title"], "Tests by type")
        tiles = {t["label"]: t["n"] for t in stats["items"]}
        self.assertEqual(tiles, {"Unit": "5,830", "Integration": "132", "E2E": "n/a"})
        self.assertEqual(pie["kind"], "pie")
        self.assertEqual(pie["title"], "Test mix")
        self.assertEqual([s["value"] for s in pie["slices"]], [5830, 132])
        self.assertIn("315 files", pie["note"])
        self.assertIn("not yet run in CI", pie["note"])

    def test_e2e_number_when_present(self):
        stats, pie = repo_stats.build_test_type_sections({**TBT, "e2e": 11})
        e2e = next(t for t in stats["items"] if t["label"] == "E2E")
        self.assertEqual(e2e["n"], "11")
        self.assertEqual(e2e["tone"], "go")

    def test_patch_upserts_both_sections(self):
        board = {"sections": [{"kind": "compare", "columns": [{"items": []}]}]}
        self.assertTrue(repo_stats.patch_test_types(board, TBT))
        titles = [s.get("title") for s in board["sections"]]
        self.assertIn("Tests by type", titles)
        self.assertIn("Test mix", titles)
        # Idempotent: a second run replaces rather than duplicates.
        repo_stats.patch_test_types(board, {**TBT, "unit": 6000})
        self.assertEqual(titles.count("Tests by type"),
                         [s.get("title") for s in board["sections"]].count("Tests by type"))
        stats = next(s for s in board["sections"] if s.get("title") == "Tests by type")
        self.assertEqual(stats["items"][0]["n"], "6,000")

    def test_old_report_without_breakdown_is_noop(self):
        board = {"sections": [{"kind": "compare", "columns": [{"items": []}]}]}
        before = copy.deepcopy(board)
        self.assertFalse(repo_stats.patch_test_types(board, {}))
        self.assertEqual(board, before)


REPORT = {"sha": "abc1234def0", "branch": "dev",
          "tests_passed": 5410, "tests_total": 5432,
          "e2e": {"passed": 5, "failed": 1, "flaky": 1, "skipped": 0,
                  "total": 7, "green": False, "duration_ms": 31000}}


class TestResultsSectionTest(unittest.TestCase):
    def test_full_report_builds_all_tiles(self):
        sec = repo_stats.build_test_results_section(REPORT)
        self.assertEqual(sec["kind"], "stats")
        self.assertEqual(sec["title"], "Test results")
        self.assertEqual(sec["count"], "1 e2e failing")
        self.assertIn("dev@abc1234", sec["desc"])
        tiles = {t["label"]: (t["n"], t["tone"]) for t in sec["items"]}
        self.assertEqual(tiles, {
            "Passed": ("5,410", "go"),
            "Skipped / todo": ("22", "done"),
            "E2E passed": ("5/7", "err"),
            "E2E failed": ("1", "err"),
            "E2E flaky": ("1", "you"),
        })

    def test_green_e2e_gets_go_tone_and_no_failure_tiles(self):
        green = {**REPORT, "e2e": {"passed": 7, "failed": 0, "flaky": 0,
                                   "skipped": 0, "total": 7, "green": True}}
        sec = repo_stats.build_test_results_section(green)
        self.assertEqual(sec["count"], "all green")
        tiles = {t["label"]: t["tone"] for t in sec["items"]}
        self.assertEqual(tiles.get("E2E passed"), "go")
        self.assertNotIn("E2E failed", tiles)
        self.assertNotIn("E2E flaky", tiles)

    def test_no_e2e_degrades_to_vitest_only(self):
        sec = repo_stats.build_test_results_section(
            {"sha": "abc1234", "branch": "main",
             "tests_passed": 100, "tests_total": 100})
        self.assertEqual(sec["count"], "all green")
        self.assertIn("no e2e in this run", sec["desc"])
        labels = [t["label"] for t in sec["items"]]
        self.assertEqual(labels, ["Passed", "Skipped / todo"])
        self.assertEqual(sec["items"][1]["n"], "0")

    def test_old_report_without_total_omits_skipped(self):
        sec = repo_stats.build_test_results_section({"tests_passed": 42})
        self.assertEqual([t["label"] for t in sec["items"]], ["Passed"])

    def test_patch_seeds_after_compare_and_replaces(self):
        board = {"sections": [{"kind": "compare", "columns": [{"items": []}]},
                              chart()]}
        self.assertTrue(repo_stats.patch_test_results(board, REPORT))
        self.assertEqual(board["sections"][1]["title"], "Test results")
        repo_stats.patch_test_results(board, {**REPORT, "tests_passed": 6000})
        titles = [s.get("title") for s in board["sections"]]
        self.assertEqual(titles.count("Test results"), 1)
        sec = board["sections"][1]
        self.assertEqual(sec["items"][0]["n"], "6,000")

    def test_report_without_headline_count_is_noop(self):
        board = {"sections": [{"kind": "compare", "columns": [{"items": []}]}]}
        before = copy.deepcopy(board)
        self.assertFalse(repo_stats.patch_test_results(board, {"sha": "x"}))
        self.assertEqual(board, before)


class ReportAgeHoursTest(unittest.TestCase):
    def test_missing_or_unparseable_is_none(self):
        self.assertIsNone(repo_stats.report_age_hours({}))
        self.assertIsNone(repo_stats.report_age_hours({"generated_at": ""}))
        self.assertIsNone(repo_stats.report_age_hours({"generated_at": "not-a-date"}))

    def test_old_report_reads_many_hours(self):
        age = repo_stats.report_age_hours({"generated_at": "2020-01-01T00:00:00Z"})
        self.assertIsNotNone(age)
        self.assertGreater(age, 4)  # decades old, well past the stale threshold

    def test_fresh_report_reads_near_zero(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        age = repo_stats.report_age_hours({"generated_at": now})
        self.assertIsNotNone(age)
        self.assertLess(age, 1)  # minutes-old report is not stale


class LocalReportTest(unittest.TestCase):
    """The runner-local state-file source — what survives GitHub
    artifact-quota blackouts when CI and the board writer share a machine."""

    def _write(self, d, name, payload):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(payload)
        return p

    def test_reads_branch_keyed_file(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "dev-test-report.json",
                        json.dumps({"branch": "dev", "tests_passed": 5}))
            r = repo_stats.local_report(d, "dev")
            self.assertEqual(r["tests_passed"], 5)

    def test_slashed_branch_is_flattened(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "112-merge-test-report.json",
                        json.dumps({"branch": "112/merge", "tests_passed": 3}))
            self.assertIsNotNone(repo_stats.local_report(d, "112/merge"))

    def test_wrong_branch_missing_garbage_or_unset_dir(self):
        import json, tempfile
        self.assertIsNone(repo_stats.local_report("", "dev"))
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(repo_stats.local_report(d, "dev"))  # missing
            self._write(d, "dev-test-report.json", "{not json")
            self.assertIsNone(repo_stats.local_report(d, "dev"))  # garbage
            self._write(d, "dev-test-report.json",
                        json.dumps({"branch": "main", "tests_passed": 5}))
            self.assertIsNone(repo_stats.local_report(d, "dev"))  # mis-keyed


class PreferReportTest(unittest.TestCase):
    def test_local_wins_when_gh_absent_or_older(self):
        local = {"generated_at": "2026-01-02T00:00:00Z"}
        gh = {"generated_at": "2026-01-01T00:00:00Z"}
        self.assertEqual(repo_stats.prefer_report(None, local), (local, True))
        self.assertEqual(repo_stats.prefer_report(gh, local), (local, True))
        # tie goes local — the same run wrote both
        self.assertEqual(repo_stats.prefer_report(local, local), (local, True))

    def test_gh_wins_when_fresher_or_local_absent(self):
        local = {"generated_at": "2026-01-01T00:00:00Z"}
        gh = {"generated_at": "2026-01-02T00:00:00Z"}
        self.assertEqual(repo_stats.prefer_report(gh, local), (gh, False))
        self.assertEqual(repo_stats.prefer_report(gh, None), (gh, False))
        # local without a readable timestamp never outranks a dated gh report
        self.assertEqual(repo_stats.prefer_report(gh, {}), (gh, False))


class E2ECarryForwardTest(unittest.TestCase):
    """A null e2e means "not measured by this run" — the tile must keep its
    last-good number, not reset to n/a."""

    def _board_with_e2e(self, n):
        board = {"sections": [{"kind": "compare", "columns": [{"items": []}]}]}
        repo_stats.patch_test_types(board, {**TBT, "e2e": n})
        return board

    def test_null_e2e_keeps_last_good_number(self):
        board = self._board_with_e2e(11)
        repo_stats.patch_test_types(board, {**TBT, "unit": 6000, "e2e": None})
        stats = next(s for s in board["sections"] if s.get("title") == "Tests by type")
        tiles = {t["label"]: t["n"] for t in stats["items"]}
        self.assertEqual(tiles["E2E"], "11")
        self.assertEqual(tiles["Unit"], "6,000")

    def test_null_e2e_on_na_board_stays_na(self):
        board = self._board_with_e2e(None)
        repo_stats.patch_test_types(board, {**TBT, "e2e": None})
        stats = next(s for s in board["sections"] if s.get("title") == "Tests by type")
        e2e = next(t for t in stats["items"] if t["label"] == "E2E")
        self.assertEqual(e2e["n"], "n/a")

    def test_real_number_still_overrides(self):
        board = self._board_with_e2e(11)
        repo_stats.patch_test_types(board, {**TBT, "e2e": 12})
        stats = next(s for s in board["sections"] if s.get("title") == "Tests by type")
        e2e = next(t for t in stats["items"] if t["label"] == "E2E")
        self.assertEqual(e2e["n"], "12")


if __name__ == "__main__":
    unittest.main()
