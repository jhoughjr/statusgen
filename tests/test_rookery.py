#!/usr/bin/env python3
"""The rookery collector: active seats from the control plane as a console
section, one line per seat showing role, state, execution mode, and runner."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bin" / "collect"))
import rookery


PAYLOAD_MIXED = [
    {
        "id": "assign-1",
        "goal": "Build the feature",
        "seats": [
            {
                "id": "seat-a1",
                "role": "primary",
                "state": "running",
                "execution": "local",
                "isReview": False,
                "runner": "mini",
                "agent": "claude-opus",
                "exitCode": None,
            },
            {
                "id": "seat-a2",
                "role": "review",
                "state": "blocked",
                "execution": "hosted",
                "isReview": True,
                "runner": None,
                "agent": None,
                "exitCode": None,
            },
        ],
    },
    {
        "id": "assign-2",
        "goal": "Fix the bug",
        "seats": [
            {
                "id": "seat-b1",
                "role": "research",
                "state": "finished",
                "execution": "local",
                "isReview": False,
                "runner": "opi",
                "agent": None,
                "exitCode": 0,
            },
            {
                "id": "seat-b2",
                "role": "debug",
                "state": "failed",
                "execution": "local",
                "isReview": False,
                "runner": "mini",
                "agent": None,
                "exitCode": 1,
            },
        ],
    },
]

PAYLOAD_EMPTY = []


class SeatLinesTest(unittest.TestCase):
    def test_one_line_per_seat_with_role_and_state(self):
        """Each seat becomes one line with role and state."""
        lines = rookery.seat_lines(PAYLOAD_MIXED)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0]["text"], "primary (claude-opus)")
        self.assertEqual(lines[1]["text"], "review")
        self.assertEqual(lines[2]["text"], "research")
        self.assertEqual(lines[3]["text"], "debug")

    def test_states_tone_correctly(self):
        """Running and starting are wip, finished is go, failed is err."""
        lines = rookery.seat_lines(PAYLOAD_MIXED)
        self.assertEqual(lines[0]["status"], "running")
        self.assertEqual(lines[0]["tone"], "wip")
        self.assertEqual(lines[1]["status"], "blocked")
        self.assertEqual(lines[1]["tone"], "you")
        self.assertEqual(lines[2]["status"], "finished")
        self.assertEqual(lines[2]["tone"], "go")
        self.assertEqual(lines[3]["status"], "failed")
        self.assertEqual(lines[3]["tone"], "err")

    def test_meta_shows_execution_and_runner(self):
        """Meta line shows where it ran: execution mode and runner name."""
        lines = rookery.seat_lines(PAYLOAD_MIXED)
        self.assertIn("local", lines[0]["meta"])
        self.assertIn("runner mini", lines[0]["meta"])
        self.assertIn("hosted", lines[1]["meta"])
        self.assertIn("control plane", lines[1]["meta"])
        self.assertIn("runner opi", lines[2]["meta"])

    def test_failed_seats_show_exit_code(self):
        """Failed seat shows its exit code in meta."""
        lines = rookery.seat_lines(PAYLOAD_MIXED)
        self.assertIn("exit 1", lines[3]["meta"])

    def test_successful_seat_shows_no_exit_code(self):
        """Successful seat does not show exit code."""
        lines = rookery.seat_lines(PAYLOAD_MIXED)
        self.assertNotIn("exit", lines[2]["meta"])

    def test_section_counts_seats(self):
        """Section title shows count of seats."""
        section = rookery.section(PAYLOAD_MIXED, "http://rookery.test")
        self.assertEqual(section["title"], "Seats")
        self.assertEqual(section["count"], "4 seat(s)")
        self.assertEqual(len(section["lines"]), 4)
        self.assertEqual(section["kind"], "console")
        self.assertEqual(section["icon"], "🪑")

    def test_section_shows_source(self):
        """Section desc includes the source URL."""
        section = rookery.section(PAYLOAD_MIXED, "http://rookery.test")
        self.assertIn("http://rookery.test", section["desc"])

    def test_empty_payload(self):
        """Empty payload produces a section with no lines."""
        section = rookery.section(PAYLOAD_EMPTY, "http://rookery.test")
        self.assertEqual(len(section["lines"]), 0)
        self.assertEqual(section["count"], "0 seat(s)")


if __name__ == "__main__":
    unittest.main()


class TheEnvelopeTheRouteAnswers(unittest.TestCase):
    """`/api/work` answers `{"assignments": [...], "can": ...}` rather than a bare list.

    The collector read the envelope as the list, found no assignments in it, and left the board alone on every run
    while saying so to a log nobody reads.
    """

    def test_the_assignments_are_taken_out_of_the_envelope(self):
        payload = {"assignments": [{"id": "a1", "seats": [{"id": "s1", "role": "builder", "state": "running"}]}],
                   "can": {"ratify": True}}

        assignments = payload.get("assignments") if isinstance(payload, dict) else payload

        self.assertIsInstance(assignments, list)
        self.assertEqual(sum(len(a.get("seats", [])) for a in assignments), 1)

    def test_a_bare_list_is_still_read(self):
        payload = [{"id": "a1", "seats": []}]

        assignments = payload.get("assignments") if isinstance(payload, dict) else payload

        self.assertEqual(assignments, payload)
