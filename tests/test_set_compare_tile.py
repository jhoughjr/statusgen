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
        {"items": [{"n": "0", "label": "Tests green"},
                   {"n": "✓", "label": "CI build"}]},
        {"items": [{"n": "346", "label": "Tests · 94 files"},
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


if __name__ == "__main__":
    unittest.main()
