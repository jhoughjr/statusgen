#!/usr/bin/env python3
"""Integration test: rookery collector produces a valid board section."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "collect"))
import lib
import rookery


FIXTURE_PAYLOAD = [
    {
        "id": "feature-work",
        "goal": "Implement feature X",
        "seats": [
            {
                "id": "seat-primary",
                "role": "coder",
                "state": "running",
                "execution": "local",
                "isReview": False,
                "runner": "mini",
                "agent": "claude-opus-4",
                "exitCode": None,
            },
            {
                "id": "seat-review",
                "role": "reviewer",
                "state": "finished",
                "execution": "hosted",
                "isReview": True,
                "runner": None,
                "agent": None,
                "exitCode": None,
            },
        ],
    },
]


class RookeryIntegrationTest(unittest.TestCase):
    def test_section_is_valid_board_structure(self):
        """Rookery section conforms to the console section schema."""
        section = rookery.section(FIXTURE_PAYLOAD, "https://rookery.test")

        # Console section is required to have these fields.
        self.assertEqual(section["kind"], "console")
        self.assertIn("icon", section)
        self.assertIn("title", section)
        self.assertIn("lines", section)

        # Each line must be a dict with status, tone, text.
        for line in section["lines"]:
            self.assertIsInstance(line, dict)
            self.assertIn("status", line)
            self.assertIn("tone", line)
            self.assertIn("text", line)
            self.assertIn(line["tone"], ["go", "you", "srv", "wip", "done", "err", "none"])

    def test_section_integrates_into_board(self):
        """Collector can upsert the section into a real board."""
        board = {
            "title": "Test Board",
            "sections": [
                {"kind": "stats", "items": [{"n": "1", "label": "Test"}]},
            ],
        }

        section = rookery.section(FIXTURE_PAYLOAD, "https://rookery.test")
        lib.upsert_section(board, "Seats", section)

        # Section was added (board had no Seats section before).
        sections_by_title = {s.get("title"): s for s in board["sections"]}
        self.assertIn("Seats", sections_by_title)
        self.assertEqual(sections_by_title["Seats"]["kind"], "console")
        self.assertEqual(len(sections_by_title["Seats"]["lines"]), 2)

    def test_section_replaces_existing_seats_section(self):
        """When Seats section exists, new data replaces it."""
        board = {
            "title": "Test Board",
            "sections": [
                {
                    "kind": "console",
                    "title": "Seats",
                    "icon": "🪑",
                    "lines": [{"status": "old", "text": "old data"}],
                },
            ],
        }

        section = rookery.section(FIXTURE_PAYLOAD, "https://rookery.test")
        lib.upsert_section(board, "Seats", section)

        sections_by_title = {s.get("title"): s for s in board["sections"]}
        self.assertEqual(len(sections_by_title["Seats"]["lines"]), 2)
        # Old data is gone.
        self.assertNotEqual(sections_by_title["Seats"]["lines"][0]["text"], "old data")


if __name__ == "__main__":
    unittest.main()
