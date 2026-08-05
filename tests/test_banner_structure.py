#!/usr/bin/env python3
"""The banner wall guard.

A `banner` renders as one flat <div> — no headings, no rows, no pills. Every
other kind gives a reader somewhere to land, so the banner is the only one that
can quietly grow into a wall nobody reads. `narrative.py` preserves the prose
above the `── shipped ·` marker verbatim by design, which means nothing in the
pipeline ever pushed back on its length. This is that push-back.

Warnings only — a board must always be able to deploy.

Run:  python3 tests/test_banner_structure.py      (from the statusgen root)
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("vb", ROOT / "bin" / "validate-board.py")
vb = importlib.util.module_from_spec(spec)
sys.argv = ["validate-board.py"]           # no paths → the module's loop is a no-op
# validate-board.py is a script, not a library: it ends in sys.exit(fail). Left
# uncaught that unwinds this file during import and the run reports green having
# asserted nothing — so swallow the exit, then insist it was the clean one.
try:
    spec.loader.exec_module(vb)
    _exit_code = 0
except SystemExit as e:
    _exit_code = e.code or 0
assert _exit_code == 0, f"validate-board.py exited {_exit_code} on an empty argv"

failures = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        failures.append(name)


LEDE = ("2026-08-04 — the merge drought broke: eleven PRs landed on dev, and main is "
        "still fourteen days back at f7aaabb. The day's work was a CRUD audit.")

print("banner_warnings")
check("a lede passes clean", vb.banner_warnings(LEDE) == [])
check("empty text is not a complaint", vb.banner_warnings("") == [])
check("None is not a complaint", vb.banner_warnings(None) == [])

wall = "This sentence is here to take up room. " * 40
w = vb.banner_warnings(wall)
check("a wall warns about length", any("chars" in x for x in w))
check("a wall warns about sentences", any("sentences" in x for x in w))
check("a wall warns about the missing paragraph break", any("paragraph break" in x for x in w))

paragraphed = "\n\n".join(["This sentence is here to take up room. " * 20] * 2)
check("paragraphs silence the paragraph warning",
      not any("paragraph break" in x for x in vb.banner_warnings(paragraphed)))

print("\nthe shipped block is not the author's prose")
# narrative.py regenerates everything below the marker every run; it is
# line-broken already and must never count against the hand-written budget.
shipped = "\n".join(f"08-04 09:0{i} · #{200+i} · a merged pull request title" for i in range(10))
with_block = LEDE + "\n" + vb.BANNER_MARKER + " auto-refreshed · times CDT ──\n" + shipped
check("the marker block is excluded from the prose", vb.banner_prose(with_block) == LEDE)
check("a lede plus a long shipped block still passes", vb.banner_warnings(with_block) == [])

print("\nthe real board is the case this exists for")
live = pathlib.Path.home() / "status-site" / "clauffice" / "board.json"
if live.exists():
    import json
    board = json.load(open(live))
    banners = [s for s in board.get("sections", []) if s.get("kind") == "banner"]
    check("the live board has a banner to judge", len(banners) >= 1)
else:
    print("  skip  live board not present on this machine")

print()
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("all banner-structure tests passed")
