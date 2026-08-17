#!/usr/bin/env python3
"""Unit tests for collect/swift_tests.py — the test-INVENTORY tile for a repo
whose suite does not run in CI.

Builds a throwaway git repo with a real `Tests/` tree and counts from it, so
the ref plumbing (fetch → origin/<branch> → ls-tree → show) is exercised rather
than mocked. The declaration regex is tested against the shapes that actually
appear in Swift: swift-testing's `@Test`, parameterized `@Test(...)`, XCTest's
`func testFoo()`, and the near-misses that must NOT count.

Run:  python3 -m unittest discover -s tests   (from the statusgen root)
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin", "collect"))

import lib
import swift_tests


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def make_repo(files, branch="dev"):
    """A repo whose `origin/<branch>` really resolves: commit on a branch, then
    clone it so the clone has a genuine remote-tracking ref."""
    src = tempfile.mkdtemp()
    git(src, "init", "-q", "-b", branch)
    git(src, "config", "user.email", "t@example.test")
    git(src, "config", "user.name", "t")
    for path, body in files.items():
        full = os.path.join(src, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(body)
    git(src, "add", "-A")
    git(src, "commit", "-qm", "tests")

    clone = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", src, clone], check=True,
                   capture_output=True)
    return clone


def board():
    return {"sections": [{"kind": "compare", "columns": [
        {"title": "Phoenix — client",
         "items": [{"n": "6605", "label": "Tests green"}]},
        {"title": "MWServer — server",
         "items": [{"n": "332", "label": "Test files"}]},
    ]}]}


def tiles(b, col=1):
    return {t["label"]: t for t in b["sections"][0]["columns"][col]["items"]}


SOURCE = {"column": "MWServer", "branch": "dev", "tests_dir": "Tests"}

SWIFT_TESTING = """\
import Testing

@Suite struct OrderTests {
    @Test func createsAnOrder() async throws {}

    @Test("renames a line")
    func renamesALine() {}

    @Test(arguments: [1, 2, 3])
    func handlesQuantities(_ n: Int) {}
}
"""

XCTEST = """\
import XCTest

