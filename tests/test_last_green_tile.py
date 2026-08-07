#!/usr/bin/env python3
"""Unit tests for the "Last green" compare tile and lib.fmt_age.

The "CI build" tile says ✓/✗ for the run that happened most recently. That is
least useful exactly when a build goes red: the board stops saying anything
about what still worked, so red reads as "everything is unknown" rather than
"here is the last thing that wasn't". These tests pin the tile that answers
the second question, and pin it to keep answering while the current build is
red — which is the whole point of it.

Monkeypatches lib.gh_runs (no gh / network).

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib
import ci_status


RUNS = [
    {"conclusion": "failure", "headSha": "80c7a2f9911",
     "createdAt": "2026-08-04T13:32:00Z", "url": "u/red"},
    {"conclusion": "cancelled", "headSha": "3711ba0aaaa",
     "createdAt": "2026-08-04T13:18:00Z", "url": "u/cancelled"},
    {"conclusion": "success", "headSha": "4bfbe2bcccc",
     "createdAt": "2026-08-04T10:00:00Z", "url": "u/green"},
]


def board_with(items):
    """The real board shape: one compare SECTION holding titled COLUMNS."""
    return {"sections": [{"kind": "compare", "title": "Phoenix ⟷ MWServer",
                          "columns": [{"title": "Phoenix", "items": list(items)},
                                      {"title": "MWServer", "items": []}]}]}


def columns(board):
    return board["sections"][0]["columns"]


def tile(board, label, col=0):
    return next((t for t in columns(board)[col]["items"]
                 if t.get("label") == label), None)


class LastGreenTile(unittest.TestCase):
    def setUp(self):
        self._real = lib.gh_runs
        self.addCleanup(lambda: setattr(lib, "gh_runs", self._real))

    def test_names_the_last_successful_commit_and_when(self):
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([{"label": "CI build", "n": "✗", "tone": "you"}])
        ci_status._last_green_tile(board, "o/r", "Phoenix")

        t = tile(board, "Last green")
        self.assertIsNotNone(t)
        self.assertEqual(t["n"], "4bfbe2b")
        self.assertEqual(t["tone"], "go")
        self.assertEqual(t["href"], "u/green")
        # The TIMESTAMP travels, not a rendered age.
        self.assertEqual(t["since"], "2026-08-04T10:00:00Z")

    def test_never_bakes_a_relative_age_into_the_value(self):
        """The bug this replaced: the collector wrote "4bfbe2b · 24m ago" into
        board.json, which is true for as long as it takes to publish the file
        and wrong forever after. A board left open kept insisting a build had
        gone green 24 minutes ago, hours later, with no such run in the history
        directly below it — the board contradicting itself, which is worse than
        the board being stale, because the reader cannot tell which half lies."""
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([])
        ci_status._last_green_tile(board, "o/r", "Phoenix")
        self.assertNotIn("ago", tile(board, "Last green")["n"])

    def test_survives_a_red_current_build(self):
        """The reason the tile exists: red must not blank out the last good."""
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([{"label": "CI build", "n": "✗", "tone": "you"}])
        ci_status._last_green_tile(board, "o/r", "Phoenix")

        self.assertEqual(tile(board, "CI build")["n"], "✗")
        self.assertEqual(tile(board, "Last green")["n"], "4bfbe2b")

    def test_skips_cancelled_and_failed_runs(self):
        """A superseded (cancelled) run is not evidence of anything."""
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([])
        ci_status._last_green_tile(board, "o/r", "Phoenix")
        self.assertNotIn("3711ba0", tile(board, "Last green")["n"])
        self.assertNotIn("80c7a2f", tile(board, "Last green")["n"])

    def test_says_none_recent_rather_than_claiming_a_stale_green(self):
        lib.gh_runs = lambda repo, limit: [r for r in RUNS
                                           if r["conclusion"] != "success"]
        board = board_with([])
        ci_status._last_green_tile(board, "o/r", "Phoenix")
        self.assertEqual(tile(board, "Last green")["n"], "none recent")
        self.assertEqual(tile(board, "Last green")["tone"], "you")

    def test_gh_unavailable_leaves_the_board_alone(self):
        """statusgen's collector contract: any failure → board untouched."""
        lib.gh_runs = lambda repo, limit: None
        board = board_with([])
        ci_status._last_green_tile(board, "o/r", "Phoenix")
        self.assertEqual(columns(board)[0]["items"], [])

    def test_writes_only_to_its_own_column(self):
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([])
        ci_status._last_green_tile(board, "o/r", "Phoenix")
        self.assertEqual(columns(board)[1]["items"], [])

    def test_is_idempotent(self):
        """Every status push re-runs collectors; tiles must not accumulate."""
        lib.gh_runs = lambda repo, limit: RUNS
        board = board_with([])
        for _ in range(3):
            ci_status._last_green_tile(board, "o/r", "Phoenix")
        labels = [i["label"] for i in columns(board)[0]["items"]]
        self.assertEqual(labels.count("Last green"), 1)


class FmtAge(unittest.TestCase):
    NOW = datetime.datetime(2026, 8, 4, 12, 0, tzinfo=datetime.timezone.utc)

    def test_buckets(self):
        for iso, want in [
            ("2026-08-04T11:59:30Z", "just now"),
            ("2026-08-04T11:51:00Z", "9m ago"),
            ("2026-08-04T09:00:00Z", "3h ago"),
            ("2026-08-02T12:00:00Z", "2d ago"),
        ]:
            self.assertEqual(lib.fmt_age(iso, now=self.NOW), want, iso)

    def test_a_future_stamp_reads_as_just_now_not_a_negative_age(self):
        """Runner clock skew shouldn't render "-1m ago" on the board."""
        self.assertEqual(lib.fmt_age("2026-08-04T12:00:30Z", now=self.NOW),
                         "just now")

    def test_unparseable_is_none_so_callers_can_omit_it(self):
        self.assertIsNone(lib.fmt_age("garbage", now=self.NOW))
        self.assertIsNone(lib.fmt_age("", now=self.NOW))
        self.assertIsNone(lib.fmt_age(None, now=self.NOW))


if __name__ == "__main__":
    unittest.main()
