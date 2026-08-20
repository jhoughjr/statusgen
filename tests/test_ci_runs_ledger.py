#!/usr/bin/env python3
"""Unit tests for the CI run ledger — the append-only record behind the feed.

The feed answers "what just happened" inside a small sliding window, so a
day's builds can scroll out of it and read as never having run (reported
2026-08-20: five proto/step builds visible in the morning were gone by night).
The ledger answers "everything that happened": a run that enters it never
leaves, however far the window has moved on.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import ci_status


def run(rid, conclusion="success", branch="dev", created="2026-08-20T10:00:00Z",
        updated="2026-08-20T10:20:00Z", event="push", workflow="Build"):
    return {"databaseId": rid, "conclusion": conclusion, "status": "completed",
            "headBranch": branch, "event": event, "workflowName": workflow,
            "createdAt": created, "updatedAt": updated,
            "url": f"u/{rid}"}


class RunLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site = pathlib.Path(self.tmp.name)
        (self.site / "clauffice").mkdir()

    def ledger(self):
        return json.loads((self.site / "clauffice/runs/ledger.json").read_text())

    def page(self):
        return json.loads((self.site / "clauffice/runs/board.json").read_text())

    def console(self):
        return next(s for s in self.page()["sections"] if s["kind"] == "console")

    def test_appends_and_dedupes_by_run_id(self):
        src = [("o/r", "Repo", None, [run(1), run(2)])]
        added, total = ci_status.update_ledger(self.site, "clauffice", src)
        self.assertEqual((added, total), (2, 2))
        added, total = ci_status.update_ledger(self.site, "clauffice", src)
        self.assertEqual((added, total), (0, 2))

    def test_a_run_that_left_the_window_stays(self):
        """The reason the ledger exists."""
        ci_status.update_ledger(self.site, "clauffice",
                                [("o/r", "Repo", None, [run(1, created="2026-08-19T01:00:00Z")])])
        ci_status.update_ledger(self.site, "clauffice",
                                [("o/r", "Repo", None, [run(9, created="2026-08-20T09:00:00Z")])])
        ids = [e["id"] for e in self.ledger()["runs"]]
        self.assertEqual(ids, [9, 1])
        self.assertEqual(len(self.console()["lines"]), 2)

    def test_an_unsettled_run_waits_for_its_verdict(self):
        unsettled = dict(run(5), conclusion=None, status="in_progress")
        _, total = ci_status.update_ledger(self.site, "clauffice",
                                           [("o/r", "Repo", None, [unsettled])])
        self.assertEqual(total, 0)

    def test_page_and_shell_are_written(self):
        ci_status.update_ledger(self.site, "clauffice",
                                [("o/r", "Repo", "swift", [run(1)])])
        page = self.page()
        self.assertEqual([s["kind"] for s in page["sections"]],
                         ["stats", "barchart", "console"])
        self.assertTrue((self.site / "clauffice/runs/index.html").exists())
        line = self.console()["lines"][0]
        self.assertEqual(line["logo"], "swift")
        self.assertEqual(line["href"], "u/1")

    def test_the_page_passes_the_schema_gate(self):
        """`roost status` validates every <site>/*/*/board.json before deploy;
        a page that fails the gate kills the whole push."""
        ci_status.update_ledger(self.site, "clauffice",
                                [("o/r", "Repo", None, [run(1), run(2, "failure")])])
        r = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "validate-board.py"),
                            str(self.site / "clauffice/runs/board.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_renders_at_most_the_cap_but_records_everything(self):
        runs = [run(i, created=f"2026-08-{10 + i % 10:02d}T00:{i % 60:02d}:00Z")
                for i in range(ci_status.LEDGER_MAX + 50)]
        _, total = ci_status.update_ledger(self.site, "clauffice",
                                           [("o/r", "Repo", None, runs)])
        self.assertEqual(total, ci_status.LEDGER_MAX + 50)
        self.assertEqual(len(self.console()["lines"]), ci_status.LEDGER_MAX)

    def test_a_cancelled_run_in_the_ledger_needs_overlap_evidence_too(self):
        cancelled = run(1, "cancelled", created="2026-08-19T13:00:00Z",
                        updated="2026-08-19T15:00:00Z")
        later_push = run(2, "success", created="2026-08-19T20:00:00Z",
                         updated="2026-08-19T20:30:00Z")
        ci_status.update_ledger(self.site, "clauffice",
                                [("o/r", "Repo", None, [later_push, cancelled])])
        cancelled_line = next(ln for ln in self.console()["lines"]
                              if ln["status"] == "cancelled")
        self.assertNotIn("superseded", cancelled_line.get("meta", ""))


if __name__ == "__main__":
    unittest.main()
