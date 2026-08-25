#!/usr/bin/env python3
"""Unit tests for lib.apply_column_order — the declared order of a compare
column's tiles.

A compare section is read ACROSS. "Is the client's coverage better than the
server's" is answered by two tiles sitting at the same height in two columns,
and nothing held them at that height: every tile is written by a different
collector, each appends when its tile is new, so each column's order was a
fossil of the order the collectors first happened to run in. The two columns
fossilised differently and the reader was left hunting for the other half of
each pair.

The section declares the order because only the board knows what it is
comparing. These tests pin that the declaration is obeyed, that an undeclared
tile still reaches the board, and that a board declaring nothing is left alone.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib


ORDER = ["CI build", "Build green", "Tests green", "Coverage"]


def board(order, left, right=()):
    """Two columns whose tiles arrive in whatever order collectors wrote them."""
    section = {"kind": "compare", "title": "Phoenix ⟷ MWServer",
               "columns": [{"title": "Phoenix",
                            "items": [{"label": l} for l in left]},
                           {"title": "MWServer",
                            "items": [{"label": l} for l in right]}]}
    if order is not None:
        section["order"] = list(order)
    return {"sections": [section]}


def labels(b, col=0):
    return [t["label"] for t in b["sections"][0]["columns"][col]["items"]]


class DeclaredOrderIsObeyed(unittest.TestCase):
    def test_a_column_sorts_into_the_declared_order(self):
        b = board(ORDER, ["Coverage (lines)", "CI build · dev", "Tests green"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b),
                         ["CI build · dev", "Tests green", "Coverage (lines)"])

    def test_both_columns_end_up_readable_across(self):
        """The point of the whole exercise: the same metric at the same height
        on both sides, whatever order the two columns were filled in."""
        b = board(ORDER,
                  ["Tests green", "CI build · dev", "Coverage (lines)"],
                  ["Coverage (lines)", "Tests green", "CI build · dev"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b, 0), labels(b, 1))

    def test_prefixes_match_the_way_every_other_tile_lookup_matches(self):
        """Tiles carry a branch in the label ("CI build · dev"). The order
        names the metric, not the tile."""
        b = board(ORDER, ["Tests green", "CI build · master"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b), ["CI build · master", "Tests green"])

    def test_two_tiles_under_one_prefix_keep_the_order_written(self):
        """dev before master, because that is the trunk preference order the
        collector wrote them in. A sort that reordered them would put the
        stable trunk above the working one."""
        b = board(ORDER, ["Tests green", "CI build · dev", "CI build · master"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b)[:2], ["CI build · dev", "CI build · master"])


class UndeclaredTilesStillReachTheBoard(unittest.TestCase):
    def test_an_unclaimed_label_goes_last_rather_than_vanishing(self):
        """A new collector must be able to add a tile without editing this
        list. Dropping it would make the ordering pass a silent censor."""
        b = board(ORDER, ["Blocked on server", "CI build · dev"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b), ["CI build · dev", "Blocked on server"])

    def test_unclaimed_labels_keep_their_relative_order(self):
        b = board(ORDER, ["Resolved", "Blocked on server", "Tests green"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b),
                         ["Tests green", "Resolved", "Blocked on server"])


class ABoardThatDeclaresNothingIsLeftAlone(unittest.TestCase):
    def test_no_order_key_means_no_reordering(self):
        b = board(None, ["Coverage (lines)", "CI build · dev", "Tests green"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b),
                         ["Coverage (lines)", "CI build · dev", "Tests green"])

    def test_an_empty_order_means_no_reordering(self):
        b = board([], ["Coverage (lines)", "CI build · dev"])
        lib.apply_column_order(b)
        self.assertEqual(labels(b), ["Coverage (lines)", "CI build · dev"])

    def test_a_malformed_order_is_ignored_rather_than_raising(self):
        """A hand-edited board must never be able to break a status push."""
        b = board(None, ["Coverage (lines)", "CI build · dev"])
        b["sections"][0]["order"] = "CI build"
        lib.apply_column_order(b)
        self.assertEqual(labels(b), ["Coverage (lines)", "CI build · dev"])

    def test_sections_that_are_not_compare_are_untouched(self):
        b = {"sections": [{"kind": "stats", "order": ["b"],
                           "items": [{"label": "a"}, {"label": "b"}]}]}
        lib.apply_column_order(b)
        self.assertEqual([i["label"] for i in b["sections"][0]["items"]],
                         ["a", "b"])


class SaveBoardAppliesIt(unittest.TestCase):
    """Wired into save_board rather than called by each collector: a column has
    to reach the renderer in order whichever collector wrote to it last, and
    every collector that touches a tile already ends by saving."""

    def test_the_file_on_disk_is_in_order(self):
        b = board(ORDER, ["Coverage (lines)", "CI build · dev", "Tests green"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "board.json")
            lib.save_board(path, b)
            written = json.load(open(path))
        self.assertEqual(
            [t["label"] for t in written["sections"][0]["columns"][0]["items"]],
            ["CI build · dev", "Tests green", "Coverage (lines)"])


if __name__ == "__main__":
    unittest.main()
