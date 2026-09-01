#!/usr/bin/env python3
"""Unit tests for the Forgejo → GitHub run mapping in lib.

Forgejo reports one `status` field where GitHub reports `status` and
`conclusion`, and its field names are not the GitHub ones in snake case. These
assert the mapping, and assert that the result actually survives the settled
filter in ci_status, which is where a wrong pending word does its damage.

No network: every case is a literal payload.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import ci_status
import lib


def run(status, **kw):
    """A Forgejo run payload, in the instance's own field names."""
    base = {
        "id": 41,
        "status": status,
        "prettyref": "refs/heads/dev",
        "commit_sha": "d77390b3d0000000000000000000000000000000",
        "event": "push",
        "created": "2026-08-31T15:00:00Z",
        "started": "2026-08-31T15:00:05Z",
        "updated": "2026-08-31T15:20:00Z",
        "stopped": "0001-01-01T00:00:00Z",
        "html_url": "/jimmy/MWServer/actions/runs/41",
        "workflow_id": "build.yml",
        "title": "ci: a change",
    }
    base.update(kw)
    return base


class VerdictTest(unittest.TestCase):
    def test_terminal_words_split_into_status_and_conclusion(self):
        for word in ("success", "failure", "cancelled", "skipped"):
            with self.subTest(word=word):
                self.assertEqual(lib.forgejo_verdict(run(word)),
                                 ("completed", word))

    def test_running_becomes_in_progress_with_no_conclusion(self):
        self.assertEqual(lib.forgejo_verdict(run("running")),
                         ("in_progress", None))

    def test_other_pending_words_become_queued(self):
        for word in ("waiting", "blocked", "unknown"):
            with self.subTest(word=word):
                self.assertEqual(lib.forgejo_verdict(run(word)),
                                 ("queued", None))

    def test_an_unknown_word_that_has_stopped_is_settled_not_hidden(self):
        # The terminal vocabulary came from one instance. A word this code does
        # not know must not be filed as pending, because the tile would then
        # inherit the previous verdict and hide a real failure.
        status, conclusion = lib.forgejo_verdict(
            run("timed_out", stopped="2026-08-31T15:20:00Z"))
        self.assertEqual(status, "completed")
        self.assertEqual(conclusion, "timed_out")
        self.assertNotEqual(conclusion, "success")

    def test_an_unknown_word_still_running_stays_pending(self):
        # The zero time is how Forgejo writes an unset timestamp, and reading it
        # as a real stop time would settle every queued run.
        self.assertEqual(lib.forgejo_verdict(run("provisioning")),
                         ("queued", None))

    def test_a_running_run_stays_in_flight_on_the_epoch_sentinel(self):
        # The regression. The fixture above carries the year-zero sentinel from
        # the swagger, and the live instance answers the Unix epoch instead. The
        # board read `latest MWServer - dev = running` off a build that was six
        # minutes into compiling, because the epoch parsed as a real stop time.
        self.assertEqual(
            lib.forgejo_verdict(run("running", stopped="1970-01-01T00:00:00Z")),
            ("in_progress", None))

    def test_every_pending_word_outranks_a_stop_time(self):
        # A word that means "not over" wins wherever the clock disagrees, so a
        # sentinel spelled a way this code does not list cannot settle a run
        # that Forgejo itself reports as unfinished.
        for word, expected in (("running", "in_progress"),
                               ("waiting", "queued"),
                               ("blocked", "queued"),
                               ("unknown", "queued")):
            for sentinel in ("1970-01-01T00:00:00Z", "0001-01-01T00:00:00Z",
                             "2026-08-31T15:20:00Z"):
                with self.subTest(word=word, stopped=sentinel):
                    self.assertEqual(
                        lib.forgejo_verdict(run(word, stopped=sentinel)),
                        (expected, None))

    def test_an_unknown_word_on_the_epoch_sentinel_stays_pending(self):
        # The clock still decides for words the vocabulary does not know, so the
        # epoch has to read as unset there too.
        self.assertEqual(
            lib.forgejo_verdict(
                run("provisioning", stopped="1970-01-01T00:00:00Z")),
            ("queued", None))


