#!/usr/bin/env python3
"""Unit tests for collect/swift_test_report.py — the test-RESULTS tiles for a
Swift repo whose gate runs in CI.

The network is never touched: `newest_report` is replaced with a stub, so what
is under test is the board patching — the rename of the inventory tile, the
per-suite section, and the coverage chart that must stay absent rather than
render a zero.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import swift_test_report as str_


def board_with(tiles):
    """A board carrying one compare column named like MWServer."""
    return {
        "sections": [
            {"kind": "compare", "title": "Phoenix ⟷ MWServer",
             "columns": [
                 {"title": "Phoenix — client", "items": [{"n": "7380", "label": "Tests green"}]},
                 {"title": "MWServer — server", "items": list(tiles)},
             ]},
        ]
    }


def column_items(board):
    return board["sections"][0]["columns"][1]["items"]


def tile(board, label):
    return next((t for t in column_items(board) if t.get("label") == label), None)


def section(board, title):
    return next((s for s in board["sections"] if s.get("title") == title), None)


REPORT = {
    "tests_passed": 618,
    "suites_total": 119,
    "suites": [
        {"name": "SQLSerializationTests", "tests": 121, "suites": 19},
        {"name": "AppTests", "tests": 278, "suites": 45},
        {"name": "IntegrationTests", "tests": 219, "suites": 55},
    ],
    "sha": "187b1650000",
    "coverage_lines_pct": 61.4,
    "coverage_regions_pct": 56.7,
    "coverage_functions_pct": 56.7,
    "coverage_branches_pct": 48.8,
}

SOURCE = {"slug": "Austin-MacWorks/MWServer", "column": "MWServer",
          "branch": "dev", "label": "MWServer"}


class ParseSources(unittest.TestCase):
    def test_defaults_fill_in(self):
        got = str_.parse_sources("owner/repo")
        self.assertEqual(got, [{"slug": "owner/repo", "column": "repo",
                                "branch": "dev", "label": "repo"}])

    def test_every_field_reads(self):
        got = str_.parse_sources("owner/repo:Col:main:Label")[0]
        self.assertEqual((got["column"], got["branch"], got["label"]),
                         ("Col", "main", "Label"))

    def test_an_entry_without_a_slug_is_dropped(self):
        self.assertEqual(str_.parse_sources("notaslug, owner/repo")[0]["slug"],
                         "owner/repo")


class Patching(unittest.TestCase):
    def apply(self, board, report=REPORT):
        original = str_.newest_report
        str_.newest_report = lambda slug, branch, work: (
            report, {"url": "https://example.test/run/1"})
        try:
            return str_.apply_source(board, SOURCE, None)
        finally:
            str_.newest_report = original

    def test_the_inventory_tile_is_replaced_in_place(self):
        """The old "Tests written" tile must not survive alongside the new one:
        two tiles claiming different totals is exactly the lie the split
        between the two collectors exists to prevent."""
        board = board_with([{"n": "547", "label": "Tests written", "tone": "srv"},
                            {"n": "132", "label": "Test files", "tone": "srv"}])
        self.apply(board)

        labels = [t["label"] for t in column_items(board)]
        self.assertIn("Tests green", labels)
        self.assertNotIn("Tests written", labels)
        self.assertEqual(tile(board, "Tests green")["n"], "618")
        self.assertEqual(tile(board, "Tests green")["tone"], "go")
        # An unrelated tile the other collector owns is left alone.
        self.assertEqual(tile(board, "Test files")["n"], "132")

    def test_coverage_tile_is_a_rounded_percent(self):
        board = board_with([])
        self.apply(board)
        self.assertEqual(tile(board, "Coverage (lines)")["n"], "61%")

    def test_suites_section_carries_one_item_per_suite(self):
        board = board_with([])
        self.apply(board)
        got = section(board, "MWServer — tests by type")
        self.assertIsNotNone(got)
        self.assertEqual([i["label"] for i in got["items"]],
                         ["SQLSerializationTests", "AppTests", "IntegrationTests"])
        self.assertEqual([i["n"] for i in got["items"]], ["121", "278", "219"])
        self.assertEqual(got["count"], "618 green")

    def test_coverage_section_carries_the_four_metrics_in_order(self):
        board = board_with([])
        self.apply(board)
        got = section(board, "MWServer — test coverage")
        self.assertEqual([s["label"] for s in got["series"]],
                         ["Lines", "Regions", "Functions", "Branches"])
        self.assertEqual(got["series"][0]["value"], 61.4)

    def test_the_chart_holds_only_the_metrics_the_report_carries(self):
        """The shape the MWServer gate really emits: three metrics, no branches.

        Swift does not instrument branch coverage, so the emitter leaves the
        key out rather than sending a zero. The chart must then draw three
        bars, because a fourth bar at zero would claim no branch is covered.
        """
        partial = {k: v for k, v in REPORT.items()
                   if k != "coverage_branches_pct"}
        board = board_with([])
        self.apply(board, report=partial)

        got = section(board, "MWServer — test coverage")
        self.assertEqual([s["label"] for s in got["series"]],
                         ["Lines", "Regions", "Functions"])
        # The tile still reads lines, which is the metric it carries.
        self.assertEqual(tile(board, "Coverage (lines)")["n"], "61%")

    def test_a_report_without_coverage_writes_no_coverage_at_all(self):
        """A gate that does not measure coverage must leave the chart and the
        tile absent. Rendering an absent measurement as 0% would read as
        "nothing is covered", which is a different and false claim."""
        bare = {k: v for k, v in REPORT.items() if not k.startswith("coverage")}
        board = board_with([])
        self.apply(board, report=bare)

        self.assertIsNone(section(board, "MWServer — test coverage"))
        self.assertIsNone(tile(board, "Coverage (lines)"))
        # The count still lands: results and coverage are independent.
        self.assertEqual(tile(board, "Tests green")["n"], "618")

    def test_no_report_leaves_the_board_untouched(self):
        board = board_with([{"n": "547", "label": "Tests written"}])
        original = str_.newest_report
        str_.newest_report = lambda slug, branch, work: (None, None)
        try:
            self.assertIsNone(str_.apply_source(board, SOURCE, None))
        finally:
            str_.newest_report = original
        self.assertEqual(tile(board, "Tests written")["n"], "547")


if __name__ == "__main__":
    unittest.main()
