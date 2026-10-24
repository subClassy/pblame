#!/usr/bin/env bash
# History the three feature clips need, after the hero's prompt is committed.
#
#   rename   — so attribution has to survive a file changing its name
#   --json   — a feature commit...
#   prettier — ...and a vague follow-up committed as a fixup, so the squash
#              clip has a real squash to perform
#
# --permission-mode auto, not acceptEdits: a rename needs `git mv` or `rm`,
# and headless Claude cannot ask anyone to approve a shell command.
set -euo pipefail

REPO=/c/demo/envdiff
MODEL=claude-sonnet-5
for v in $(env | grep -oE '^(CLAUDE[A-Z_]*|ANTHROPIC[A-Z_]*)=' | tr -d '='); do unset "$v"; done

ask() {
  echo "  > $1"
  claude -p "$1" --model "$MODEL" --permission-mode auto > /dev/null
}

cd "$REPO"

ask "Rename envfile.py to dotenv_loader.py and update the import in envdiff.py."
git add -A && git commit -q -m "rename envfile to dotenv_loader"

ask "Add a --json flag that prints the same report as machine-readable JSON instead of text."
git add -A && git commit -q -m "envdiff: --json output"

ask "make the json output prettier"
git add -A && git commit -q --fixup HEAD

git log --oneline -5
