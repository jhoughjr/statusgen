#!/usr/bin/env python3
"""Unit tests for the merged build compare tile and lib.fmt_age.

One tile carries a trunk's whole build state: the verdict as the headline, and
the commit that verdict was measured at on the tile's `meta` line. It was two
tiles until 2026-08-25, and the second one existed because ✓/✗ is least useful
exactly when a build goes red — the board stopped saying anything about what
still worked, so red read as "everything is unknown" rather than "here is the
last thing that wasn't".

These tests pin that the evidence still answers the second question while the
current build is red, and that merging it in did not let it start answering the
FIRST one: a bare SHA under a ✗ must never read as the SHA that failed.

Monkeypatches lib.gh_runs (no gh / network).

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib
import ci_status


RUNS = [
    {"conclusion": "failure", "headSha": "80c7a2f9911",
     "createdAt": "2026-08-04T13:32:00Z", "url": "u/red"},
    {"conclusion": "cancelled", "headSha": "3711ba0aaaa",
     "createdAt": "2026-08-04T13:18:00Z", "url": "u/cancelled"},
    {"conclusion": "success", "headSha": "4bfbe2bcccc",
     "createdAt": "2026-08-04T10:00:00Z", "url": "u/green"},
]

GREEN_FIRST = [RUNS[2]] + RUNS[:2]


def board_with(items):
    """The real board shape: one compare SECTION holding titled COLUMNS."""
    return {"sections": [{"kind": "compare", "title": "Phoenix ⟷ MWServer",
                          "columns": [{"title": "Phoenix", "items": list(items)},
                                      {"title": "MWServer", "items": []}]}]}


def columns(board):
    return board["sections"][0]["columns"]


def tile(board, label, col=0):
    return next((t for t in columns(board)[col]["items"]
                 if t.get("label") == label), None)


class BuildTileVerdict(unittest.TestCase):
    def setUp(self):
        self._real = lib.gh_runs
        self.addCleanup(lambda: setattr(lib, "gh_runs", self._real))
        lib.gh_runs = lambda repo, limit: RUNS

    def test_a_green_trunk_states_the_verdict_and_the_commit(self):
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", GREEN_FIRST, [])

        t = tile(board, "CI build")
        self.assertEqual(t["n"], "✓")
        self.assertEqual(t["tone"], "go")
        self.assertEqual(t["meta"], "4bfbe2b")
        self.assertEqual(t["href"], "u/green")
        # The TIMESTAMP travels, not a rendered age.
        self.assertEqual(t["since"], "2026-08-04T10:00:00Z")

    def test_a_red_trunk_keeps_naming_the_last_green(self):
        """The reason the evidence exists: red must not blank out the last
        good commit."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])

        t = tile(board, "CI build")
        self.assertEqual(t["n"], "✗")
        self.assertEqual(t["tone"], "you")
        self.assertIn("4bfbe2b", t["meta"])
        self.assertEqual(t["since"], "2026-08-04T10:00:00Z")

    def test_a_red_trunk_says_the_sha_is_the_last_green_not_the_failure(self):
        """The risk merging created. Under a ✓ the SHA is the commit that
        passed; under a ✗ the same bare SHA reads as the commit that failed,
        which is the opposite of what it is. The line has to say so."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        self.assertEqual(tile(board, "CI build")["meta"], "last green 4bfbe2b")

    def test_a_red_trunk_links_the_failure_it_is_reporting(self):
        """The headline is ✗, so the click has to reach the ✗. The green run
        stays reachable through the runs feed, and its SHA is on the tile."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        self.assertEqual(tile(board, "CI build")["href"], "u/red")

    def test_never_bakes_a_relative_age_into_the_tile(self):
        """The bug this replaced: the collector wrote "4bfbe2b · 24m ago" into
        board.json, which is true for as long as it takes to publish the file
        and wrong forever after. A board left open kept insisting a build had
        gone green 24 minutes ago, hours later, with no such run in the history
        directly below it — the board contradicting itself, which is worse than
        the board being stale, because the reader cannot tell which half lies."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        t = tile(board, "CI build")
        self.assertNotIn("ago", t["n"])
        self.assertNotIn("ago", t["meta"])

    def test_skips_cancelled_and_failed_commits(self):
        """A superseded (cancelled) run is not evidence of anything."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        self.assertNotIn("3711ba0", tile(board, "CI build")["meta"])
        self.assertNotIn("80c7a2f", tile(board, "CI build")["meta"])

    def test_says_so_rather_than_claiming_a_stale_green(self):
        runs = [r for r in RUNS if r["conclusion"] != "success"]
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", runs, [])

        t = tile(board, "CI build")
        self.assertEqual(t["n"], "✗")
        self.assertEqual(t["meta"], "no green in the window")
        # No stamp: there is nothing for an age to date.
        self.assertNotIn("since", t)

    def test_an_empty_window_leaves_the_board_alone(self):
        """statusgen's collector contract: absent data → board untouched.
        (main() already skips the whole pass when gh returns nothing.)"""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", [], [])
        self.assertEqual(columns(board)[0]["items"], [])

    def test_writes_only_to_its_own_column(self):
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        self.assertEqual(columns(board)[1]["items"], [])

    def test_is_idempotent(self):
        """Every status push re-runs collectors; tiles must not accumulate."""
        board = board_with([])
        for _ in range(3):
            ci_status.apply_tiles(board, "Phoenix", RUNS, [])
        labels = [i["label"] for i in columns(board)[0]["items"]]
        self.assertEqual(labels.count("CI build"), 1)


