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
