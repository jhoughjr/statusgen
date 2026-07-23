#!/usr/bin/env python3
"""Unit tests for collect/test_detail.py — the Test results detail page.

The behaviour worth pinning down is what the page claims when the report is
incomplete. "No failing tests" and "this build didn't record which tests
failed" are different statements, and a page that renders the first when it
means the second is exactly the kind of confident-wrong the board is meant to
stop making.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import json
import os
import sys
import tempfile
import unittest
import pathlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))
import test_detail as td  # noqa: E402

RUN = "https://github.com/o/r/commit/abc/checks"


def report(**kw):
    base = {
        "sha": "8bef2079a086", "branch": "dev", "generated_at": "2026-07-23T06:41:00Z",
        "tests_passed": 6591, "tests_total": 6634, "test_files": 362,
        "tests_by_type": {"unit": 6501, "integration": 90, "e2e": 2,
                          "unit_files": 354, "integration_files": 8},
        "coverage_lines_pct": 79.81,
        "coverage": {"lines_pct": 79.81, "files_total": 400, "files_zero": 44,
                     "worst": [{"file": "a.tsx", "uncovered_lines": 139, "lines_pct": 59.8},
                               {"file": "b.tsx", "uncovered_lines": 61, "lines_pct": 51.6}]},
        "e2e": {"passed": 2, "failed": 15, "flaky": 0, "skipped": 2,
                "total": 19, "green": False, "duration_ms": 41000},
    }
    base.update(kw)
    return base


class TestFailuresSection(unittest.TestCase):
    def test_absent_failures_with_red_e2e_says_it_cannot_name_them(self):
        s = td.failures_section(report(), RUN)
        self.assertEqual(s["kind"], "banner")
        self.assertIn("15 failing", s["text"])
        self.assertIn("predates", s["text"])
        # Must NOT claim everything passed.
        self.assertNotIn("No failing", s["text"])

    def test_absent_failures_with_green_e2e_renders_nothing(self):
        r = report(e2e={"passed": 19, "failed": 0, "total": 19, "green": True})
        self.assertIsNone(td.failures_section(r, RUN))

    def test_empty_failures_list_is_a_positive_claim(self):
        s = td.failures_section(report(failures=[]), RUN)
        self.assertEqual(s["kind"], "banner")
        self.assertEqual(s["tone"], "go")
        self.assertIn("No failing tests", s["text"])

    def test_named_failures_render_as_console_lines(self):
        r = report(failures=[{"type": "e2e", "file": "tests/e2e/login.spec.ts",
                              "title": "signs in"}])
        s = td.failures_section(r, RUN)
        self.assertEqual(s["kind"], "console")
        self.assertEqual(s["count"], "1 failing")
        line = s["lines"][0]
        self.assertEqual(line["text"], "signs in")
        self.assertIn("login.spec.ts", line["meta"])
        self.assertEqual(line["href"], RUN)
        self.assertEqual(line["tone"], "err")

    def test_long_failure_lists_are_capped_and_say_so(self):
        r = report(failures=[{"title": f"t{i}"} for i in range(td.FAIL_MAX + 5)])
        s = td.failures_section(r, RUN)
        self.assertEqual(len(s["lines"]), td.FAIL_MAX)
        self.assertIn(str(td.FAIL_MAX + 5), s["count"])
        self.assertIn("showing", s["desc"])

    def test_a_failure_without_a_title_falls_back_to_its_file(self):
        s = td.failures_section(report(failures=[{"file": "x.spec.ts"}]), RUN)
        self.assertEqual(s["lines"][0]["text"], "x.spec.ts")


class TestLinkBoardTiles(unittest.TestCase):
    def board(self):
        return {"sections": [
            {"kind": "stats", "title": "Test results",
             "items": [{"n": "1", "label": "Passed"}, {"n": "2", "label": "E2E failed"}]},
            {"kind": "compare", "columns": [
                {"items": [{"n": "1", "label": "Tests green"},
                           {"n": "80%", "label": "Coverage (lines)"},
                           {"n": "✓", "label": "CI build"}]},
                {"items": [{"n": "332", "label": "Test files"}]},
            ]},
            {"kind": "stats", "title": "Tests by type", "items": [{"n": "1", "label": "Unit"}]},
        ]}

    def test_test_results_section_and_every_tile_link(self):
        b = self.board()
        td.link_board_tiles(b, "tests/", RUN)
        sec = b["sections"][0]
        self.assertEqual(sec["href"], "tests/")
        self.assertTrue(all(i["href"] == "tests/" for i in sec["items"]))

    def test_client_compare_tiles_link_to_the_page(self):
        b = self.board()
        td.link_board_tiles(b, "tests/", RUN)
        col = b["sections"][1]["columns"][0]["items"]
        self.assertEqual(col[0]["href"], "tests/")   # Tests green
        self.assertEqual(col[1]["href"], "tests/")   # Coverage

    def test_ci_build_tile_links_to_the_run_not_the_page(self):
        b = self.board()
        td.link_board_tiles(b, "tests/", RUN)
        self.assertEqual(b["sections"][1]["columns"][0]["items"][2]["href"], RUN)

    def test_the_servers_test_file_count_is_not_linked_to_the_client_page(self):
        # That tile is MWServer's number; this page is Phoenix's suite.
        b = self.board()
        td.link_board_tiles(b, "tests/", RUN)
        self.assertNotIn("href", b["sections"][1]["columns"][1]["items"][0])

    def test_unrelated_stats_sections_are_untouched(self):
        b = self.board()
        td.link_board_tiles(b, "tests/", RUN)
        self.assertNotIn("href", b["sections"][2])
        self.assertNotIn("href", b["sections"][2]["items"][0])

    def test_returns_how_many_tiles_it_touched(self):
        self.assertEqual(td.link_board_tiles(self.board(), "tests/", RUN), 4)

    def test_no_run_url_leaves_the_ci_tile_alone(self):
        b = self.board()
        td.link_board_tiles(b, "tests/", None)
        self.assertNotIn("href", b["sections"][1]["columns"][0]["items"][2])


class TestLoadReports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, obj):
        (self.d / f"{name}-test-report.json").write_text(json.dumps(obj))

    def test_indexes_by_branch_name(self):
        self.write("dev", report())
        by_branch, _ = td.load_reports(self.d)
        self.assertIn("dev", by_branch)

    def test_undated_reports_are_kept_for_lookup_but_not_charted(self):
        self.write("dev", report())
        self.write("main", report(generated_at=None))
        by_branch, dated = td.load_reports(self.d)
        self.assertIn("main", by_branch)
        self.assertEqual(len(dated), 1)

    def test_dated_reports_come_back_oldest_first(self):
        self.write("a", report(generated_at="2026-07-20T00:00:00Z"))
        self.write("b", report(generated_at="2026-07-10T00:00:00Z"))
        _, dated = td.load_reports(self.d)
        self.assertEqual([r["generated_at"][:10] for r in dated],
                         ["2026-07-10", "2026-07-20"])

    def test_corrupt_json_is_skipped_not_fatal(self):
        self.write("dev", report())
        (self.d / "bad-test-report.json").write_text("{not json")
        by_branch, _ = td.load_reports(self.d)
        self.assertEqual(list(by_branch), ["dev"])

    def test_missing_dir_is_empty_not_an_error(self):
        self.assertEqual(td.load_reports("/nope/nowhere"), ({}, []))


class TestSections(unittest.TestCase):
    def test_hero_links_every_tile_at_the_run(self):
        items = td.hero(report(), RUN)["items"]
        self.assertTrue(all(i["href"] == RUN for i in items))

    def test_hero_derives_skipped_from_total_minus_passed(self):
        items = td.hero(report(), RUN)["items"]
        self.assertEqual(items[1]["n"], "43")

    def test_hero_survives_a_report_with_no_coverage(self):
        items = td.hero(report(coverage_lines_pct=None), RUN)["items"]
        self.assertEqual(items[3]["n"], "—")

    def test_e2e_tone_is_red_only_when_something_failed(self):
        red = td.hero(report(), RUN)["items"][-1]
        green = td.hero(report(e2e={"passed": 19, "failed": 0, "total": 19}), RUN)["items"][-1]
        self.assertEqual(red["tone"], "err")
        self.assertEqual(green["tone"], "go")

    def test_by_type_shows_a_dash_when_e2e_was_not_measured(self):
        t = report()["tests_by_type"] | {"e2e": None}
        sec = td.by_type_section(report(tests_by_type=t))
        self.assertEqual(sec["items"][2]["n"], "—")

    def test_coverage_table_ranks_by_uncovered_lines(self):
        sec = td.coverage_section(report())
        self.assertEqual([r[0] for r in sec["rows"]], ["a.tsx", "b.tsx"])
        self.assertIn("44 files at 0%", sec["count"])

    def test_no_coverage_means_no_table(self):
        self.assertIsNone(td.coverage_section(report(coverage={})))

    def test_trend_needs_at_least_two_points(self):
        self.assertEqual(td.trend_sections([report()]), [])

    def test_trend_is_capped_to_the_most_recent_runs(self):
        pts = [report(generated_at=f"2026-07-{d:02d}T00:00:00Z") for d in range(1, 29)]
        secs = td.trend_sections(pts)
        self.assertEqual(len(secs[0]["series"]), td.TREND_MAX)
        self.assertTrue(secs[0]["series"][-1]["label"].startswith("07-28"))

    def test_coverage_trend_skips_runs_that_measured_none(self):
        pts = [report(generated_at="2026-07-01T00:00:00Z", coverage_lines_pct=None),
               report(generated_at="2026-07-02T00:00:00Z"),
               report(generated_at="2026-07-03T00:00:00Z")]
        secs = td.trend_sections(pts)
        cov = [s for s in secs if s["title"] == "Coverage over time"][0]
        self.assertEqual(len(cov["series"]), 2)

    def test_commit_url_needs_both_repo_and_sha(self):
        self.assertIsNone(td.commit_url("o/r", None))
        self.assertIsNone(td.commit_url(None, "abc"))
        self.assertIn("/commit/abc/checks", td.commit_url("o/r", "abc"))


if __name__ == "__main__":
    unittest.main()
