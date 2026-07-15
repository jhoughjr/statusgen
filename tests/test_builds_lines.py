#!/usr/bin/env python3
"""Unit tests for builds.build_lines — the manifest → console-line mapping.

The manifest's `mtime` is UTC. BOARD_SCHEMA requires collectors to emit it
as `ts` so the renderer localizes it per viewer; baking a preformatted
string into `meta` showed the runner's UTC clock to everyone.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import builds


VAULT = "https://vault.example.net/api/files/phoenix-builds"
FILE = {
    "name": "Phoenix-2026-07-13-abc1234.zip",
    "size": 104857600,
    "mtime": "2026-07-13T21:42:00Z",
}


class BuildLinesTest(unittest.TestCase):
    def test_mtime_is_passed_through_as_ts_untouched(self):
        [line] = builds.build_lines([dict(FILE)], VAULT)
        # The renderer localizes this; it must reach it as a parseable
        # UTC instant, not a preformatted string.
        self.assertEqual(line["ts"], "2026-07-13T21:42:00Z")

    def test_meta_carries_size_only_and_no_baked_timestamp(self):
        [line] = builds.build_lines([dict(FILE)], VAULT)
        self.assertEqual(line["meta"], "· 100 MB")
        # The old bug: "2026-07-13 21:42" baked into meta.
        self.assertNotIn("21:42", line["meta"])
        self.assertNotIn("2026", line["meta"])

    def test_line_carries_name_status_and_vault_href(self):
        [line] = builds.build_lines([dict(FILE)], VAULT)
        self.assertEqual(line["text"], FILE["name"])
        self.assertEqual(line["status"], "signed")
        self.assertEqual(line["href"], VAULT + "/" + FILE["name"])

    def test_only_newest_is_toned_go(self):
        files = [dict(FILE, name=f"b{i}.zip") for i in range(3)]
        lines = builds.build_lines(files, VAULT)
        self.assertEqual([l["tone"] for l in lines], ["go", "none", "none"])

    def test_keeps_at_most_five(self):
        files = [dict(FILE, name=f"b{i}.zip") for i in range(9)]
        self.assertEqual(len(builds.build_lines(files, VAULT)), 5)

    def test_missing_mtime_omits_ts_rather_than_emitting_empty(self):
        f = dict(FILE)
        del f["mtime"]
        [line] = builds.build_lines([f], VAULT)
        self.assertNotIn("ts", line)
        self.assertEqual(line["meta"], "· 100 MB")

    def test_name_is_url_quoted_in_href(self):
        [line] = builds.build_lines([dict(FILE, name="Phoenix Repair POS.zip")], VAULT)
        self.assertEqual(line["href"], VAULT + "/Phoenix%20Repair%20POS.zip")


if __name__ == "__main__":
    unittest.main()
