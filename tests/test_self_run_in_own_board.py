#!/usr/bin/env python3
"""A run must appear in the board it publishes.

The board step runs INSIDE the job it reports on, so `gh run list` calls that
job `in_progress` and every filter drops it. A run could therefore never appear
in the board it published — it surfaced only when some later push happened to
refresh the feed, and if nothing else pushed for hours it looked like the build
had simply vanished.

Reported 2026-08-06 as "it's not in the list and I watched it run — it didn't
succeed [or] fail", against a run the reporter had watched execute start to
finish. Distinct from the cancelled-run case (test_ci_status_lines.py): that
one dropped superseded runs, this one drops the *current* one.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib


def runs():
    return [
        {"status": "in_progress", "conclusion": None, "headBranch": "dev",
         "event": "push", "createdAt": "2026-08-06T15:29:00Z",
         "url": "u/self", "headSha": "aaaaaaa", "databaseId": 999},
        {"status": "completed", "conclusion": "success", "headBranch": "dev",
         "event": "push", "createdAt": "2026-08-06T11:50:00Z",
         "url": "u/prev", "headSha": "bbbbbbb", "databaseId": 111},
    ]


def feed(sources, **kw):
    return [l for l in lib.console_lines(sources, **kw) if "cmd" not in l]


class SelfRunIsVisibleInItsOwnBoard(unittest.TestCase):
    def setUp(self):
        self._real = lib.gh_runs
        lib.gh_runs = lambda repo, limit: runs()
        self.addCleanup(lambda: setattr(lib, "gh_runs", self._real))

    def test_without_the_hint_the_publishing_run_is_missing(self):
        """The bug, reproduced: gh cannot yet know the outcome, so the row the
        reporter watched execute is simply absent."""
        self.assertEqual([l["href"] for l in feed([("o/r", "Repo", 4)])], ["u/prev"])

    def test_with_the_hint_it_appears_with_its_real_outcome(self):
        lines = feed([("o/r", "Repo", 4)], self_run=("o/r", "999", "success"))
        self.assertEqual([l["href"] for l in lines], ["u/self", "u/prev"])
        self.assertEqual(lines[0]["status"], "success")

    def test_a_failing_run_reports_itself_as_failing(self):
        """Not a way to make every board look green: whatever CI's own outcome
        is, is what gets published."""
        lines = feed([("o/r", "Repo", 4)], self_run=("o/r", "999", "failure"))
        self.assertEqual(lines[0]["status"], "failure")
        self.assertEqual(lines[0]["tone"], "you")

    def test_the_hint_only_applies_to_its_own_repo(self):
        lines = feed([("o/other", "Other", 4)], self_run=("o/r", "999", "success"))
        self.assertEqual([l["href"] for l in lines], ["u/prev"])

    def test_an_unrelated_run_id_changes_nothing(self):
        lines = feed([("o/r", "Repo", 4)], self_run=("o/r", "12345", "success"))
        self.assertEqual([l["href"] for l in lines], ["u/prev"])

    def test_self_run_from_needs_all_three_parts(self):
        self.assertIsNone(lib.self_run_from({}))
        self.assertIsNone(lib.self_run_from({"ROOST_CI_SELF_REPO": "o/r",
                                             "ROOST_CI_SELF_RUN_ID": "999"}))
        self.assertEqual(
            lib.self_run_from({"ROOST_CI_SELF_REPO": "o/r",
                               "ROOST_CI_SELF_RUN_ID": "999",
                               "ROOST_CI_SELF_OUTCOME": "success"}),
            ("o/r", "999", "success"))

    def test_apply_self_run_is_a_no_op_without_a_hint(self):
        data = runs()
        self.assertIs(lib.apply_self_run("o/r", data, None), data)

    def test_apply_self_run_does_not_mutate_the_caller_s_rows(self):
        data = runs()
        lib.apply_self_run("o/r", data, ("o/r", "999", "success"))
        self.assertEqual(data[0]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
