#!/usr/bin/env python3
"""Unit tests for trunk scoping of the "CI build" / "Last green" tiles.

The bug these pin, observed on the clauffice board 2026-08-05: the badge read
✗ while every trunk was green. The tile was set from the repo's newest run on
ANY branch, and the newest run happened to be a failing pull request
(Phoenix-Electron #235, red on its `fix/po-list-server-search` branch). A
project is not red because someone's PR is red — that is a PR's business, not
the board's headline.

Since 2026-08-20 every trunk with settled runs gets its OWN tile pair, branch
in the label, so one trunk can never mask another: after a trunk switch moved
MWServer's story to master, the dev-pinned tile asserted a two-day silence
while master went green in the feed below it. The preferred trunk renames the
legacy plain tiles in place; later trunks sit beside it.

Monkeypatches nothing: apply_tiles takes the run window as an argument.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import ci_status


def run(conclusion, branch, sha, created, url, status="completed"):
    return {"conclusion": conclusion, "status": status, "headBranch": branch,
            "headSha": sha, "createdAt": created, "url": url}


# Newest first, as `gh run list` returns them. This is the real shape of the
# window that produced the bad badge: a red PR on top, dev green underneath.
RUNS = [
    run("failure", "fix/po-list-server-search", "96f1ab6ff",
        "2026-08-04T18:53:00Z", "u/pr-red"),
    run("success", "dev", "500b6394a", "2026-08-04T17:07:00Z", "u/dev-green"),
    run("success", "dev", "e2e00000a", "2026-08-04T15:16:00Z", "u/dev-older"),
    run("success", "main", "f7aaabb46", "2026-08-04T07:15:00Z", "u/main-green"),
]

TRUNKS = ["dev", "main"]


def board_with(items):
    return {"sections": [{"kind": "compare", "title": "Phoenix ⟷ MWServer",
                          "columns": [{"title": "Phoenix", "items": list(items)},
                                      {"title": "MWServer", "items": []}]}]}


def columns(board):
    return board["sections"][0]["columns"]


def tile(board, label, col=0):
    return next((t for t in columns(board)[col]["items"]
                 if t.get("label") == label), None)


class CiBuildTileIsTrunkScoped(unittest.TestCase):
    def test_a_red_pull_request_does_not_turn_the_badge_red(self):
        """The reported bug, verbatim."""
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        t = tile(board, "CI build · dev")
        self.assertEqual(t["n"], "✓")
        self.assertEqual(t["tone"], "go")
        self.assertEqual(t["href"], "u/dev-green")

    def test_a_red_trunk_still_turns_the_badge_red(self):
        """Scoping must not become a way to never show bad news."""
        runs = [run("failure", "dev", "deadbee", "2026-08-04T19:00:00Z", "u/dev-red")] + RUNS
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertEqual(tile(board, "CI build · dev")["n"], "✗")
        self.assertEqual(tile(board, "CI build · dev")["tone"], "you")
        self.assertEqual(tile(board, "CI build · dev")["href"], "u/dev-red")

    def test_a_nightly_green_main_cannot_mask_a_red_dev(self):
        """Each trunk owns a labelled tile, so masking is impossible by
        construction: main's green sits beside dev's red, not over it."""
        runs = [
            run("success", "main", "f7aaabb46", "2026-08-05T07:16:00Z", "u/main-cron"),
            run("failure", "dev", "deadbee", "2026-08-04T19:00:00Z", "u/dev-red"),
        ]
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertEqual(tile(board, "CI build · dev")["n"], "✗")
        self.assertEqual(tile(board, "CI build · dev")["href"], "u/dev-red")
        self.assertEqual(tile(board, "CI build · main")["n"], "✓")
        self.assertEqual(tile(board, "CI build · main")["href"], "u/main-cron")

    def test_both_trunks_get_a_pair_side_by_side(self):
        """Ruled 2026-08-20: dev and master together."""
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        self.assertIsNotNone(tile(board, "CI build · dev"))
        self.assertIsNotNone(tile(board, "Last green · dev"))
        self.assertIsNotNone(tile(board, "CI build · main"))
        self.assertIsNotNone(tile(board, "Last green · main"))
        self.assertEqual(tile(board, "Last green · main")["href"], "u/main-green")

    def test_the_preferred_trunk_renames_the_legacy_plain_tile_in_place(self):
        """Boards deployed before the split hold a plain "CI build" tile.
        It must rename, not orphan: a dead plain tile would keep asserting a
        state no collector maintains."""
        board = board_with([{"label": "CI build", "n": "✗", "tone": "you"}])
        ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        self.assertIsNone(tile(board, "CI build"))
        self.assertEqual(tile(board, "CI build · dev")["n"], "✓")

    def test_falls_through_to_main_when_dev_has_no_runs_in_the_window(self):
        runs = [
            run("failure", "some/feature", "aaa", "2026-08-05T09:00:00Z", "u/feat"),
            run("success", "main", "f7aaabb46", "2026-08-05T07:16:00Z", "u/main-cron"),
        ]
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertEqual(tile(board, "CI build · main")["n"], "✓")
        self.assertEqual(tile(board, "CI build · main")["href"], "u/main-cron")

    def test_no_trunk_in_the_window_leaves_the_tile_untouched(self):
        """Collector contract: absent data leaves the board alone. It must not
        fall back to a feature branch — that is the original bug."""
        runs = [run("failure", "some/feature", "aaa", "2026-08-05T09:00:00Z", "u/feat")]
        board = board_with([{"label": "CI build", "n": "✓", "tone": "go"}])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        t = tile(board, "CI build")
        self.assertEqual(t["n"], "✓")
        self.assertEqual(t["tone"], "go")
        # Untouched means untouched: no href grafted on from the feature branch.
        self.assertIsNone(t.get("href"))

    def test_in_progress_and_cancelled_trunk_runs_are_not_an_outcome(self):
        runs = [
            run(None, "dev", "aaa", "2026-08-05T09:00:00Z", "u/running",
                status="in_progress"),
            run("cancelled", "dev", "bbb", "2026-08-05T08:00:00Z", "u/cancelled"),
            run("failure", "dev", "ccc", "2026-08-05T07:00:00Z", "u/dev-red"),
        ]
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertEqual(tile(board, "CI build · dev")["href"], "u/dev-red")

    def test_writes_only_to_its_own_column(self):
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        self.assertEqual(columns(board)[1]["items"], [])

    def test_is_idempotent(self):
        board = board_with([])
        for _ in range(3):
            ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        labels = [i["label"] for i in columns(board)[0]["items"]]
        self.assertEqual(labels.count("CI build · dev"), 1)
        self.assertEqual(labels.count("CI build · main"), 1)
        self.assertEqual(labels.count("Last green · dev"), 1)
        self.assertEqual(labels.count("Last green · main"), 1)


class LastGreenIsScopedToTheSameBranch(unittest.TestCase):
    """Each pair is read together; sourcing a pair from different branches
    would produce a column that quietly contradicts itself."""

    def test_last_green_comes_from_the_same_trunk_as_its_badge(self):
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", RUNS, TRUNKS)
        self.assertTrue(tile(board, "Last green · dev")["n"].startswith("500b639"),
                        tile(board, "Last green · dev")["n"])
        self.assertEqual(tile(board, "Last green · dev")["href"], "u/dev-green")

    def test_a_green_pull_request_is_not_the_projects_last_green(self):
        runs = [
            run("success", "someones/pr", "cafebabe", "2026-08-05T09:00:00Z", "u/pr-green"),
            run("failure", "dev", "deadbee", "2026-08-04T19:00:00Z", "u/dev-red"),
            run("success", "dev", "500b6394a", "2026-08-04T17:07:00Z", "u/dev-green"),
        ]
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertTrue(tile(board, "Last green · dev")["n"].startswith("500b639"))

    def test_trunk_red_all_window_says_none_recent(self):
        runs = [run("failure", "dev", "deadbee", "2026-08-04T19:00:00Z", "u/dev-red")]
        board = board_with([])
        ci_status.apply_tiles(board, "o/r", "Phoenix", runs, TRUNKS)
        self.assertEqual(tile(board, "Last green · dev")["n"], "none recent")


class ParseTrunks(unittest.TestCase):
    def test_default_prefers_dev(self):
        self.assertEqual(ci_status.parse_trunks({})[0], "dev")

    def test_unset_or_blank_falls_back_to_the_default(self):
        self.assertEqual(ci_status.parse_trunks({"ROOST_CI_TRUNKS": "   "}),
                         list(ci_status.TRUNKS_DEFAULT))

    def test_configured_order_is_preserved(self):
        self.assertEqual(ci_status.parse_trunks({"ROOST_CI_TRUNKS": "main, dev"}),
                         ["main", "dev"])

    def test_empty_entries_are_dropped(self):
        self.assertEqual(ci_status.parse_trunks({"ROOST_CI_TRUNKS": "dev,,main,"}),
                         ["dev", "main"])


if __name__ == "__main__":
    unittest.main()
