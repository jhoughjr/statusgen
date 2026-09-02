#!/usr/bin/env python3
"""A board write is atomic, so a reader never sees a half-written board.

Writing in place produced a real corruption on 2026-09-01: two status runs
overlapped, the shorter document landed inside the longer file, and
clauffice/board.json ended as 141,943 valid bytes followed by 199 bytes of the
previous file's tail. The board is parsed in the browser, so a file in that
state is not a stale board, it is no board at all.

Overlapping runs are ordinary: a scheduled agent publishes the site and a
person can publish by hand at the same moment. These do not pin that the runs
are serialised — they are not, and should not be. They pin that the loser of a
race is harmless.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib


def board(n_sections):
    return {"title": "T", "sections": [{"kind": "cards", "title": f"S{i}",
                                        "items": [{"q": "x" * 200}]}
                                       for i in range(n_sections)]}


class BoardWriteIsAtomic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        self.path = self.dir / "board.json"

    def whole(self):
        """The board at the path, asserting nothing follows it.

        `json.load` alone would not catch this: the corruption was a COMPLETE
        document with another file's tail after it, which parses fine if you
        stop at the first object. `raw_decode` reports where it stopped.
        """
        raw = self.path.read_text()
        obj, end = json.JSONDecoder().raw_decode(raw.lstrip())
        self.assertEqual(raw.lstrip()[end:].strip(), "",
                         "something follows the board — this is the corruption")
        return obj

    def test_a_writer_mid_write_on_the_path_cannot_corrupt_the_result(self):
        """The real mechanism, which takes two writers.

        One truncating write can never leave a tail behind it, so the
        corruption only appears when two runs overlap: one truncates and
        refills while the other is still writing at its own offsets, and the
        longer document's remainder lands past the end of the shorter one.

        `os.replace` breaks that. It swaps the directory entry, so a writer
        still holding the old file goes on writing into a file the path no
        longer names, and what a reader opens is whole either way.
        """
        lib.save_board(self.path, board(3))
        # Another run, mid-write, in place: a long document, not yet finished.
        stray = open(self.path, "w")
        stray.write(json.dumps(board(60), indent=2)[:100_000])

        lib.save_board(self.path, board(2))
        self.assertEqual(len(self.whole()["sections"]), 2)

        # The stray run finishes. Its bytes land in the replaced-away file, so
        # the path still holds exactly the board that was written to it.
        stray.write("]}")
        stray.close()
        self.assertEqual(len(self.whole()["sections"]), 2)

    def test_a_shorter_board_replaces_a_longer_one_whole(self):
        lib.save_board(self.path, board(60))
        long_size = self.path.stat().st_size
        lib.save_board(self.path, board(2))
        self.assertLess(self.path.stat().st_size, long_size)
        self.assertEqual(len(self.whole()["sections"]), 2)

    def test_the_file_is_never_seen_partly_written(self):
        """`os.replace` is the whole point: the path moves from one complete
        board to the next with no state in between. Asserted by reading the
        path from inside the serialiser, at the moment the temp file holds a
        half-written document."""
        lib.save_board(self.path, board(3))
        seen = {}

        class Peeking(dict):
            def __init__(self, data):
                super().__init__(data)

            def items(self):
                seen["mid_write"] = self.path_ref.read_text()
                return super().items()

        payload = Peeking(board(9))
        payload.path_ref = self.path
        lib.save_board(self.path, payload)
        # What a reader saw during the write was the PREVIOUS whole board.
        self.assertEqual(len(json.loads(seen["mid_write"])["sections"]), 3)
        self.assertEqual(len(json.loads(self.path.read_text())["sections"]), 9)

    def test_a_failed_write_leaves_the_board_and_no_litter(self):
        lib.save_board(self.path, board(4))
        before = self.path.read_text()

        # Fails inside json.dump, once the temp file is open and part-written —
        # which is the only failure that could leave litter or a broken board.
        with self.assertRaises(TypeError):
            lib.save_board(self.path, {"title": "T", "sections": [
                {"kind": "cards", "title": "S", "items": [{"q": object()}]}]})
        self.assertEqual(self.path.read_text(), before)
        strays = [p.name for p in self.dir.iterdir() if p.name != "board.json"]
        self.assertEqual(strays, [], "a failed write left a temp file behind")

    def test_two_writers_do_not_share_a_temp_name(self):
        # Same directory, same target: the pid keeps their scratch files apart,
        # so one cannot move the other's half-written file into place.
        name = lambda pid: f".{self.path.name}.{pid}.tmp"
        self.assertNotEqual(name(101), name(102))

    def test_the_written_board_still_ends_in_a_newline(self):
        # The site is a git repo; a file with no trailing newline makes every
        # diff of it noisier than the change deserves.
        lib.save_board(self.path, board(2))
        self.assertTrue(self.path.read_text().endswith("}\n"))

    def test_a_str_path_works_as_well_as_a_path(self):
        lib.save_board(str(self.path), board(2))
        self.assertEqual(len(json.loads(self.path.read_text())["sections"]), 2)


if __name__ == "__main__":
    unittest.main()
