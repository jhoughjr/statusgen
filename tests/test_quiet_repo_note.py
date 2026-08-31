#!/usr/bin/env python3
"""Unit tests for lib.quiet_repo_note — what a board says when a repo says nothing.

A repo that returns no runs leaves its tiles holding their last verdict. That
is correct and invisible, and it is how a board goes on reporting a green that
stopped being true. These assert the two silences are distinguished, and that a
forge repo names the cause a mirror actually has.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib


class QuietRepoNoteTest(unittest.TestCase):
    def test_a_repo_with_runs_says_nothing(self):
        self.assertIsNone(lib.quiet_repo_note("o/r", [{"status": "completed"}]))

    def test_no_answer_is_reported_as_no_answer(self):
        note = lib.quiet_repo_note("o/r", None)
        self.assertIn("o/r", note)
        self.assertIn("did not answer", note)

    def test_an_empty_answer_is_not_confused_with_no_answer(self):
        # The distinction is the point: one is a forge that is unreachable, the
        # other is a forge that replied and had nothing to say.
        self.assertNotEqual(lib.quiet_repo_note("o/r", None),
                            lib.quiet_repo_note("o/r", []))

    def test_an_empty_forge_repo_names_the_cause_a_mirror_has(self):
        # Forgejo creates a mirror with `has_actions: false`, so it carries the
        # code and runs nothing. Without this the board is silent in exactly the
        # case someone has just stood a mirror up and believes it is working.
        note = lib.quiet_repo_note("jimmy/MWServer", [], from_forge=True)
        self.assertIn("Actions", note)
        self.assertIn("mirror", note)

    def test_an_empty_github_repo_does_not_mention_mirrors(self):
        note = lib.quiet_repo_note("o/r", [], from_forge=False)
        self.assertNotIn("mirror", note)

    def test_every_note_names_the_repo(self):
        for runs in (None, []):
            for forge in (True, False):
                with self.subTest(runs=runs, forge=forge):
                    self.assertIn("o/r",
                                  lib.quiet_repo_note("o/r", runs, from_forge=forge))


if __name__ == "__main__":
    unittest.main()
