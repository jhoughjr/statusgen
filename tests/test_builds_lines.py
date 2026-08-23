#!/usr/bin/env python3
"""Unit tests for builds.py — the manifest → console-line mapping, and the
multi-source merge that lets client and server builds share one feed.

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
SRC = {"label": "Phoenix", "logo": "ts", "index": "http://x/phoenix/index.json", "vault": VAULT}
FILE = {
    "name": "Phoenix-2026-07-13-abc1234.zip",
    "size": 104857600,
    "mtime": "2026-07-13T21:42:00Z",
}


class BuildLinesTest(unittest.TestCase):
    def test_mtime_is_passed_through_as_ts_untouched(self):
        [line] = builds.build_lines([dict(FILE)], SRC)
        # The renderer localizes this; it must reach it as a parseable
        # UTC instant, not a preformatted string.
        self.assertEqual(line["ts"], "2026-07-13T21:42:00Z")

    def test_meta_carries_size_only_and_no_baked_timestamp(self):
        [line] = builds.build_lines([dict(FILE)], SRC)
        self.assertEqual(line["meta"], "· 100 MB")
        # The old bug: "2026-07-13 21:42" baked into meta.
        self.assertNotIn("21:42", line["meta"])
        self.assertNotIn("2026", line["meta"])

    def test_line_carries_name_status_and_vault_href(self):
        [line] = builds.build_lines([dict(FILE)], SRC)
        self.assertEqual(line["text"], FILE["name"])
        self.assertEqual(line["status"], "signed")
        self.assertEqual(line["href"], VAULT + "/" + FILE["name"])

    def test_only_newest_is_toned_go(self):
        files = [dict(FILE, name=f"b{i}.zip") for i in range(3)]
        lines = builds.build_lines(files, SRC)
        self.assertEqual([l["tone"] for l in lines], ["go", "none", "none"])

    def test_keeps_at_most_five(self):
        files = [dict(FILE, name=f"b{i}.zip") for i in range(9)]
        self.assertEqual(len(builds.build_lines(files, SRC)), 5)

    def test_missing_mtime_omits_ts_rather_than_emitting_empty(self):
        f = dict(FILE)
        del f["mtime"]
        [line] = builds.build_lines([f], SRC)
        self.assertNotIn("ts", line)
        self.assertEqual(line["meta"], "· 100 MB")

    def test_name_is_url_quoted_in_href(self):
        [line] = builds.build_lines([dict(FILE, name="Phoenix Repair POS.zip")], SRC)
        self.assertEqual(line["href"], VAULT + "/Phoenix%20Repair%20POS.zip")

    def test_the_source_logo_marks_every_line(self):
        [line] = builds.build_lines([dict(FILE)], SRC)
        self.assertEqual(line["logo"], "ts")

    def test_a_source_without_a_logo_emits_none(self):
        src = dict(SRC)
        del src["logo"]
        [line] = builds.build_lines([dict(FILE)], src)
        self.assertNotIn("logo", line)


class SourcesFromTest(unittest.TestCase):
    def test_legacy_index_and_vault_mean_one_phoenix_source(self):
        cfg = {"ROOST_BUILDS_INDEX": "http://x/phoenix/index.json", "ROOST_BUILDS_VAULT": VAULT}
        [src] = builds.sources_from(cfg)
        self.assertEqual(src["label"], "Phoenix")
        self.assertEqual(src["logo"], "ts")
        self.assertEqual(src["index"], "http://x/phoenix/index.json")

    def test_sources_json_wins_over_the_legacy_pair(self):
        cfg = {
            "ROOST_BUILDS_INDEX": "http://x/legacy/index.json",
            "ROOST_BUILDS_VAULT": VAULT,
            "ROOST_BUILDS_SOURCES":
                '[{"label": "MWServer", "logo": "swift", "index": "http://x/mw/index.json", "vault": "%s"}]' % VAULT,
        }
        [src] = builds.sources_from(cfg)
        self.assertEqual(src["label"], "MWServer")

    def test_a_source_missing_index_or_vault_is_dropped(self):
        cfg = {"ROOST_BUILDS_SOURCES": '[{"label": "broken", "logo": "swift"}]'}
        self.assertEqual(builds.sources_from(cfg), [])

    def test_no_config_means_no_sources(self):
        self.assertEqual(builds.sources_from({}), [])


class CollectLinesTest(unittest.TestCase):
    PHOENIX = {"label": "Phoenix", "logo": "ts", "index": "http://x/p", "vault": VAULT}
    MWSERVER = {"label": "MWServer", "logo": "swift", "index": "http://x/m",
                "vault": "https://vault.example.net/api/files/mwserver-builds"}

    def fetch_for(self, manifests):
        return lambda source: manifests[source["label"]]

    def test_two_products_merge_newest_first_across_sources(self):
        fetch = self.fetch_for({
            "Phoenix": [dict(FILE, name="p1.zip", mtime="2026-08-23T05:00:00Z"),
                        dict(FILE, name="p2.zip", mtime="2026-08-21T05:00:00Z")],
            "MWServer": [dict(FILE, name="m1.zip", mtime="2026-08-22T05:00:00Z")],
        })
        lines, notes = builds.collect_lines([self.PHOENIX, self.MWSERVER], fetch, [])
        self.assertEqual([l["text"] for l in lines], ["p1.zip", "m1.zip", "p2.zip"])
        self.assertEqual(notes, [])

    def test_the_newest_of_each_product_is_green(self):
        fetch = self.fetch_for({
            "Phoenix": [dict(FILE, name="p1.zip", mtime="2026-08-23T05:00:00Z"),
                        dict(FILE, name="p2.zip", mtime="2026-08-21T05:00:00Z")],
            "MWServer": [dict(FILE, name="m1.zip", mtime="2026-08-22T05:00:00Z")],
        })
        lines, _ = builds.collect_lines([self.PHOENIX, self.MWSERVER], fetch, [])
        tones = {l["text"]: l["tone"] for l in lines}
        self.assertEqual(tones, {"p1.zip": "go", "m1.zip": "go", "p2.zip": "none"})

    def test_a_failing_source_keeps_its_existing_lines_instead_of_vanishing(self):
        def fetch(source):
            if source["label"] == "MWServer":
                raise OSError("connection refused")
            return [dict(FILE, name="p1.zip", mtime="2026-08-23T05:00:00Z")]
        existing = [
            {"text": "m-old.zip", "logo": "swift", "ts": "2026-08-20T05:00:00Z"},
            {"text": "p-old.zip", "logo": "ts", "ts": "2026-08-19T05:00:00Z"},
        ]
        lines, notes = builds.collect_lines([self.PHOENIX, self.MWSERVER], fetch, existing)
        self.assertEqual([l["text"] for l in lines], ["p1.zip", "m-old.zip"])
        self.assertEqual(len(notes), 1)
        self.assertIn("MWServer", notes[0])

    def test_every_source_failing_with_no_existing_lines_yields_nothing(self):
        def fetch(source):
            raise OSError("down")
        lines, notes = builds.collect_lines([self.PHOENIX], fetch, [])
        self.assertEqual(lines, [])
        self.assertEqual(len(notes), 1)


if __name__ == "__main__":
    unittest.main()