class FieldMapTest(unittest.TestCase):
    def test_the_fields_map_onto_the_gh_run_list_shape(self):
        got = lib.forgejo_run_to_gh(run("success"),
                                    base_url="https://forge.example")
        self.assertEqual(got["headBranch"], "dev")
        self.assertEqual(got["headSha"],
                         "d77390b3d0000000000000000000000000000000")
        self.assertEqual(got["createdAt"], "2026-08-31T15:00:00Z")
        self.assertEqual(got["startedAt"], "2026-08-31T15:00:05Z")
        self.assertEqual(got["updatedAt"], "2026-08-31T15:20:00Z")
        self.assertEqual(got["databaseId"], 41)
        self.assertEqual(got["workflowName"], "build.yml")
        self.assertEqual(got["displayTitle"], "ci: a change")
        self.assertEqual(got["event"], "push")

    def test_a_relative_url_is_made_absolute(self):
        got = lib.forgejo_run_to_gh(run("success"),
                                    base_url="https://forge.example/")
        self.assertEqual(got["url"],
                         "https://forge.example/jimmy/MWServer/actions/runs/41")

    def test_an_absolute_url_is_left_alone(self):
        got = lib.forgejo_run_to_gh(
            run("success", html_url="https://forge.example/a/b/actions/runs/9"),
            base_url="https://forge.example")
        self.assertEqual(got["url"], "https://forge.example/a/b/actions/runs/9")

    def test_a_tag_ref_loses_its_prefix_too(self):
        got = lib.forgejo_run_to_gh(run("success", prettyref="refs/tags/v1.2"))
        self.assertEqual(got["headBranch"], "v1.2")

    def test_a_missing_field_does_not_raise(self):
        got = lib.forgejo_run_to_gh({"status": "success"})
        self.assertEqual(got["headBranch"], "")
        self.assertEqual(got["headSha"], "")
        self.assertIsNone(got["databaseId"])


class SettledFilterTest(unittest.TestCase):
    """The mapping has to satisfy the consumer, not merely look right.

    `ci_status.settled_pools` filters on `conclusion or status` against
    `lib.CONSOLE_SKIP`, which holds GitHub's vocabulary. Forgejo's `running`
    and `blocked` are absent from that set, so passing them through unmapped
    would let a build still in flight set the board's badge.
    """

    def _pools(self, *runs):
        mapped = [lib.forgejo_run_to_gh(r) for r in runs]
        return ci_status.settled_pools(mapped, ("dev",))

    def test_a_running_run_is_not_evidence(self):
        self.assertEqual(self._pools(run("running")), [])

    def test_a_running_run_on_the_epoch_sentinel_is_not_evidence(self):
        # The same case at the consumer, where the damage actually lands. The
        # verdict test above proves the mapping, and this proves the filter
        # still drops it, which is what keeps an in-flight build off the badge.
        self.assertEqual(
            self._pools(run("running", stopped="1970-01-01T00:00:00Z")), [])

    def test_a_blocked_run_is_not_evidence(self):
        self.assertEqual(self._pools(run("blocked")), [])

    def test_a_successful_run_is_evidence(self):
        pools = self._pools(run("success"))
        self.assertEqual(len(pools), 1)
        branch, entries = pools[0]
        self.assertEqual(branch, "dev")
        self.assertEqual(entries[0]["conclusion"], "success")

    def test_a_failed_run_is_evidence(self):
        pools = self._pools(run("failure"))
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0][1][0]["conclusion"], "failure")

    def test_raw_forgejo_words_would_have_slipped_through(self):
        # The regression this mapping exists to prevent. Unmapped, `running`
        # is not in CONSOLE_SKIP, so the filter keeps it.
        raw = [{"status": "running", "headBranch": "dev", "conclusion": None}]
        self.assertNotEqual(ci_status.settled_pools(raw, ("dev",)), [])


class FetchTest(unittest.TestCase):
    def test_missing_configuration_returns_none_rather_than_raising(self):
        self.assertIsNone(lib.forgejo_runs("", "t", "o/r", 5))
        self.assertIsNone(lib.forgejo_runs("https://forge.example", "", "o/r", 5))
        self.assertIsNone(lib.forgejo_runs("https://forge.example", "t", "", 5))


if __name__ == "__main__":
    unittest.main()
