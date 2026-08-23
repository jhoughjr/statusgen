#!/usr/bin/env python3
"""The widget-surface contract.

Four artifacts each claim to know what a board section looks like: the renderer, the validator,
the machine spec (bin/widgets.schema.json), and the prose catalog (BOARD_SCHEMA.md).
Before this test nothing held them together, and the bundled demo example had failed the validator
for an unknown span of time without anything noticing.
This file pins all four to the same surface.

Run:  python3 tests/test_widget_schema.py      (from the statusgen root)
"""
import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec_loader = importlib.util.spec_from_file_location("vbs", ROOT / "bin" / "validate-board.py")
vbs = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(vbs)

SCHEMA = json.load(open(ROOT / "bin" / "widgets.schema.json"))


def errors_of(board):
    errors, _, _ = vbs.validate_board(board)
    return errors


def warnings_of(board):
    _, warnings, _ = vbs.validate_board(board)
    return warnings


def board_with(section):
    return {"title": "t", "sections": [section]}


# -- the four surfaces agree on the kind list ---------------------------------

renderer_js = (ROOT / "renderer" / "board.js").read_text()
renderers_block = re.search(r"const RENDERERS = \{(.*?)\};", renderer_js, re.S).group(1)
renderer_kinds = set(re.findall(r'^\s*(?:"([^"]+)"|(\w+)):', renderers_block, re.M))
renderer_kinds = {a or b for a, b in renderer_kinds}
assert renderer_kinds == set(SCHEMA["kinds"]), \
    f"renderer and spec disagree: {renderer_kinds ^ set(SCHEMA['kinds'])}"
assert vbs.KINDS == set(SCHEMA["kinds"]), "validator KINDS must come from the spec"

# every spec field type names a real type tag
for scope in [SCHEMA["board"], SCHEMA["sectionCommon"], *SCHEMA["kinds"].values()]:
    stack = [scope["fields"]]
    while stack:
        fields = stack.pop()
        for name, fs in fields.items():
            assert fs["type"] in vbs.TYPES, f"{name}: unknown type tag {fs['type']!r}"
            assert fs.get("need", "soft") in ("hard", "soft"), f"{name}: bad need"
            if "item" in fs:
                stack.append(fs["item"]["fields"])

# -- every bundled example passes the gate ------------------------------------

for path in sorted((ROOT / "examples").glob("*.board.json")):
    board = json.load(open(path))
    errs = errors_of(board)
    assert not errs, f"{path.name}: {errs}"

# -- every ```json example in BOARD_SCHEMA.md is strict JSON and passes -------

doc = (ROOT / "BOARD_SCHEMA.md").read_text()
doc_blocks = re.findall(r"```json\n(.*?)```", doc, re.S)
assert len(doc_blocks) >= 10, "BOARD_SCHEMA.md lost its examples"
for i, block in enumerate(doc_blocks):
    parsed = json.loads(block)  # a doc example a reader cannot paste is a trap
    if "sections" in parsed:
        errs = errors_of(parsed)
    elif "kind" in parsed:
        errs = errors_of(board_with(parsed))
    elif set(parsed) & {"hide", "order", "staleAfterMinutes"}:
        errs = vbs.validate_config(parsed, None)
    else:
        continue
    assert not errs, f"BOARD_SCHEMA.md block {i}: {errs}"

# -- hard findings fail, new rules only warn ----------------------------------

assert errors_of({"sections": []}), "a board without a title must fail"
assert errors_of(board_with({"kind": "nope"})), "an unknown kind must fail"
assert errors_of(board_with({"kind": "console"})), "a console without lines must fail"
assert errors_of(board_with({"kind": "console", "lines": [{"tone": "go"}]})), \
    "a console line without text must fail"
assert errors_of(board_with({"kind": "cards", "items": [{"note": "no headline"}]})), \
    "a cards item without q must fail"
assert errors_of(board_with({"kind": "stats", "items": [{"label": "only a label"}]})), \
    "a stats item needs n or ts"
assert errors_of(board_with({"kind": "compare", "columns": []})), \
    "an empty compare must fail"
assert errors_of(board_with({"kind": "live-console", "poll": {}})), \
    "a live-console without poll.url must fail"
assert errors_of({"title": "t", "sections": [], "staleAfterDays": "7"}), \
    "a string staleAfterDays must fail"

# a rule the live boards never had stays a warning, so the deploy gate cannot freeze the site on it
for section in [
    {"kind": "banner"},
    {"kind": "barchart"},
    {"kind": "pie"},
    {"kind": "table"},
    {"kind": "stats"},
]:
    b = board_with(section)
    assert not errors_of(b), f"{section['kind']}: a missing data field must stay soft"
    assert warnings_of(b), f"{section['kind']}: a missing data field must at least warn"

# -- the typo catcher ---------------------------------------------------------

typo = board_with({"kind": "stats", "items": [{"n": "1", "label": "x"}], "collapsable": True})
assert not errors_of(typo), "an unknown field must not fail the gate"
assert any("collapsable" in w for w in warnings_of(typo)), \
    "a misspelled field must be named, because the renderer drops it silently"

board_typo = {"title": "t", "sections": [], "staleAfterMins": 60}
assert any("staleAfterMins" in w for w in warnings_of(board_typo)), \
    "a misspelled board key must be named"
assert not warnings_of({"title": "t", "sections": [], "staleAfterMinutes": 60}), \
    "the real staleAfterMinutes key is known"

# -- pill shape follows the renderer: text or pill carries the label ----------

for key in ("text", "pill"):
    ok = board_with({"kind": "cards", "items": [{"q": "x", "pill": {key: "go", "tone": "go"}}]})
    assert not errors_of(ok), f"a pill labeled via {key!r} is legal"
assert errors_of(board_with({"kind": "cards", "items": [{"q": "x", "pill": {"tone": "go"}}]})), \
    "a pill with no label must fail"

print("ok - widget schema surface")
