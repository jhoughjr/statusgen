#!/usr/bin/env python3
"""Unit tests for collect/narrative.py — the banner's auto-refreshed timeline.

The contract worth pinning: hand-written prose above the marker is never
touched, re-running is idempotent (no marker stacking), and the window
fallback means the timeline shows the latest shipped day rather than going
blank on a quiet week.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))
import narrative as na  # noqa: E402

CDT = timezone(timedelta(hours=-5), "CDT")

PRS = [
    {"number": 166, "title": "fix: SRO price edit contract (#166)",
     "mergedAt": "2026-07-23T15:16:16Z"},
    {"number": 160, "title": "test(users): cover the write half of UsersView",
     "mergedAt": "2026-07-22T19:46:25Z"},
]


class TimelineTest(unittest.TestCase):
    def test_lines_lead_with_local_timestamp_oldest_first(self):
        lines = na.timeline(PRS, tz=CDT)
        self.assertEqual(lines[0][:11], "07-22 14:46")
        self.assertEqual(lines[1][:11], "07-23 10:16")
        self.assertIn("#166", lines[1])

    def test_trailing_pr_number_dropped_title_otherwise_verbatim(self):
        line = na.timeline(PRS, tz=CDT)[1]
        self.assertNotIn("(#166)", line)
        self.assertIn("fix: SRO price edit contract", line)

    def test_limit_keeps_the_newest(self):
        lines = na.timeline(PRS, tz=CDT, limit=1)
        self.assertEqual(len(lines), 1)
        self.assertIn("#166", lines[0])


class SpliceTest(unittest.TestCase):
    def setUp(self):
        self.block = na.render_block(PRS, tz=CDT)

    def test_no_marker_appends_below_hand_text(self):
        out = na.splice("2026-07-23 — a test-quality day.", self.block)
        self.assertTrue(out.startswith("2026-07-23 — a test-quality day.\n"))
        self.assertIn(na.MARKER_PREFIX, out)

    def test_marker_replaces_everything_below_it(self):
        old = "lede line\n" + na.MARKER_PREFIX + " old ──\n01-01 00:00 · #1 · stale"
        out = na.splice(old, self.block)
        self.assertNotIn("stale", out)
        self.assertTrue(out.startswith("lede line\n"))

    def test_idempotent_no_marker_stacking(self):
        once = na.splice("lede", self.block)
        twice = na.splice(once, self.block)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(na.MARKER_PREFIX), 1)

    def test_empty_banner_becomes_just_the_block(self):
        self.assertEqual(na.splice("", self.block), self.block)


class WindowTest(unittest.TestCase):
    def test_recent_window_wins(self):
        now = datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc)
        picked = na.pick_window(PRS, days=2, now=now)
        self.assertEqual(len(picked), 2)

    def test_quiet_week_falls_back_to_latest_shipped_day(self):
        now = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        picked = na.pick_window(PRS, days=2, now=now)
        self.assertEqual([p["number"] for p in picked], [166])

    def test_no_prs_is_empty(self):
        self.assertEqual(na.pick_window([], days=2), [])


if __name__ == "__main__":
    unittest.main()
