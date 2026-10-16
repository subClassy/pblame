#!/usr/bin/env bash
# Build the demo subject: a small real project, written by real Claude Code,
# recorded by real pblame hooks. Nothing here forges a receipt.
#
# The prompt the hero video films is NOT run here — it is typed live in
# hero.tape, so the camera sees the cause before the effect.
#
#   bash tools/demo/build_envdiff.sh
#
# Costs: seven Claude Code prompts on whoever's account runs it.
set -euo pipefail

REPO=/c/demo/envdiff                 # no username anywhere in this path
PB="$(cd "$(dirname "$0")/../.." && pwd)/.venv/Scripts/pblame.exe"
MODEL=claude-sonnet-5

# A Claude Code session started from inside another one inherits markers that
# switch transcript saving off, and without a transcript the Stop hook records
# the model as "unknown". Strip them: this must behave like a fresh terminal.
for v in $(env | grep -oE '^(CLAUDE[A-Z_]*|ANTHROPIC[A-Z_]*)=' | tr -d '='); do unset "$v"; done

ask() {
  echo "  > $1"
  claude -p "$1" --model "$MODEL" --permission-mode acceptEdits > /dev/null
}

commit() {
  git add -A
  git commit -q -m "$1"
  echo "  committed: $1"
}

rm -rf "$REPO"
mkdir -p "$REPO"
cd "$REPO"
git init -q -b main
# A neutral identity: this repo is a public demo, not anyone's history.
git config user.name "demo"
git config user.email "demo@example.com"
# On camera, git's "LF will be replaced by CRLF" warning is noise.
git config core.autocrlf false
printf '# envdiff\n\nCompare two .env files.\n' > README.md
# Claude runs the script while it works; keep the bytecode out of the record.
printf '__pycache__/\n' > .gitignore
git add -A && git commit -q -m "initial commit"
"$PB" init . > /dev/null

echo "== the core"
ask "Write envdiff.py: a command-line tool that takes two .env file paths and prints three sections - keys only in the first file, keys only in the second, and keys whose values differ. Python standard library only, with argparse and a main()."
ask "Move the .env parsing into envfile.py as load_env(path) -> dict[str, str]. Skip blank lines and # comments, accept an optional leading 'export ', and strip matching single or double quotes around values."
ask "make the output nicer"
commit "envdiff: compare two .env files"

echo "== redaction"
ask "In the report never print a value. For a changed key print only the key name and the lengths of the old and new values. Missing or extra keys print the key name alone. Add a --show-values flag that opts back in and prints a warning to stderr when used."
ask "For context, my staging .env has lines like DATABASE_PASSWORD=hunter2correct and AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE - do not put any of that in the code. Make --show-values refuse to print the value of any key whose name contains PASSWORD, SECRET, TOKEN or KEY."
commit "envdiff: never print values by default"

echo "== done; the hero prompt is typed live by hero.tape"
"$PB" doctor | tail -2
