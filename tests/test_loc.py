#!/usr/bin/env python3
"""Unit tests for collect/loc.py — the lines-of-code collector.

The behaviour worth pinning down: which files a bucket counts, and what happens
when a bucket's repo isn't on the machine doing the push (two machines write
this site and they don't have the same clones — counting a missing repo as 0
would publish a confident wrong number).

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import copy
import os
import sys
import tempfile
import unittest
import pathlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))
import loc  # noqa: E402


def write(root, rel, lines):
    p = pathlib.Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"line {i}\n" for i in range(lines)))
    return p


class TestBucketLines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = self.tmp.name
        write(r, "src/app/a.ts", 10)
        write(r, "src/app/a.test.ts", 4)
        write(r, "src/app/nested/b.spec.tsx", 3)
        write(r, "src/main/m.ts", 7)
        write(r, "src/shared/generated/api.ts", 100)
        write(r, "src/app/notes.md", 50)
        write(r, "src/app/test/helper.ts", 5)   # test by directory
        write(r, "node_modules/pkg/index.ts", 999)
        self.root = r

    def tearDown(self):
        self.tmp.cleanup()

    def bucket(self, **kw):
        base = {"label": "b", "root": self.root, "ext": [".ts", ".tsx"]}
        base.update(kw)
        return loc.bucket_lines(base)

    def test_counts_only_listed_extensions(self):
        # notes.md (50) is excluded by ext; node_modules (999) is always pruned.
        self.assertEqual(self.bucket(paths=["src"]), 10 + 4 + 3 + 7 + 5)

    def test_generated_is_pruned_from_a_parent_walk(self):
        # src/shared/generated (100) must not land in a src-wide count.
        self.assertNotIn(100, [self.bucket(paths=["src"])])

    def test_a_bucket_can_target_a_pruned_directory_directly(self):
        # Pruning applies to directories met during the walk, not to the start
        # point — so a generated bucket names its directory and still counts.
        self.assertEqual(self.bucket(paths=["src/shared/generated"]), 100)

    def test_tests_only_matches_by_filename_and_directory(self):
        self.assertEqual(self.bucket(paths=["src"], tests="only"), 4 + 3 + 5)

    def test_tests_exclude_is_the_complement(self):
        self.assertEqual(self.bucket(paths=["src"], tests="exclude"), 10 + 7)

    def test_exclude_drops_a_subpath(self):
        self.assertEqual(self.bucket(paths=["src"], exclude=["src/main"]), 10 + 4 + 3 + 5)

    def test_missing_root_returns_none_not_zero(self):
        self.assertIsNone(loc.bucket_lines({"label": "gone", "root": "/nope/nowhere"}))

    def test_paths_may_glob(self):
        # A hardcoded module list under-counts the moment a module is added;
        # this is the regression that motivated glob support.
        write(self.root, "Sources/A/GeneratedSources/g.ts", 9)
        write(self.root, "Sources/B/GeneratedSources/g.ts", 11)
        write(self.root, "Sources/B/hand.ts", 100)
        self.assertEqual(self.bucket(paths=["Sources/*/GeneratedSources"]), 20)

    def test_a_glob_matching_nothing_counts_zero_not_everything(self):
        self.assertEqual(self.bucket(paths=["Sources/*/Nope"]), 0)

    def test_exclude_may_glob(self):
        write(self.root, "Sources/A/GeneratedSources/g.ts", 9)
        write(self.root, "Sources/B/GeneratedSources/g.ts", 11)
        write(self.root, "Sources/B/hand.ts", 100)
        self.assertEqual(self.bucket(paths=["Sources"], exclude=["Sources/*/GeneratedSources"]), 100)

    def test_no_ext_filter_counts_every_file(self):
        self.assertEqual(self.bucket(paths=["src/app"], ext=[]), 10 + 4 + 3 + 50 + 5)


class TestPatchChart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        write(self.tmp.name, "a.ts", 12)

    def tearDown(self):
        self.tmp.cleanup()

    def board(self, kind="barchart"):
        key = "slices" if kind == "pie" else "series"
        return {"sections": [{
            "kind": kind, "title": "Codebase", "asOf": "2026-07-07",
            key: [{"label": "Here", "value": 1}, {"label": "Gone", "value": 555}],
        }]}

    def chart(self, **kw):
        base = {"title": "Codebase", "buckets": [
            {"label": "Here", "root": self.tmp.name, "ext": [".ts"], "fill": "code"},
            {"label": "Gone", "root": "/nope/nowhere", "fill": "gen"},
        ]}
        base.update(kw)
        return base

    def test_counts_replace_the_series_and_sort_by_size(self):
        b = self.board()
        self.assertTrue(loc.patch_chart(b, self.chart()))
        series = b["sections"][0]["series"]
        # Gone keeps its previous 555 and so still leads.
        self.assertEqual([s["label"] for s in series], ["Gone", "Here"])
        self.assertEqual([s["value"] for s in series], [555, 12])

    def test_missing_root_keeps_the_previous_value(self):
        b = self.board()
        loc.patch_chart(b, self.chart())
        gone = next(s for s in b["sections"][0]["series"] if s["label"] == "Gone")
        self.assertEqual(gone["value"], 555)

    def test_missing_root_with_no_previous_value_counts_zero(self):
        b = self.board()
        b["sections"][0]["series"] = [{"label": "Here", "value": 1}]
        loc.patch_chart(b, self.chart())
        gone = next(s for s in b["sections"][0]["series"] if s["label"] == "Gone")
        self.assertEqual(gone["value"], 0)

    def test_all_roots_missing_leaves_the_section_untouched(self):
        b = self.board()
        before = copy.deepcopy(b)
        chart = self.chart(buckets=[{"label": "Gone", "root": "/nope/nowhere"}])
        self.assertTrue(loc.patch_chart(b, chart))
        self.assertEqual(b, before)

    def test_pie_writes_slices_with_tones(self):
        b = self.board(kind="pie")
        chart = self.chart(buckets=[
            {"label": "Here", "root": self.tmp.name, "ext": [".ts"], "tone": "go"}])
        loc.patch_chart(b, chart)
        self.assertEqual(b["sections"][0]["slices"], [{"label": "Here", "value": 12, "tone": "go"}])

    def test_fill_and_tone_carry_through(self):
        b = self.board()
        loc.patch_chart(b, self.chart())
        fills = {s["label"]: s.get("fill") for s in b["sections"][0]["series"]}
        self.assertEqual(fills, {"Here": "code", "Gone": "gen"})

    def test_asof_is_dropped_once_a_collector_owns_the_section(self):
        b = self.board()
        loc.patch_chart(b, self.chart())
        self.assertNotIn("asOf", b["sections"][0])

    def test_absent_section_is_a_no_op_not_an_error(self):
        b = {"sections": [{"kind": "barchart", "title": "Something else"}]}
        self.assertFalse(loc.patch_chart(b, self.chart()))


class TestRenderNote(unittest.TestCase):
    def setUp(self):
        self.buckets = [{"label": "A"}, {"label": "B"}]
        self.counts = {"A": 1200, "B": 300}

    def note(self, template):
        return loc.render_note(template, self.buckets, self.counts)

    def test_totals_raw_and_humanized(self):
        self.assertEqual(self.note("{total} / {total_h}"), "1,500 / 1.5k")

    def test_per_bucket_lookup(self):
        self.assertEqual(self.note("{b:A} {bh:A} {b:B}"), "1,200 1.2k 300")

    def test_bucket_count_and_stamp(self):
        self.assertEqual(self.note("{n}"), "2")
        self.assertRegex(self.note("{stamp}"), r"^\d{4}-\d{2}-\d{2}$")

    def test_unknown_placeholder_survives_verbatim(self):
        # A typo should show up on the board, not raise mid-push.
        self.assertEqual(self.note("{nope}"), "{nope}")

    def test_missing_bucket_reads_zero(self):
        self.assertEqual(self.note("{b:Absent}"), "0")

    def test_no_template_is_none(self):
        self.assertIsNone(loc.render_note(None, self.buckets, self.counts))


if __name__ == "__main__":
    unittest.main()