class RetiresTheSeparateLastGreenTile(unittest.TestCase):
    """The migration. An upsert never removes, so a board that carried the old
    pair would keep the "Last green" tile with the SHA it last held while the
    merged tile moved on — a tile no collector writes any more, stating a stale
    number beside the live ones in the same type."""

    def setUp(self):
        self._real = lib.gh_runs
        self.addCleanup(lambda: setattr(lib, "gh_runs", self._real))
        lib.gh_runs = lambda repo, limit: RUNS

    def test_the_old_tile_goes(self):
        board = board_with([
            {"label": "CI build", "n": "✓", "tone": "go"},
            {"label": "Last green", "n": "0000000", "tone": "go"},
        ])
        ci_status.apply_tiles(board, "Phoenix", GREEN_FIRST, [])

        labels = [i["label"] for i in columns(board)[0]["items"]]
        self.assertNotIn("Last green", labels)
        self.assertEqual(labels.count("CI build"), 1)

    def test_the_branch_suffixed_old_tiles_go_too(self):
        board = board_with([
            {"label": "CI build · dev", "n": "✓", "tone": "go"},
            {"label": "Last green · dev", "n": "0000000", "tone": "go"},
            {"label": "Last green · main", "n": "1111111", "tone": "go"},
        ])
        ci_status.apply_tiles(board, "Phoenix", GREEN_FIRST, [])

        labels = [i["label"] for i in columns(board)[0]["items"]]
        self.assertEqual([l for l in labels if l.startswith("Last green")], [])

    def test_a_dead_window_keeps_its_hands_off_the_old_tile(self):
        """Same contract as everywhere else here: with nothing settled to
        replace it with, deleting the old tile would remove information and put
        nothing in its place."""
        board = board_with([{"label": "Last green", "n": "0000000"}])
        ci_status.apply_tiles(board, "Phoenix", [], [])
        self.assertIsNotNone(tile(board, "Last green"))


class FmtAge(unittest.TestCase):
    NOW = datetime.datetime(2026, 8, 4, 12, 0, tzinfo=datetime.timezone.utc)

    def test_buckets(self):
        for iso, want in [
            ("2026-08-04T11:59:30Z", "just now"),
            ("2026-08-04T11:51:00Z", "9m ago"),
            ("2026-08-04T09:00:00Z", "3h ago"),
            ("2026-08-02T12:00:00Z", "2d ago"),
        ]:
            self.assertEqual(lib.fmt_age(iso, now=self.NOW), want, iso)

    def test_a_future_stamp_reads_as_just_now_not_a_negative_age(self):
        """Runner clock skew shouldn't render "-1m ago" on the board."""
        self.assertEqual(lib.fmt_age("2026-08-04T12:00:30Z", now=self.NOW),
                         "just now")

    def test_unparseable_is_none_so_callers_can_omit_it(self):
        self.assertIsNone(lib.fmt_age("garbage", now=self.NOW))
        self.assertIsNone(lib.fmt_age("", now=self.NOW))
        self.assertIsNone(lib.fmt_age(None, now=self.NOW))


