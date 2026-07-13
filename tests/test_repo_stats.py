#!/usr/bin/env python3
"""Unit tests for repo_stats.patch_coverage_chart — the rich-coverage board
patch. The gh-driven fetch path isn't exercised here; these pin the pure
board transformation: bars matched by label, note rebuilt (zero-count +
worst offenders), unknown labels and foreign sections untouched, and the
no-matching-section / old-report shapes.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bin", "collect"))
import repo_stats

COVD = {
    "lines_pct": 63.04, "statements_pct": 61.82,
    "functions_pct": 55.0, "branches_pct": 50.0,
    "files_total": 312, "files_zero": 41,
    "worst": [
        {"file": "src/renderer/views/Big.tsx", "uncovered_lines": 400, "lines_pct": 20},
        {"file": "src/main/services/Zero.ts", "uncovered_lines": 200, "lines_pct": 0},
        {"file": "src/shared/tiny.ts", "uncovered_lines": 10, "lines_pct": 0},
        {"file": "src/shared/fourth.ts", "uncovered_lines": 5, "lines_pct": 50},
    ],
}


def chart(series_labels=("Lines", "Statements", "Functions", "Branches")):
    return {"kind": "barchart", "title": "Test Coverage",
            "note": "stale hand-written note",
            "series": [{"label": l, "value": 1.0, "fill": "code"}
                       for l in series_labels]}


class PatchCoverageChartTest(unittest.TestCase):
    def test_bars_patched_by_label(self):
        board = {"sections": [chart()]}
        self.assertTrue(repo_stats.patch_coverage_chart(board, COVD, 3902))
        values = {b["label"]: b["value"] for b in board["sections"][0]["series"]}
        self.assertEqual(values, {"Lines": 63.0, "Statements": 61.8,
                                  "Functions": 55.0, "Branches": 50.0})

    def test_note_has_counts_and_top3_worst(self):
        board = {"sections": [chart()]}
        repo_stats.patch_coverage_chart(board, COVD, 3902)
        note = board["sections"][0]["note"]
        self.assertIn("3,902 tests green", note)
        self.assertIn("41 of 312 files at 0%", note)
        self.assertIn("Big.tsx (400), Zero.ts (200), tiny.ts (10)", note)
        self.assertNotIn("fourth.ts", note)  # top-3 only

    def test_unknown_label_and_missing_metric_untouched(self):
        board = {"sections": [chart(("Lines", "Mutation"))]}
        covd = {"lines_pct": 63.04, "files_total": 312, "files_zero": 41}
        repo_stats.patch_coverage_chart(board, covd, 10)
        lines, mutation = board["sections"][0]["series"]
        self.assertEqual(lines["value"], 63.0)
        self.assertEqual(mutation["value"], 1.0)
        self.assertNotIn("most uncovered", board["sections"][0]["note"])

    def test_other_sections_never_touched(self):
        other = {"kind": "barchart", "title": "Codebase",
                 "series": [{"label": "Lines", "value": 9.0}]}
        board = {"sections": [copy.deepcopy(other), chart()]}
        self.assertTrue(repo_stats.patch_coverage_chart(board, COVD, 1))
        self.assertEqual(board["sections"][0], other)

    def test_no_matching_section_returns_false(self):
        board = {"sections": [{"kind": "compare", "columns": []}]}
        before = copy.deepcopy(board)
        self.assertFalse(repo_stats.patch_coverage_chart(board, COVD, 1))
        self.assertEqual(board, before)


if __name__ == "__main__":
    unittest.main()