final class LegacyTests: XCTestCase {
    func testOne() {}
    private func testTwo() {}
    func helperNotATest() {}
    // func testCommentedOut() {}
}
"""


class DeclRegexTest(unittest.TestCase):
    def count(self, body):
        return len(swift_tests.DECL_RE.findall(swift_tests.strip_comments(body)))

    def test_counts_swift_testing_declarations(self):
        # Plain, named, and parameterized — three declarations.
        self.assertEqual(self.count(SWIFT_TESTING), 3)

    def test_counts_xctest_declarations(self):
        # testOne + testTwo. `helperNotATest` is not a test, and the
        # commented-out one is dead code.
        self.assertEqual(self.count(XCTEST), 2)

    def test_does_not_count_words_that_merely_contain_test(self):
        self.assertEqual(self.count("func attestation() {}\nlet contest = 1\n"), 0)

    def test_does_not_count_a_suite_or_a_test_type_reference(self):
        self.assertEqual(self.count("@Suite struct S {}\nlet x: TestKind = .a\n"), 0)

    def test_both_dialects_ignore_commented_out_tests(self):
        self.assertEqual(self.count("// @Test func gone() {}\n"), 0)
        self.assertEqual(self.count("  // func testGone() {}\n"), 0)
        self.assertEqual(self.count("/* @Test func gone() {}\n"
                                    "   func testAlsoGone() {} */\n"), 0)

    def test_an_indented_declaration_inside_a_suite_still_counts(self):
        self.assertEqual(self.count("struct S {\n    func testDeep() {}\n}\n"), 1)


class CountFromRefTest(unittest.TestCase):
    def test_counts_cases_and_files_at_the_ref(self):
        repo = make_repo({"Tests/AppTests/Order.swift": SWIFT_TESTING,
                          "Tests/AppTests/Legacy.swift": XCTEST,
                          "Sources/App/main.swift": "func testNotInTests() {}\n"})
        ref = swift_tests.resolve_ref(repo, "dev")
        self.assertEqual(ref, "origin/dev")
        # Sources/ is outside the test tree and must not be counted.
        self.assertEqual(swift_tests.count_tests(repo, ref, "Tests"), (5, 2))

    def test_non_swift_files_are_not_counted_as_test_files(self):
        repo = make_repo({"Tests/AppTests/Order.swift": SWIFT_TESTING,
                          "Tests/AppTests/fixture.json": "{}\n"})
        self.assertEqual(swift_tests.count_tests(repo, "origin/dev", "Tests"),
                         (3, 1))

    def test_missing_test_tree_is_none_not_zero(self):
        repo = make_repo({"Sources/App/main.swift": "let x = 1\n"})
        self.assertIsNone(swift_tests.count_tests(repo, "origin/dev", "Tests"))

    def test_unknown_ref_is_none(self):
        repo = make_repo({"Tests/A.swift": SWIFT_TESTING})
        self.assertIsNone(swift_tests.count_tests(repo, "origin/nope", "Tests"))

    def test_a_non_repo_resolves_to_nothing(self):
        self.assertIsNone(swift_tests.resolve_ref(tempfile.mkdtemp(), "dev"))


class ApplySourceTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo({"Tests/AppTests/Order.swift": SWIFT_TESTING,
                               "Tests/AppTests/Legacy.swift": XCTEST})
        self.source = dict(SOURCE, root=self.repo)

    def test_writes_an_inventory_tile_into_the_server_column(self):
        b = board()
        self.assertIsNotNone(swift_tests.apply_source(b, self.source))
        t = tiles(b)
        self.assertEqual(t["Tests written"]["n"], "5")
        self.assertEqual(t["Test files"]["n"], "2")

    # The whole point of this collector: the tile must never read as a test
    # RESULT. Nothing here ran a test, so nothing may claim one passed.
    def test_the_label_never_claims_a_passing_run(self):
        b = board()
        swift_tests.apply_source(b, self.source)
        labels = [t["label"] for t in b["sections"][0]["columns"][1]["items"]]
        self.assertIn("Tests written", labels)
        self.assertNotIn("Tests green", labels)
        for t in b["sections"][0]["columns"][1]["items"]:
            self.assertNotEqual(t.get("tone"), "go")

    def test_it_replaces_the_stale_count_rather_than_appending_beside_it(self):
        b = board()
        swift_tests.apply_source(b, self.source)
        files = [t for t in b["sections"][0]["columns"][1]["items"]
                 if t["label"] == "Test files"]
        self.assertEqual(len(files), 1)
        self.assertNotEqual(files[0]["n"], "332")

    def test_the_client_column_is_untouched(self):
        b = board()
        swift_tests.apply_source(b, self.source)
        self.assertEqual(tiles(b, 0)["Tests green"]["n"], "6605")

    def test_repeat_runs_do_not_accumulate_tiles(self):
        b = board()
        swift_tests.apply_source(b, self.source)
        swift_tests.apply_source(b, self.source)
        labels = [t["label"] for t in b["sections"][0]["columns"][1]["items"]]
        self.assertEqual(len(labels), len(set(labels)))

    def test_a_repo_that_is_not_on_this_machine_leaves_the_board_alone(self):
        b = board()
        self.assertIsNone(swift_tests.apply_source(
            b, dict(SOURCE, root="/nope/nowhere")))
        self.assertEqual(b, board())


class ParseSourcesTest(unittest.TestCase):
    def test_full_spec(self):
        got = swift_tests.parse_sources("/r/MWServer:MWServer:dev:Tests")
        self.assertEqual(got, [{"root": "/r/MWServer", "column": "MWServer",
                                "branch": "dev", "tests_dir": "Tests"}])

    def test_defaults_from_the_directory_name(self):
        got = swift_tests.parse_sources("/r/MWServer")[0]
        self.assertEqual((got["column"], got["branch"], got["tests_dir"]),
                         ("MWServer", swift_tests.DEFAULT_BRANCH,
                          swift_tests.DEFAULT_TESTS_DIR))

    def test_expands_a_home_relative_path(self):
        got = swift_tests.parse_sources("~/repos/MWServer:MWServer")[0]
        self.assertTrue(got["root"].startswith(os.path.expanduser("~")))
        self.assertNotIn("~", got["root"])

    def test_empty_spec(self):
        self.assertEqual(swift_tests.parse_sources(""), [])


class ShTimeoutTest(unittest.TestCase):
    # A fetch that hangs must come back as a failed command, not an exception
    # that takes the whole status push down with it.
    def test_timeout_is_a_nonzero_result_not_a_raise(self):
        r = lib.sh([sys.executable, "-c", "import time; time.sleep(5)"],
                   timeout=0.2)
        self.assertNotEqual(r.returncode, 0)

    def test_a_missing_binary_is_a_nonzero_result(self):
        self.assertNotEqual(lib.sh(["definitely-not-a-binary-xyz"]).returncode, 0)


if __name__ == "__main__":
    unittest.main()


class InventoryStandsDownTest(unittest.TestCase):
    """A repo whose gate reports a measured result keeps that number alone.

    `swift_test_report` writes "Tests green" from a run that passed, and this
    collector counts what the source tree declares. Both numbers answer "how
    many tests", so a column that shows both makes the reader pick one."""

    def setUp(self):
        self.repo = make_repo({"Tests/AppTests/Order.swift": SWIFT_TESTING,
                               "Tests/AppTests/Legacy.swift": XCTEST})
        self.source = dict(SOURCE, root=self.repo)

    def measured_board(self):
        b = board()
        b["sections"][0]["columns"][1]["items"].append(
            {"n": "618", "label": "Tests green", "tone": "go"})
        return b

    def test_no_inventory_tile_lands_beside_a_measured_one(self):
        b = self.measured_board()
        self.assertIsNotNone(swift_tests.apply_source(b, self.source))
        self.assertNotIn("Tests written", tiles(b))

    def test_the_file_count_still_lands(self):
        # Nothing else measures it, so it is the collector's whole remaining job.
        b = self.measured_board()
        swift_tests.apply_source(b, self.source)
        self.assertEqual(tiles(b)["Test files"]["n"], "2")

    def test_the_measured_tile_is_left_exactly_as_it_was(self):
        b = self.measured_board()
        swift_tests.apply_source(b, self.source)
        green = tiles(b)["Tests green"]
        self.assertEqual(green["n"], "618")
        self.assertEqual(green["tone"], "go")

    def test_a_board_that_already_carries_both_loses_the_inventory_tile(self):
        # The regression this guards: the duplicate reached the live board once
        # already. A run must correct it, not preserve it.
        b = self.measured_board()
        b["sections"][0]["columns"][1]["items"].append(
            {"n": "625", "label": "Tests written", "tone": "srv"})
        swift_tests.apply_source(b, self.source)
        labels = [t["label"] for t in b["sections"][0]["columns"][1]["items"]]
        self.assertNotIn("Tests written", labels)
        self.assertIn("Tests green", labels)

    def test_a_column_without_a_measured_tile_still_gets_the_inventory(self):
        b = board()
        swift_tests.apply_source(b, self.source)
        self.assertEqual(tiles(b)["Tests written"]["n"], "5")
