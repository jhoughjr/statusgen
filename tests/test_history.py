#!/usr/bin/env python3
"""Integration tests for bin/collect/history.py.

Builds a throwaway git repo with hand-crafted status commits, runs the real
collector against it (STATUS_SITE_DIR), and asserts the History it emits:
the umbrella summary (per-board split, auto-refresh exclusion, "· also"
annotation, ordering, manifest icons, detail links) and the per-board detail
pages under <slug>/history/ (full log, back-links, browsable shell). No
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
        self._write("status.json", json.dumps([
            {"slug": "clauffice", "title": "Clauffice", "icon": "🏢"},
            {"slug": "watts", "title": "Watts"},
            {"slug": "fleet", "title": "Fleet Health"},
        ]))
        self._commit(["clauffice", "watts"], "status: shared update (2026-01-01)",
                     "2026-01-01T12:00:00")
        self._commit(["fleet"], "status: scheduled refresh (2026-01-02)",
                     "2026-01-02T12:00:00")   # auto — must be excluded
        self._commit(["clauffice"], "by-hand tweak with no status prefix",
                     "2026-01-03T12:00:00")   # edit — kept
        self._commit(["watts"], "status: watts pipeline (2026-01-04)",
                     "2026-01-04T12:00:00")
        # A regen of a detail page — a nested <slug>/history/ path must NOT be
        # counted as a push to that board.
        self._commit_paths(["clauffice/history/board.json"],
                           "status: regen (2026-01-05)", "2026-01-05T12:00:00")

        run(sys.executable, SCRIPT, cwd=self.dir, env=self.env)
        with open(os.path.join(self.dir, "history", "board.json")) as f:
            self.board = json.load(f)
        self.consoles = [s for s in self.board["sections"] if s["kind"] == "console"]

    def _write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def _commit_paths(self, rels, subject, when):
        for rel in rels:
            self._write(rel, json.dumps({"n": subject}))
        run("git", "add", "-A", cwd=self.dir)
        env = {**self.env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        run("git", "commit", "-q", "-m", subject, cwd=self.dir, env=env)

    def _commit(self, boards, subject, when):
        self._commit_paths([f"{b}/board.json" for b in boards], subject, when)

    def titles(self):
        return [c["title"] for c in self.consoles]

    def console(self, title):
        return next(c for c in self.consoles if c["title"] == title)

    def detail(self, slug):
        with open(os.path.join(self.dir, slug, "history", "board.json")) as f:
            return json.load(f)

    # ---- umbrella summary --------------------------------------------------

    def test_one_console_per_active_board(self):
        self.assertEqual(set(self.titles()), {"Clauffice", "Watts"})

    def test_auto_only_board_excluded(self):
        self.assertNotIn("Fleet Health", self.titles())

    def test_sections_ordered_by_recency(self):
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

    def test_nested_history_path_not_counted(self):
        # the 2026-01-05 regen touched only clauffice/history/board.json
        self.assertEqual(self.console("Clauffice")["count"], "showing 2 of 2")

    def test_icon_from_manifest_with_default(self):
        self.assertEqual(self.console("Clauffice")["icon"], "🏢")
        self.assertEqual(self.console("Watts")["icon"], DEFAULT_ICON)

    def test_umbrella_titles_link_to_detail(self):
        self.assertEqual(self.console("Clauffice")["href"], "/clauffice/history/")

    # ---- per-board detail pages -------------------------------------------

    def test_detail_page_generated_per_active_board(self):
        self.assertTrue(os.path.exists(os.path.join(self.dir, "clauffice", "history", "board.json")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "watts", "history", "board.json")))
        # fleet is auto-only → no detail page
        self.assertFalse(os.path.exists(os.path.join(self.dir, "fleet", "history", "board.json")))

    def test_detail_page_has_full_log_and_backlinks(self):
        d = self.detail("clauffice")
        self.assertEqual(d["title"], "Clauffice — History")
        hrefs = [l["href"] for l in d["links"]]
        self.assertIn("../", hrefs)          # back to the board
        self.assertIn("/history/", hrefs)    # to the umbrella
        console = next(s for s in d["sections"] if s["kind"] == "console")
        self.assertEqual(console["count"], "2 of 2")

    def test_detail_shell_is_browsable(self):
        shell = os.path.join(self.dir, "watts", "history", "index.html")
        self.assertTrue(os.path.exists(shell))
        self.assertIn("board.json", open(shell).read())


class MissingSiteTest(unittest.TestCase):
    def test_errors_without_site_dir(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("STATUS_SITE_DIR", "ROOST_STATUS_SITE")}
        env["HOME"] = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, SCRIPT], env=env,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no site dir", r.stderr)


if __name__ == "__main__":
    unittest.main()
