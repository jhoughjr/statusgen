#!/usr/bin/env python3
"""Unit tests for lib.set_compare_tile — wiring a hardcoded compare tile to
live data. Matches by label prefix across every column, sets n (and optional
label/tone), and is a silent no-op when the board doesn't carry the tile.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))
import lib


def board():
    return {"sections": [{"kind": "compare", "columns": [
        {"title": "Phoenix — client",
         "items": [{"n": "0", "label": "Tests green"},
                   {"n": "✓", "label": "CI build"}]},
        {"title": "MWServer — server",
         "items": [{"n": "346", "label": "Tests · 94 files"},
                   {"n": "10", "label": "Resolved"}]},
    ]}]}


class SetCompareTileTest(unittest.TestCase):
    def test_sets_value_in_first_column(self):
        b = board()
        self.assertTrue(lib.set_compare_tile(b, "CI build", "✗", tone="you"))
        tile = b["sections"][0]["columns"][0]["items"][1]
        self.assertEqual(tile["n"], "✗")
        self.assertEqual(tile["tone"], "you")

    def test_finds_tile_in_second_column_and_relabels(self):
        b = board()
        self.assertTrue(lib.set_compare_tile(b, "Tests ·", "332", label="Test files"))
        tile = b["sections"][0]["columns"][1]["items"][0]
        self.assertEqual((tile["n"], tile["label"]), ("332", "Test files"))

    def test_missing_tile_is_silent_noop(self):
        b = board()
        before = copy.deepcopy(b)
        self.assertFalse(lib.set_compare_tile(b, "Docker build", "✓"))
        self.assertEqual(b, before)

    def test_no_compare_section(self):
        b = {"sections": [{"kind": "console", "lines": []}]}
        self.assertFalse(lib.set_compare_tile(b, "CI build", "✓"))

    # The bug this scoping exists to prevent: the client repo's test-file count
    # was written by a search across every column, and the only tile matching
    # "Tests ·" lived in the SERVER column — so the client's number rendered
    # under the server's heading (and the relabel then froze it there, because
    # "Test files" no longer matches the "Tests ·" prefix on the next run).
    def test_column_scope_keeps_a_repos_number_out_of_the_other_column(self):
        b = board()
        self.assertFalse(lib.set_compare_tile(b, "Tests ·", "332",
                                              label="Test files",
                                              column="Phoenix"))
        self.assertEqual(b["sections"][0]["columns"][1]["items"][0]["n"], "346")

    def test_column_scope_matches_on_a_title_substring(self):
        b = board()
        self.assertTrue(lib.set_compare_tile(b, "Tests ·", "99",
                                             column="MWServer"))
        self.assertEqual(b["sections"][0]["columns"][1]["items"][0]["n"], "99")


class CompareColumnsTest(unittest.TestCase):
    def test_no_match_returns_every_column(self):
        self.assertEqual(len(lib.compare_columns(board())), 2)

    def test_match_is_case_insensitive_substring(self):
        cols = lib.compare_columns(board(), "mwserver")
        self.assertEqual([c["title"] for c in cols], ["MWServer — server"])

    def test_unknown_column_matches_nothing(self):
        self.assertEqual(lib.compare_columns(board(), "Vault"), [])


class UpsertCompareTileTest(unittest.TestCase):
    def test_creates_a_tile_the_column_does_not_have(self):
        b = board()
        self.assertTrue(lib.upsert_compare_tile(b, "MWServer", "Build time",
                                                "5m36s", tone="none"))
        tile = b["sections"][0]["columns"][1]["items"][-1]
        self.assertEqual((tile["n"], tile["label"], tile["tone"]),
                         ("5m36s", "Build time", "none"))
        # …and leaves the other column alone.
        self.assertEqual(len(b["sections"][0]["columns"][0]["items"]), 2)

    def test_updates_in_place_rather_than_appending_a_duplicate(self):
        b = board()
        lib.upsert_compare_tile(b, "Phoenix", "CI build", "✗", tone="you")
        items = b["sections"][0]["columns"][0]["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual((items[1]["n"], items[1]["tone"]), ("✗", "you"))

    def test_match_lets_a_collector_rename_its_own_tile(self):
        b = board()
        lib.upsert_compare_tile(b, "MWServer", "Test files", "99",
                                match="Tests ·")
        items = b["sections"][0]["columns"][1]["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual((items[0]["n"], items[0]["label"]), ("99", "Test files"))

    # A tile that linked to last week's run must not keep that link once the
    # collector has no run to point at.
    def test_none_clears_a_stale_href(self):
        b = board()
        lib.upsert_compare_tile(b, "Phoenix", "CI build", "✓",
                                href="https://example.test/runs/1")
        lib.upsert_compare_tile(b, "Phoenix", "CI build", "✓")
        self.assertNotIn("href", b["sections"][0]["columns"][0]["items"][1])

    def test_unknown_column_is_a_noop(self):
        b = board()
        before = copy.deepcopy(b)
        self.assertFalse(lib.upsert_compare_tile(b, "Vault", "Build time", "1m"))
        self.assertEqual(b, before)


if __name__ == "__main__":
    unittest.main()
