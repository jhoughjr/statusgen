#!/usr/bin/env bash
# git-stats.sh — emit quantitative stats for a git repo as JSON.
#
# Building block: a per-project collector script calls this, then merges
# the numbers into the right `stats` tiles / `barchart` series of a
# board.json (see BOARD_SCHEMA.md's "Collectible fields" section).
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") <repo-path>

Print a JSON object of quantitative stats for a repo:

  { "commits_7d": N, "loc": N, "test_files": N, "tests_dir_loc": N }

  commits_7d      commits reachable from HEAD in the last 7 days
                  (0 if <repo-path> isn't a git repo)
  loc             lines of code, excluding .git, node_modules, generated
  test_files      count of *.test.* files, same exclusions
  tests_dir_loc   lines of code inside test/tests/__tests__/spec(s) dirs

Generic and defensive: missing directories yield 0s rather than errors.

Arguments:
  <repo-path>  Path to a repo (or any directory) to scan
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  echo "error: expected exactly 1 argument, got $#" >&2
  usage >&2
  exit 1
fi

repo="$1"

if [[ ! -d "$repo" ]]; then
  echo "error: not a directory: ${repo}" >&2
  exit 1
fi

# Shared prune clause: skip .git, node_modules, generated wherever they occur.
prune=(-name .git -o -name node_modules -o -name generated)

# --- commits_7d ---

commits_7d=0
if git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
  # A repo with a branch but zero commits yet makes `git log` fail fatally
  # (exit 128) rather than print nothing — guard it like the pipelines below
  # so an empty-but-initialized repo still yields 0, not a crash.
  commits_7d=$(git -C "$repo" log --since="7 days ago" --oneline 2>/dev/null | wc -l | tr -d ' ') || true
fi
commits_7d="${commits_7d:-0}"

# --- loc ---

loc=$(find "$repo" \( "${prune[@]}" \) -prune -o -type f -print0 2>/dev/null \
  | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ') || true
loc="${loc:-0}"

# --- test_files ---

test_files=$(find "$repo" \( "${prune[@]}" \) -prune -o -type f -name '*.test.*' -print 2>/dev/null \
  | wc -l | tr -d ' ') || true
test_files="${test_files:-0}"

# --- tests_dir_loc ---

tests_dir_loc=0
while IFS= read -r -d '' tdir; do
  n=$(find "$tdir" \( "${prune[@]}" \) -prune -o -type f -print0 2>/dev/null \
    | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ') || true
  n="${n:-0}"
  tests_dir_loc=$((tests_dir_loc + n))
done < <(find "$repo" \( "${prune[@]}" \) -prune -o -type d \
  \( -iname test -o -iname tests -o -iname __tests__ -o -iname spec -o -iname specs \) \
  -print0 2>/dev/null) || true

printf '{ "commits_7d": %d, "loc": %d, "test_files": %d, "tests_dir_loc": %d }\n' \
  "$commits_7d" "$loc" "$test_files" "$tests_dir_loc"