class ARepoDeclaresItsOwnTrunks(unittest.TestCase):
    """Two projects on one board do not share a trunk set.

    MWServer's CI moved to the Forgejo mirror, which builds dev alone, while
    Phoenix builds dev and main. Under one global list every project is assumed
    to have every branch, and a project that does not gets a tile nothing will
    ever write again — MWServer's `CI build · master`, frozen on a 2026-08-19
    GitHub verdict from a pipeline nobody runs.
    """

    def _runs(self, *branches):
        return [{"conclusion": "success", "headBranch": b, "headSha": f"{b}0000000",
                 "createdAt": "2026-09-01T10:00:00Z",
                 "url": f"https://github.com/o/r/actions/runs/{b}"}
                for b in branches]

    def test_a_quiet_trunk_is_fetched_when_the_window_misses_it(self):
        """MWServer's master last built on 2026-08-19, and a bot workflow has
        run on issue comments many times since, so master was nowhere in the
        repo's newest forty and its tile could not be written at all."""
        real = lib.gh_run_history
        try:
            asked = []

            def history(repo, limit=20, branch=None, **kw):
                asked.append(branch)
                return self._runs(branch) if branch == "master" else []

            lib.gh_run_history = history
            extra = ci_status._reach_quiet_trunks(
                "o/r", self._runs("dev"), ["dev", "master"])
            self.assertEqual(asked, ["master"], "asked about a trunk it had")
            self.assertEqual([r["headBranch"] for r in extra], ["master"])
        finally:
            lib.gh_run_history = real

    def test_a_branch_seen_only_as_skipped_runs_is_still_fetched(self):
        """What hid this. Master's bot runs are all skipped, they sit in the
        window in numbers, and counting any run at all made the branch look
        covered while it carried no verdict for the tile to read."""
        real = lib.gh_run_history
        try:
            asked = []
            lib.gh_run_history = lambda repo, limit=20, branch=None, **kw: (
                asked.append(branch) or self._runs(branch))
            window = [dict(r, conclusion="skipped")
                      for r in self._runs("master")]
            ci_status._reach_quiet_trunks("o/r", window, ["master"])
            self.assertEqual(asked, ["master"])
        finally:
            lib.gh_run_history = real

    def test_a_forge_source_is_never_asked_through_gh(self):
        # The repo path exists only on the forge, so the call could only fail.
        real = lib.gh_run_history
        try:
            lib.gh_run_history = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("asked GitHub about a forge repo"))
            self.assertEqual(
                ci_status._reach_quiet_trunks("jimmy/M", self._runs("dev"),
                                              ["dev", "master"],
                                              from_forge=True), [])
        finally:
            lib.gh_run_history = real

    def test_a_source_key_beats_the_label_key(self):
        """One project's trunks can come from two forges. MWServer builds dev
        on the mirror and master on GitHub, and both write into one column
        under one label, so a per-label answer cannot tell them apart."""
        cfg = {"ROOST_CI_TRUNKS_MWSERVER": "dev",
               "ROOST_CI_TRUNKS_AUSTIN_MACWORKS_MWSERVER": "master"}
        self.assertEqual(
            ci_status.parse_trunks(cfg, "MWServer", "Austin-MacWorks/MWServer"),
            ["master"])
        self.assertEqual(
            ci_status.parse_trunks(cfg, "MWServer", "jimmy/MWServer-Mirror"),
            ["dev"])

    def test_a_repo_name_becomes_a_shell_safe_key(self):
        self.assertEqual(ci_status.trunks_key("jimmy/MWServer-Mirror"),
                         "ROOST_CI_TRUNKS_JIMMY_MWSERVER_MIRROR")

    def test_two_sources_keep_two_tiles_rather_than_renaming_one(self):
        """The collision. `upsert_compare_tile` matches by PREFIX, so the first
        trunk's old `CI build` match also matched `CI build · dev`. With one
        source that was invisible — it found its own tile. With two, MWServer's
        dev from the mirror and its master from GitHub took turns renaming a
        single tile, and the column held one verdict that changed identity on
        every push."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", self._runs("master"), ["master"],
                              column_trunks=["dev", "master"])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"],
                              column_trunks=["dev", "master"])
        labels = sorted(t["label"] for t in columns(board)[0]["items"])
        self.assertEqual(labels, ["CI build · dev", "CI build · master"])

    def test_a_legacy_bare_tile_is_renamed_by_exact_name(self):
        board = board_with([{"label": "CI build", "n": "✓", "tone": "go"}])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"])
        self.assertEqual([t["label"] for t in columns(board)[0]["items"]],
                         ["CI build · dev"])

    def test_the_migration_never_touches_an_already_named_tile(self):
        board = board_with([{"label": "CI build · master", "n": "✓"}])
        self.assertFalse(ci_status._migrate_bare_tile(board, "Phoenix", "dev"))
        self.assertEqual([t["label"] for t in columns(board)[0]["items"]],
                         ["CI build · master"])

    def test_one_source_does_not_retire_the_other_sources_tile(self):
        """The two-forge column. Retiring against a source's own trunks would
        have each delete the other's tile, and the column would flip between
        them by whichever collector ran last."""
        board = board_with([
            {"label": "CI build · dev", "n": "✓", "tone": "go"},
            {"label": "CI build · master", "n": "✓", "tone": "go"},
        ])
        # The forge source: dev only, but the column carries both.
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"],
                              column_trunks=["dev", "master"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertIn("CI build · master", labels)
        self.assertIn("CI build · dev", labels)

    def test_a_branch_no_source_claims_is_still_retired(self):
        board = board_with([
            {"label": "CI build · dev", "n": "✓"},
            {"label": "CI build · gone", "n": "✓"},
        ])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"],
                              column_trunks=["dev", "master"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertNotIn("CI build · gone", labels)

    def test_a_repo_key_overrides_the_global_list(self):
        cfg = {"ROOST_CI_TRUNKS": "dev,main,master",
               "ROOST_CI_TRUNKS_MWSERVER": "dev"}
        self.assertEqual(ci_status.parse_trunks(cfg, "MWServer"), ["dev"])
        self.assertEqual(ci_status.parse_trunks(cfg, "Phoenix"),
                         ["dev", "main", "master"])

    def test_a_label_with_punctuation_still_names_a_key(self):
        # ~/.roostrc is a shell-style file; a key has to be shell-safe.
        self.assertEqual(ci_status.trunks_key("MWServer-Models"),
                         "ROOST_CI_TRUNKS_MWSERVER_MODELS")

    def test_no_repo_key_falls_back_to_the_global_list(self):
        cfg = {"ROOST_CI_TRUNKS": "dev,main"}
        self.assertEqual(ci_status.parse_trunks(cfg, "MWServer"), ["dev", "main"])

    def test_no_config_at_all_keeps_the_default(self):
        self.assertEqual(ci_status.parse_trunks({}, "MWServer"),
                         list(ci_status.TRUNKS_DEFAULT))

    def test_a_tile_for_an_undeclared_branch_is_retired(self):
        """The case. Nothing writes it any more, so no later run corrects it,
        and it states a stale ✓ beside the live one in the same type."""
        board = board_with([
            {"label": "CI build · dev", "n": "✓", "tone": "go"},
            {"label": "CI build · master", "n": "✓", "tone": "go",
             "meta": "b9357e3"},
        ])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertNotIn("CI build · master", labels)
        self.assertIn("CI build · dev", labels)

    def test_a_declared_trunk_missing_from_the_window_is_kept(self):
        """The reason this is driven by config and never by absence. The window
        is the last runs per repo, so a busy dev can push a quiet main out of
        it, and retiring on absence would delete a healthy tile on a slow day."""
        board = board_with([
            {"label": "CI build · dev", "n": "✓", "tone": "go"},
            {"label": "CI build · main", "n": "✓", "tone": "go", "meta": "aaa1111"},
        ])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev", "main"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertIn("CI build · main", labels)

    def test_the_unsuffixed_tile_is_renamed_not_retired(self):
        """It belongs to the primary trunk, whichever branch that currently is.
        Retiring it would delete the tile this pass is about to write, and the
        upsert renames it in place instead — one tile before, one after."""
        board = board_with([{"label": "CI build", "n": "✓", "tone": "go"}])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertEqual(labels, ["CI build · dev"])

    def test_an_empty_window_retires_nothing(self):
        """Absent data leaves the board alone — the collector's standing
        contract. A gh outage must not strip a column of its tiles."""
        board = board_with([
            {"label": "CI build · master", "n": "✓", "tone": "go"}])
        ci_status.apply_tiles(board, "Phoenix", [], ["dev"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertIn("CI build · master", labels)

    def test_other_tiles_in_the_column_are_untouched(self):
        board = board_with([
            {"label": "CI build · master", "n": "✓"},
            {"label": "Build time", "n": "36m32s"},
            {"label": "Tests green", "n": "9/9"},
        ])
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"])
        labels = [t["label"] for t in columns(board)[0]["items"]]
        self.assertIn("Build time", labels)
        self.assertIn("Tests green", labels)

    def test_it_writes_only_to_its_own_column(self):
        board = board_with([])
        columns(board)[1]["items"] = [{"label": "CI build · master", "n": "✓"}]
        ci_status.apply_tiles(board, "Phoenix", self._runs("dev"), ["dev"])
        self.assertEqual([t["label"] for t in columns(board)[1]["items"]],
                         ["CI build · master"])


class TheBadgeSaysWhereItWasMeasured(unittest.TestCase):
    """A ✓ that does not say where it came from asserts more than it knows.

    MWServer is the case. Its dev is green on the Forgejo instance today and
    its master is green on GitHub from a fortnight ago, and the two tiles sit
    side by side in one column. Unmarked they read as one project's two
    branches rather than as two pipelines, one of which nobody runs.
    """

    FORGE = [{"conclusion": "success", "headSha": "d66a1177e07",
              "createdAt": "2026-09-01T16:38:09Z",
              "url": "https://forgejo.jimmyhoughjr.net/jimmy/"
                     "MWServer-Mirror/actions/runs/4"}]
    HUB = [{"conclusion": "success", "headSha": "b9357e3aaaa",
            "createdAt": "2026-08-19T20:54:47Z",
            "url": "https://github.com/o/r/actions/runs/1"}]

    def test_a_forge_verdict_says_the_forge(self):
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", self.FORGE, [])
        self.assertEqual(tile(board, "CI build")["where"], "on forgejo")

    def test_a_github_verdict_says_github(self):
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", self.HUB, [])
        self.assertEqual(tile(board, "CI build")["where"], "on github")

    def test_a_verdict_with_no_url_claims_no_place(self):
        # Absent beats guessed. A place the collector could not read must not
        # be filled in with the likely one.
        board = board_with([])
        run = dict(self.FORGE[0])
        del run["url"]
        ci_status.apply_tiles(board, "Phoenix", [run], [])
        self.assertNotIn("where", tile(board, "CI build"))

    def test_a_trunk_that_moves_forge_does_not_keep_the_old_place(self):
        """The clearing case, and the reason `where` goes through the same
        None-clears path as the rest. A tile that kept the place from the run
        before would name the forge it used to be measured on beside a verdict
        from the new one."""
        board = board_with([])
        ci_status.apply_tiles(board, "Phoenix", self.HUB, [])
        self.assertEqual(tile(board, "CI build")["where"], "on github")
        ci_status.apply_tiles(board, "Phoenix", self.FORGE, [])
        self.assertEqual(tile(board, "CI build")["where"], "on forgejo")


if __name__ == "__main__":
    unittest.main()
