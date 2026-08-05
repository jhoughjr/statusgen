#!/usr/bin/env python3
"""Unit tests for lib.console_lines — the CI-run → console-line mapping.

Monkeypatches lib.gh_runs (no gh / network): asserts run lines carry the
Actions URL as `href`, each repo's block ends with a copyable
`gh run watch` chip line, and a repo with no data emits neither.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib


RUN = {
    "status": "completed", "conclusion": "success", "headBranch": "dev",
    "event": "push", "createdAt": "2026-07-13T19:03:04Z",
    "url": "https://github.com/o/r/actions/runs/1",
}


class ConsoleLinesTest(unittest.TestCase):
    def setUp(self):
        self._real = lib.gh_runs

    def tearDown(self):
        lib.gh_runs = self._real

    def test_run_line_carries_href_and_repo_gets_watch_chip(self):
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        lines = lib.console_lines([("o/r", "Repo", 4)])
        self.assertEqual(len(lines), 2)
        run, watch = lines
        self.assertEqual(run["href"], RUN["url"])
        self.assertEqual(run["status"], "success")
        self.assertEqual(watch["cmd"], "gh run watch -R o/r")
        self.assertEqual(watch["status"], "watch")
        self.assertNotIn("href", watch)

    def test_urlless_run_omits_href(self):
        run = dict(RUN)
        del run["url"]
        lib.gh_runs = lambda repo, limit: [run]
        lines = lib.console_lines([("o/r", "Repo", 4)])
        self.assertNotIn("href", lines[0])

    def test_no_data_emits_no_watch_chip(self):
        lib.gh_runs = lambda repo, limit: None
        self.assertEqual(lib.console_lines([("o/r", "Repo", 4)]), [])
        lib.gh_runs = lambda repo, limit: []
        self.assertEqual(lib.console_lines([("o/r", "Repo", 4)]), [])

    def test_a_source_can_tag_its_rows_with_a_stack_mark(self):
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        run, watch = lib.console_lines([("o/r", "Repo", 4, "swift")])
        self.assertEqual(run["logo"], "swift")
        # The watch chip is that repo's row too — an unmarked row in a merged
        # feed reads as belonging to whichever stack came before it.
        self.assertEqual(watch["logo"], "swift")

    def test_an_untagged_source_emits_no_logo_key(self):
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        for line in lib.console_lines([("o/r", "Repo", 4)]):
            self.assertNotIn("logo", line)

    def test_each_source_keeps_its_own_mark_in_one_merged_feed(self):
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        lines = lib.console_lines([("o/a", "A", 1, "ts"), ("o/b", "B", 1, "swift")])
        # Runs first (interleaved by time), then the watch chips. Both runs
        # share a timestamp here, so the sort is stable and A leads.
        self.assertEqual([l.get("logo") for l in lines],
                         ["ts", "swift", "ts", "swift"])

    def test_the_feed_is_chronological_across_repos_not_grouped_by_repo(self):
        """The bug this pins: rows were appended one repo at a time, so a
        server build from an hour ago sat below a client build from yesterday
        purely because the client repo was configured first. Read top-down —
        the only way anyone reads "recent runs" — this morning's builds looked
        like they had never happened."""
        def runs(repo, limit):
            when = {"o/a": "2026-08-04T17:07:00Z", "o/b": "2026-08-05T14:33:00Z"}[repo]
            return [dict(RUN, createdAt=when)]
        lib.gh_runs = runs
        lines = [l for l in lib.console_lines([("o/a", "A", 1), ("o/b", "B", 1)])
                 if "cmd" not in l]
        self.assertEqual([l["text"] for l in lines], ["B · dev", "A · dev"])

    def test_newest_first_within_a_repo_too(self):
        lib.gh_runs = lambda repo, limit: [
            dict(RUN, createdAt="2026-08-01T00:00:00Z"),
            dict(RUN, createdAt="2026-08-05T00:00:00Z"),
        ]
        lines = [l for l in lib.console_lines([("o/a", "A", 4)]) if "cmd" not in l]
        self.assertEqual([l["ts"] for l in lines],
                         ["2026-08-05T00:00:00Z", "2026-08-01T00:00:00Z"])

    def test_a_row_without_a_timestamp_sorts_last_rather_than_to_the_top(self):
        lib.gh_runs = lambda repo, limit: [
            dict(RUN, createdAt=""),
            dict(RUN, createdAt="2026-08-05T00:00:00Z"),
        ]
        lines = [l for l in lib.console_lines([("o/a", "A", 4)]) if "cmd" not in l]
        self.assertEqual(lines[0].get("ts"), "2026-08-05T00:00:00Z")

    def test_watch_chips_come_after_every_run(self):
        """They are controls, not events — a chip in the middle of a
        chronological feed reads as something that happened at that time."""
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        lines = lib.console_lines([("o/a", "A", 1), ("o/b", "B", 1)])
        first_chip = next(i for i, l in enumerate(lines) if "cmd" in l)
        self.assertTrue(all("cmd" in l for l in lines[first_chip:]))

    def test_watch_chip_per_repo(self):
        lib.gh_runs = lambda repo, limit: [dict(RUN)]
        lines = lib.console_lines([("o/a", "A", 1), ("o/b", "B", 1)])
        cmds = [ln["cmd"] for ln in lines if "cmd" in ln]
        self.assertEqual(cmds, ["gh run watch -R o/a", "gh run watch -R o/b"])

    def _run(self, status, conclusion):
        return {"status": status, "conclusion": conclusion, "headBranch": "dev",
                "event": "push", "createdAt": "2026-07-13T19:03:04Z",
                "url": "https://github.com/o/r/actions/runs/1"}

    def test_in_progress_and_cancelled_runs_are_skipped(self):
        # The mess the push-based update used to freeze on: a still-running row
        # on top, then concurrency-cancelled churn — none should surface.
        runs = [self._run("in_progress", None),
                self._run("completed", "cancelled"),
                self._run("completed", "cancelled"),
                self._run("completed", "success")]
        lib.gh_runs = lambda repo, limit: runs
        lines = lib.console_lines([("o/r", "Repo", 4)])
        statuses = [ln["status"] for ln in lines if "cmd" not in ln]
        self.assertEqual(statuses, ["success"])  # only the real outcome

    def test_failures_survive_the_filter(self):
        runs = [self._run("in_progress", None), self._run("completed", "failure")]
        lib.gh_runs = lambda repo, limit: runs
        lines = lib.console_lines([("o/r", "Repo", 4)])
        self.assertEqual([ln["status"] for ln in lines if "cmd" not in ln], ["failure"])

    def test_limit_respected_after_filtering(self):
        runs = ([self._run("in_progress", None)] * 5
                + [self._run("completed", "success")] * 10)
        lib.gh_runs = lambda repo, limit: runs
        lines = lib.console_lines([("o/r", "Repo", 3)])
        self.assertEqual(len([ln for ln in lines if "cmd" not in ln]), 3)

    def test_overfetch_asks_gh_for_more_than_limit(self):
        seen = {}
        def fake(repo, limit):
            seen["limit"] = limit
            return [dict(RUN)]
        lib.gh_runs = fake
        lib.console_lines([("o/r", "Repo", 4)])
        self.assertGreaterEqual(seen["limit"], 30)


if __name__ == "__main__":
    unittest.main()
