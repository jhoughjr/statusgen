#!/usr/bin/env python3
"""The config sweep.

config.json is hand-authored and the renderer ignores a broken one outright, which is
the safe failure and also the silent one. The validator names what the renderer will
ignore — a typo'd key, a title no section carries, a value of the wrong type — and it
rides the existing deploy sweep by visiting each board's sibling config.json, so the
roost glob needs no change. Every finding is a warning: the gate must never freeze the
site over a settings file the renderer does not even require.

Run:  python3 tests/test_config_validation.py      (from the statusgen root)
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "bin" / "validate-board.py"
spec_loader = importlib.util.spec_from_file_location("vbc", VALIDATOR)
vbc = importlib.util.module_from_spec(spec_loader)
spec_loader.loader.exec_module(vbc)

BOARD = {"title": "t", "sections": [
    {"kind": "cards", "title": "Alpha", "items": [{"q": "a"}]},
    {"kind": "cards", "title": "Beta", "items": [{"q": "b"}]},
]}

# a clean config draws no findings
assert vbc.validate_config({"staleAfterMinutes": 60, "hide": ["Beta"], "order": ["Alpha"]}, BOARD) == []

# the typo catcher: a misspelled key is named, because the renderer drops it silently
assert any("staleAfterMins" in w for w in vbc.validate_config({"staleAfterMins": 60}, BOARD))

# a title no section carries is named, softly - its collector may not have seeded yet
warns = vbc.validate_config({"hide": ["Gamma"]}, BOARD)
assert any("Gamma" in w and "absent" in w for w in warns), warns

# wrong types are named, never raised
assert any("must be" in w for w in vbc.validate_config({"staleAfterMinutes": "soon"}, BOARD))
assert any("must be" in w for w in vbc.validate_config({"hide": [7]}, BOARD))
assert vbc.validate_config("not an object", BOARD)

# with no board at hand, title cross-checks stay quiet rather than guessing
assert vbc.validate_config({"hide": ["Gamma"]}, None) == []

# -- the sweep picks up a sibling config.json without being told about it -----

with tempfile.TemporaryDirectory() as td:
    d = pathlib.Path(td)
    (d / "board.json").write_text(json.dumps(BOARD))
    (d / "config.json").write_text(json.dumps({"hide": ["Gamma"]}))
    r = subprocess.run([sys.executable, str(VALIDATOR), str(d / "board.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "config.json" in r.stdout and "Gamma" in r.stdout, r.stdout

    # a config that does not parse warns and the gate still passes
    (d / "config.json").write_text("{not json")
    r = subprocess.run([sys.executable, str(VALIDATOR), str(d / "board.json")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "invalid JSON" in r.stdout, r.stdout

    # a broken BOARD still fails the gate exactly as before
    (d / "board.json").write_text(json.dumps({"sections": []}))
    r = subprocess.run([sys.executable, str(VALIDATOR), str(d / "board.json")],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout

print("ok - config validation")
