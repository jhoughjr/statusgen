#!/usr/bin/env python3
"""Unit tests for collect/ci_health.py — build-pipeline health tiles + the
build-time trend chart.

Monkeypatches lib.gh_run_history (no gh / network). The cases that matter are
the ones where a wrong answer would still look plausible on the board: churned
runs inflating the green rate, a failed run's clock passing for a build time,
and durations formatted into `value` where they would draw nothing.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib
import ci_health


def run(conclusion="success", sha="abc1234def", started="2026-07-26T05:10:22Z",
        ended="2026-07-26T05:15:58Z", branch="dev"):
    return {"status": "completed", "conclusion": conclusion,
            "headBranch": branch, "event": "push", "headSha": sha,
            "createdAt": started, "startedAt": started, "updatedAt": ended,
            "url": f"https://github.com/o/r/actions/runs/{sha}",
            "workflowName": "Build & Push"}


def board():
    return {"sections": [{"kind": "compare", "columns": [
        {"title": "Phoenix — client", "items": [{"n": "1", "label": "Tests green"}]},
        {"title": "MWServer — server", "items": [{"n": "99", "label": "Test files"}]},
    ]}]}


SOURCE = {"repo": "o/r", "column": "MWServer", "branch": "dev",
          "samples": 12, "workflow": None}


def tiles(b, col=1):
    return {t["label"]: t for t in b["sections"][0]["columns"][col]["items"]}


class ParseSourcesTest(unittest.TestCase):
    def test_full_spec(self):
        got = ci_health.parse_sources("o/r:MWServer:dev:5:Build")
        self.assertEqual(got, [{"repo": "o/r", "column": "MWServer",
                                "branch": "dev", "samples": 5,
                                "workflow": "Build"}])

    def test_defaults_fill_in_from_the_repo_name(self):
        got = ci_health.parse_sources("o/thing")[0]
        self.assertEqual((got["column"], got["branch"], got["samples"],
                          got["workflow"]),
                         ("thing", ci_health.DEFAULT_BRANCH,
                          ci_health.DEFAULT_SAMPLES, None))

    def test_multiple_entries_and_whitespace(self):
        got = ci_health.parse_sources(" o/a:A:dev:3 , o/b:B:main:4 ")
        self.assertEqual([s["repo"] for s in got], ["o/a", "o/b"])
        self.assertEqual([s["branch"] for s in got], ["dev", "main"])

    def test_unparseable_sample_count_falls_back_rather_than_dropping_the_repo(self):
        got = ci_health.parse_sources("o/r:R:dev:lots")[0]
        self.assertEqual(got["samples"], ci_health.DEFAULT_SAMPLES)

    def test_empty_spec(self):
        self.assertEqual(ci_health.parse_sources(""), [])
        self.assertEqual(ci_health.parse_sources(" , "), [])


class FinishedRunsTest(unittest.TestCase):
    # Cancelled/skipped runs are what a busy branch produces when a newer push
    # supersedes an older one. Scoring them as failures would make an entirely
    # healthy pipeline look broken; charting their time-to-cancel would make it
    # look fast.
    def test_churn_is_excluded(self):
        runs = [run("success"), run("cancelled"), run("skipped"),
                run("failure"), run(None)]
        got = ci_health.finished_runs(runs)
        self.assertEqual([r["conclusion"] for r in got], ["success", "failure"])

    def test_none_and_empty(self):
        self.assertEqual(ci_health.finished_runs(None), [])
        self.assertEqual(ci_health.finished_runs([]), [])


class ApplySourceTest(unittest.TestCase):
    def setUp(self):
        self._real = lib.gh_run_history

    def tearDown(self):
        lib.gh_run_history = self._real

    def feed(self, runs):
        lib.gh_run_history = lambda repo, **kw: runs

    def test_writes_build_time_and_green_rate_into_its_own_column(self):
        self.feed([run(), run(), run("failure")])
        b = board()
        self.assertIsNotNone(ci_health.apply_source(b, SOURCE))
        t = tiles(b)
        self.assertEqual(t["Build time"]["n"], "5m36s")
        self.assertEqual(t["Build green"]["n"], "2/3")
        # The client column is untouched.
        self.assertEqual(list(tiles(b, 0)), ["Tests green"])

    def test_build_time_comes_from_the_newest_run_that_actually_built(self):
        # Newest run failed after 1 minute; the build time is the last SUCCESS,
        # not "1m" — a failure's clock is how far it got, not how long it takes.
        failed = run("failure", started="2026-07-26T06:00:00Z",
                     ended="2026-07-26T06:01:00Z")
        self.feed([failed, run()])
        b = board()
        ci_health.apply_source(b, SOURCE)
        self.assertEqual(tiles(b)["Build time"]["n"], "5m36s")

    def test_build_time_tile_links_to_that_run(self):
        self.feed([run(sha="fc44010")])
        b = board()
        ci_health.apply_source(b, SOURCE)
        self.assertEqual(tiles(b)["Build time"]["href"],
                         "https://github.com/o/r/actions/runs/fc44010")

    def test_all_red_still_reports_a_green_rate_and_no_build_time(self):
        self.feed([run("failure"), run("failure")])
        b = board()
        ci_health.apply_source(b, SOURCE)
        t = tiles(b)
        self.assertEqual(t["Build green"]["n"], "0/2")
        self.assertEqual(t["Build green"]["tone"], "you")
        self.assertNotIn("Build time", t)

    def test_green_rate_goes_amber_below_two_thirds(self):
        self.feed([run(), run("failure"), run("failure")])
        b = board()
        ci_health.apply_source(b, SOURCE)
        self.assertEqual(tiles(b)["Build green"]["tone"], "you")

    def test_green_rate_stays_go_at_exactly_two_thirds(self):
        self.feed([run(), run(), run("failure")])
        b = board()
        ci_health.apply_source(b, SOURCE)
        self.assertEqual(tiles(b)["Build green"]["tone"], "go")

    def test_samples_caps_what_is_scored(self):
        self.feed([run() for _ in range(10)])
        b = board()
        ci_health.apply_source(b, dict(SOURCE, samples=4))
        self.assertEqual(tiles(b)["Build green"]["n"], "4/4")

    def test_no_runs_leaves_the_board_untouched(self):
        for feed in (None, [], [run("cancelled")]):
            self.feed(feed)
            b = board()
            self.assertIsNone(ci_health.apply_source(b, SOURCE))
            self.assertEqual(b, board())

    def test_unknown_column_cannot_invent_one(self):
        self.feed([run()])
        b = board()
        ci_health.apply_source(b, dict(SOURCE, column="Vault"))
        self.assertEqual(len(b["sections"][0]["columns"]), 2)

    def test_repeat_runs_do_not_accumulate_duplicate_tiles(self):
        self.feed([run()])
        b = board()
        ci_health.apply_source(b, SOURCE)
        ci_health.apply_source(b, SOURCE)
        labels = [t["label"] for t in b["sections"][0]["columns"][1]["items"]]
        self.assertEqual(len(labels), len(set(labels)))

    def test_it_asks_gh_only_for_this_branchs_push_runs(self):
        seen = {}

        def spy(repo, **kw):
            seen.update(kw, repo=repo)
            return [run()]

        lib.gh_run_history = spy
        ci_health.apply_source(board(), SOURCE)
        self.assertEqual(seen["repo"], "o/r")
        self.assertEqual(seen["branch"], "dev")
        self.assertEqual(seen["event"], "push")


class BuildChartTest(unittest.TestCase):
    def test_series_is_numeric_minutes_with_a_readable_label(self):
        chart = ci_health.build_chart(SOURCE, [run(), run(), run()])
        bar = chart["series"][0]
        # `value` drives bar width, so it must stay a number; `valueText` is
        # what the reader sees. Putting "5m36s" in `value` would draw nothing.
        self.assertIsInstance(bar["value"], float)
        self.assertEqual(bar["value"], 5.6)
        self.assertEqual(bar["valueText"], "5m36s")
        self.assertEqual(bar["label"], "abc1234")

    def test_failed_runs_are_charted_in_the_failure_tone(self):
        chart = ci_health.build_chart(SOURCE, [run(), run(), run("failure")])
        self.assertEqual([b["fill"] for b in chart["series"]],
                         ["go", "go", "you"])

    def test_note_reports_the_spread_of_the_green_runs(self):
        slow = run(started="2026-07-26T04:21:06Z", ended="2026-07-26T04:52:12Z")
        chart = ci_health.build_chart(SOURCE, [run(), run(), slow])
        self.assertIn("Fastest green 5m36s", chart["note"])
        self.assertIn("slowest 31m06s", chart["note"])

    # A run that failed in a minute is not this pipeline's fastest build.
    def test_a_quick_failure_is_not_reported_as_the_fastest(self):
        quick_fail = run("failure", started="2026-07-26T06:00:00Z",
                         ended="2026-07-26T06:01:02Z")
        chart = ci_health.build_chart(SOURCE, [quick_fail, run(), run()])
        self.assertIn("Fastest green 5m36s", chart["note"])
        self.assertNotIn("1m02s", chart["note"])

    def test_an_all_red_stretch_charts_without_claiming_a_spread(self):
        chart = ci_health.build_chart(
            SOURCE, [run("failure"), run("failure"), run("failure")])
        self.assertEqual(len(chart["series"]), 3)
        self.assertNotIn("Fastest green", chart["note"])

    def test_too_few_points_is_no_chart_rather_than_an_empty_one(self):
        self.assertIsNone(ci_health.build_chart(SOURCE, [run(), run()]))

    def test_undated_runs_are_dropped_not_drawn_as_instant(self):
        stampless = run()
        del stampless["startedAt"], stampless["createdAt"]
        chart = ci_health.build_chart(SOURCE, [run(), run(), run(), stampless])
        self.assertEqual(len(chart["series"]), 3)

    def test_chart_title_is_stable_so_it_upserts_rather_than_stacking(self):
        a = ci_health.build_chart(SOURCE, [run(), run(), run()])
        b = ci_health.build_chart(SOURCE, [run(), run(), run("failure")])
        self.assertEqual(a["title"], b["title"])
        self.assertEqual(a["title"], "MWServer — build time")


class DurationTest(unittest.TestCase):
    def test_measures_from_started_not_created(self):
        # A queued run's createdAt can precede its start by minutes; counting
        # queue time as build time makes a busy account look slow.
        r = run(started="2026-07-26T05:10:22Z", ended="2026-07-26T05:15:58Z")
        r["createdAt"] = "2026-07-26T05:00:00Z"
        self.assertEqual(lib.run_duration(r), 336.0)

    def test_falls_back_to_created_when_started_is_absent(self):
        r = run()
        del r["startedAt"]
        self.assertEqual(lib.run_duration(r), 336.0)

    def test_unfinished_or_unparseable_is_none(self):
        r = run()
        del r["updatedAt"]
        self.assertIsNone(lib.run_duration(r))
        self.assertIsNone(lib.run_duration({"startedAt": "not a date",
                                            "updatedAt": "also not"}))
        self.assertIsNone(lib.run_duration({}))

    def test_formats(self):
        self.assertEqual(lib.fmt_duration(45), "45s")
        self.assertEqual(lib.fmt_duration(360), "6m")
        self.assertEqual(lib.fmt_duration(336), "5m36s")
        self.assertEqual(lib.fmt_duration(1866), "31m06s")
        self.assertEqual(lib.fmt_duration(3840), "1h04m")
        self.assertIsNone(lib.fmt_duration(None))


if __name__ == "__main__":
    unittest.main()
