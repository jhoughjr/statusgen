"""A collector's write stamps the section it writes with `generatedAt`, so the renderer can say who wrote it (house#92).

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "collect"))
import lib  # noqa: E402

STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class SectionStampTest(unittest.TestCase):
    def test_upsert_section_stamps_the_section_it_writes(self):
        board = {"sections": [{"kind": "banner", "text": "by a person"}]}
        lib.upsert_section(board, "Stacks", {"kind": "console", "title": "Stacks", "lines": []}, after_kind="banner")
        stacks = next(s for s in board["sections"] if s.get("title") == "Stacks")
        self.assertRegex(stacks["generatedAt"], STAMP)
        self.assertNotIn("generatedAt", board["sections"][0], "the hand-written banner stays unstamped")

    def test_a_tile_written_by_a_collector_stamps_its_compare_section(self):
        board = {"sections": [{"kind": "compare", "columns": [{"title": "Phoenix", "items": [{"label": "Tests green", "n": "0"}]}]}]}
        self.assertTrue(lib.upsert_compare_tile(board, "Phoenix", "Tests green", 12))
        self.assertRegex(board["sections"][0]["generatedAt"], STAMP)
        board["sections"][0].pop("generatedAt")
        self.assertTrue(lib.set_compare_tile(board, "Tests green", 13, column="Phoenix"))
        self.assertRegex(board["sections"][0]["generatedAt"], STAMP)


if __name__ == "__main__":
    unittest.main()
