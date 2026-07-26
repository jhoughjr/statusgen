#!/usr/bin/env python3
"""swift_tests.py — how many tests a Swift repo *has*, counted from its source.

This is deliberately not a test *result*. It exists for a repo whose suite does
not run in CI: there is no report to read, so the only honest number is the
inventory — how many test cases are written — and the only honest label says so.

The distinction matters on a compare board. "6,605 tests green" is a claim that
something ran and passed; "367 tests written" is a claim about the source tree
and nothing more. Rendering the second as if it were the first is how a board
starts lying, so the two never share a label here.

Counted from `origin/<branch>` after a best-effort fetch, never from the
working tree: a status writer's checkout sits wherever someone last left it,
and a number counted from a stale or half-switched tree is worse than none.

Config (~/.roostrc):
  ROOST_SWIFT_TESTS_BOARD=clauffice
  ROOST_SWIFT_TESTS=/path/to/repo:Column:branch[:testsDir], …

  Column    substring of the compare column title this repo owns
  branch    branch to count (default dev)
  testsDir  test tree relative to the repo root (default Tests)

Non-fatal by contract: no config → skip; any failure → board untouched, exit 0.
"""
import os
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib

DEFAULT_BRANCH = "dev"
DEFAULT_TESTS_DIR = "Tests"
# A fetch against an unreachable remote must not wedge the push.
FETCH_TIMEOUT = 60

# swift-testing's `@Test` and XCTest's `func testFoo()`. Both dialects coexist
# in a migrating repo, so both are counted and reported as one number.
#
# `@Test\b` also matches `@Test(...)`, which is how a parameterized case is
# written — one declaration, several executed cases. So this counts *declared*
# cases and can under-count what a run reports. That is the conservative
# direction for an inventory number, and the label says "written", not "run".
DECL_RE = re.compile(r"(^|[^\w])@Test\b|^[ \t]*(public\s+|private\s+|internal\s+)?"
                     r"(final\s+)?func\s+test\w*\s*\(", re.MULTILINE)

# Comments are stripped before counting. Without this the two dialects
# disagree: a commented-out `func testFoo()` is already excluded (the `func`
# is no longer at the start of its line) while a commented-out `@Test` still
# matches — so a repo mid-migration would count its dead code inconsistently
# depending on which dialect it was dead in.
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def strip_comments(src):
    """Swift source minus its comments. Deliberately naive: a `//` inside a
    string literal is stripped too. That can only ever lose a match, and the
    strings that contain `//` are URLs, not test declarations."""
    return LINE_COMMENT_RE.sub("", BLOCK_COMMENT_RE.sub("", src))


def parse_sources(spec):
    """"dir:Column:branch[:testsDir], …" → list of dicts."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(":")]
        root = os.path.expanduser(bits[0])
        if not root:
            continue
        column = bits[1] if len(bits) > 1 and bits[1] else os.path.basename(root)
        branch = bits[2] if len(bits) > 2 and bits[2] else DEFAULT_BRANCH
        tests_dir = bits[3] if len(bits) > 3 and bits[3] else DEFAULT_TESTS_DIR
        out.append({"root": root, "column": column, "branch": branch,
                    "tests_dir": tests_dir})
    return out


def resolve_ref(root, branch):
    """`origin/<branch>` after a best-effort fetch, or None if it can't be
    resolved. A failed fetch is not fatal — an existing (if older) remote ref
    still beats the working tree, and the caller reports which sha it counted
    so a stale one is visible rather than silent."""
    if not os.path.isdir(os.path.join(root, ".git")):
        return None
    lib.sh(["git", "-C", root, "fetch", "--quiet", "origin", branch],
           timeout=FETCH_TIMEOUT)
    ref = f"origin/{branch}"
    r = lib.sh(["git", "-C", root, "rev-parse", "--verify", "--quiet", ref])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return ref


def count_tests(root, ref, tests_dir):
    """(cases, files) declared under `tests_dir` at `ref`, or None."""
    r = lib.sh(["git", "-C", root, "ls-tree", "-r", "--name-only", ref,
                "--", tests_dir])
    if r.returncode != 0:
        return None
    files = [f for f in r.stdout.splitlines() if f.endswith(".swift")]
    if not files:
        return None

    cases = 0
    for path in files:
        blob = lib.sh(["git", "-C", root, "show", f"{ref}:{path}"])
        if blob.returncode != 0:
            continue
        cases += len(DECL_RE.findall(strip_comments(blob.stdout)))
    return cases, len(files)


def apply_source(board, source):
    """Patch one repo's inventory tile into `board`; returns a log line."""
    ref = resolve_ref(source["root"], source["branch"])
    if ref is None:
        return None
    counted = count_tests(source["root"], ref, source["tests_dir"])
    if counted is None:
        return None
    cases, files = counted

    sha = lib.sh(["git", "-C", source["root"], "rev-parse", "--short",
                  ref]).stdout.strip()
    # "written", never "green": nothing here observed a test pass. Tone `srv`
    # is the board's neutral other-side colour — a count is not an outcome, so
    # it must not be able to read as one.
    lib.upsert_compare_tile(board, source["column"], "Tests written",
                            f"{cases:,}", tone="srv")
    lib.upsert_compare_tile(board, source["column"], "Test files",
                            f"{files:,}", tone="srv", match="Test files")
    return (f"{source['column']}: {cases:,} cases in {files:,} files "
            f"@{sha or ref}")


def main():
    cfg = lib.read_roostrc()
    spec = cfg.get("ROOST_SWIFT_TESTS", "")
    board_dir = cfg.get("ROOST_SWIFT_TESTS_BOARD", "")
    if not spec or not board_dir:
        print("swift-tests: ROOST_SWIFT_TESTS/ROOST_SWIFT_TESTS_BOARD not configured — skipping")
        return 0
    board_path = lib.site_dir(cfg) / board_dir / "board.json"
    if not board_path.exists():
        print(f"swift-tests: {board_path} not found — skipping")
        return 0

    sources = parse_sources(spec)
    if not sources:
        print("swift-tests: ROOST_SWIFT_TESTS parsed to nothing — skipping")
        return 0

    board = lib.load_board(board_path)
    reports = [msg for msg in (apply_source(board, s) for s in sources) if msg]
    if not reports:
        print("swift-tests: nothing counted (no clone, or no test tree) — leaving board as-is")
        return 0

    lib.save_board(board_path, board)
    for msg in reports:
        print(f"swift-tests: {msg}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a status push
        print(f"swift-tests: non-fatal error: {e}")
        sys.exit(0)
