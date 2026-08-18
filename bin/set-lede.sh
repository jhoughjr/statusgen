#!/usr/bin/env bash
# set-lede.sh — rewrite the hand-written lede of a board banner, and publish it.
#
# A banner has two halves. Everything below the shipped marker is rewritten by
# narrative.py on every refresh. Everything above it is prose that no collector
# touches, so it stays as it is until a person changes it.
#
# The order of the steps here is the whole point. `roost status` pulls the
# published board before it regenerates, so a lede that is edited first and
# refreshed second is quietly replaced by the copy that was already published.
# This pulls first, edits second, and pushes the edit on its own, which is the
# order that survives.
#
# Usage:
#   set-lede.sh <site-dir> <slug> < lede.txt
#   echo "2026-08-18 - what shipped ..." | set-lede.sh ~/status-site clauffice
#
# Environment:
#   DEPLOY_REMOTE  git remote that deploys the site (default: dokku)
set -euo pipefail

SITE="${1:-}"
SLUG="${2:-}"
REMOTE="${DEPLOY_REMOTE:-dokku}"
MARKER="── shipped"

if [ -z "$SITE" ] || [ -z "$SLUG" ]; then
  echo "usage: $(basename "$0") <site-dir> <slug> < lede.txt" >&2
  exit 2
fi

BOARD="$SITE/$SLUG/board.json"
[ -f "$BOARD" ] || { echo "no board at $BOARD" >&2; exit 2; }

LEDE="$(cat)"
[ -n "$LEDE" ] || { echo "the lede is empty, so nothing was changed" >&2; exit 2; }

# The rule the schema enforces, checked here so the message names the real problem.
python3 - "$LEDE" <<'PY'
import re, sys
lede = sys.argv[1].strip()
sentences = len([s for s in re.split(r'(?<=[.!?])\s+', lede) if s])
if len(lede) > 700:
    sys.exit(f"the lede is {len(lede)} characters, and the limit is 700")
if sentences > 5:
    sys.exit(f"the lede is {sentences} sentences, and the limit is 5")
print(f"lede: {len(lede)} characters, {sentences} sentences")
PY

# The published board comes first, or the edit below lands on a stale copy.
git -C "$SITE" pull --ff-only "$REMOTE" main

python3 - "$BOARD" "$LEDE" "$MARKER" <<'PY'
import json, pathlib, sys
board, lede, marker = pathlib.Path(sys.argv[1]), sys.argv[2].strip(), sys.argv[3]
doc = json.loads(board.read_text())
for section in doc.get("sections", []):
    text = section.get("text")
    if isinstance(text, str) and marker in text:
        section["text"] = lede + "\n\n" + text[text.find(marker):]
        board.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        print("lede replaced")
        break
else:
    sys.exit("no banner carries the shipped marker, so nothing was changed")
PY

# The gate the board has to pass before anybody sees it.
python3 "$(dirname "$0")/validate-board.py" "$BOARD"

git -C "$SITE" add "$SLUG/board.json"
git -C "$SITE" commit -q -m "status: the banner lede catches up"
git -C "$SITE" push "$REMOTE" main
echo "✓ lede published"
