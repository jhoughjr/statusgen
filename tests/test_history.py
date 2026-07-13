#!/usr/bin/env python3
"""Integration tests for bin/collect/history.py's per-board history.

Builds a throwaway git repo with hand-crafted status commits, runs the real
collector against it (STATUS_SITE_DIR), and asserts the shape of the History
board it emits — the per-board split, auto-refresh exclusion, "· also"
cross-board annotation, recency ordering, and manifest-driven icons. No
third-party deps: stdlib unittest + git.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "bin", "collect", "history.py")
DEFAULT_ICON = "📋"


def run(*args, cwd, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class PerBoardHistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="history-test-")
        self.env = {**os.environ, "STATUS_SITE_DIR": self.dir,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        run("git", "init", "-q", cwd=self.dir)
        # Titles + optional icons the board pulls in per slug. clauffice carries
        # an icon; watts deliberately omits one to exercise the default.
        self._write("status.json", json.dumps([
            {"slug": "clauffice", "title": "Clauffice", "icon": "🏢"},
            {"slug": "watts", "title": "Watts"},
            {"slug": "fleet", "title": "Fleet Health"},
        ]))
        # A history of pushes, oldest first. Each entry: which boards changed +
        # the commit subject. Content is bumped so git records a real change.
        self._commit(["clauffice", "watts"], "status: shared update (2026-01-01)",
                     "2026-01-01T12:00:00")
        self._commit(["fleet"], "status: scheduled refresh (2026-01-02)",
                     "2026-01-02T12:00:00")   # auto — must be excluded
        self._commit(["clauffice"], "by-hand tweak with no status prefix",
                     "2026-01-03T12:00:00")   # edit — kept
        self._commit(["watts"], "status: watts pipeline (2026-01-04)",
                     "2026-01-04T12:00:00")

        run(sys.executable, SCRIPT, cwd=self.dir, env=self.env)
        with open(os.path.join(self.dir, "history", "board.json")) as f:
            self.board = json.load(f)
        self.consoles = [s for s in self.board["sections"] if s["kind"] == "console"]

    def _write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def _commit(self, boards, subject, when):
        for b in boards:
            self._write(f"{b}/board.json", json.dumps({"n": subject}))
        run("git", "add", "-A", cwd=self.dir)
        env = {**self.env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        run("git", "commit", "-q", "-m", subject, cwd=self.dir, env=env)

    def titles(self):
        return [c["title"] for c in self.consoles]

    def console(self, title):
        return next(c for c in self.consoles if c["title"] == title)

    def test_one_console_per_active_board(self):
        # clauffice + watts have authored/edit pushes; fleet only an auto one.
        self.assertEqual(set(self.titles()), {"Clauffice", "Watts"})

    def test_auto_only_board_excluded(self):
        self.assertNotIn("Fleet Health", self.titles())

    def test_sections_ordered_by_recency(self):
        # watts' latest push (01-04) is newer than clauffice's (01-03).
        self.assertEqual(self.titles(), ["Watts", "Clauffice"])

    def test_cross_board_push_annotated(self):
        shared = next(ln for ln in self.console("Clauffice")["lines"]
                      if "shared update" in ln["text"])
        self.assertIn("also watts", shared["meta"])

    def test_by_hand_commit_kept_and_toned(self):
        tweak = next(ln for ln in self.console("Clauffice")["lines"]
                     if "by-hand tweak" in ln["text"])
        self.assertEqual(tweak["status"], "edit")
        self.assertEqual(tweak["tone"], "wip")

    def test_counts_reflect_kept_pushes(self):
        self.assertEqual(self.console("Clauffice")["count"], "showing 2 of 2")

    def test_icon_from_manifest_with_default(self):
        self.assertEqual(self.console("Clauffice")["icon"], "🏢")   # from manifest
        self.assertEqual(self.console("Watts")["icon"], DEFAULT_ICON)  # fallback


class MissingSiteTest(unittest.TestCase):
    def test_errors_without_site_dir(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUS_SITE_DIR", "ROOST_STATUS_SITE")}
        env["HOME"] = tempfile.mkdtemp()  # no ~/.roostrc to fall back to
        r = subprocess.run([sys.executable, SCRIPT], env=env,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no site dir", r.stderr)


if __name__ == "__main__":
    unittest.main()
