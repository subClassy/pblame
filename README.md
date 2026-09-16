# pblame — git blame, for the prompt

`git blame` tells you who committed a line. `pblame` tells you **which prompt produced it**.

It records every Claude Code prompt you run in a repo, works out which lines each one
produced, and attaches that record to whatever commit you make — as ordinary `git notes`,
inside your repo, no server. Then:

```
$ pblame blame src/auth.py

src/auth.py  41/48 lines from 3 prompt(s)

  ▎ Add a login endpoint that checks the password hash and returns a session token.
  ▎ claude-opus-5 - 3f2a9c1 - 2026-09-12 14:03
  ▎ 12 │ def login(username, password):
  ▎ 13 │     user = db.find(username)
  ...
  ▎ make it safer
  ▎ claude-opus-5 - 3f2a9c1 - 2026-09-12 14:11
  ▎ 19 │     if not user or not verify(password, user.hash):
  ▎ 20 │         time.sleep(0.5)
```

Early preview. It works, it has been stress-tested on real sessions, and it will
still surprise you sometimes. Please tell me what you see.

## Install

Requires **Python 3.10+**, **git 2.31+**, and **Claude Code** (terminal or VS Code — same
hooks either way).

The easiest route is [pipx](https://pipx.pypa.io/), which installs `pblame` on your PATH
in its own environment:

```
pipx install ./pblame-0.1.0-py3-none-any.whl
```

Or into any Python environment you like:

```
pip install ./pblame-0.1.0-py3-none-any.whl
```

Then, **in each repo you want recorded**:

```
cd your-project
pblame init .
pblame doctor          # must say "Recording is live"
```

`init` writes two Claude Code hooks into `.claude/settings.local.json` (the personal,
gitignored settings file) and two git hooks (`post-commit`, `post-rewrite`). Existing
hooks and settings are preserved, not replaced. **Open a fresh Claude Code session after
`init`** — hooks load when a session starts.

## Use

Just work. Prompt Claude Code as normal, commit when you like.

| | |
|---|---|
| `pblame blame <file>` | the file, annotated with the prompt behind each line (`--json` for machines) |
| `pblame show [commit]` | every prompt recorded on a commit, with the files and line ranges it produced |
| `pblame doctor` | is this repo actually recording right now? Run it if anything feels off |
| `pblame uninstall` | remove the hooks; recorded history is kept (`--purge` deletes that too) |

## What gets recorded, and where

For each prompt: the prompt text, the model, a timestamp, the session id, and the files
and line ranges the turn changed. Nothing else — no tool calls, no responses, no tokens.

Everything stays in your repo:

- `.git/pblame/staging.json` — prompts since your last commit
- `.git/pblame/hook.log` — errors, if a hook ever fails (should stay empty)
- `refs/notes/pblame` — the permanent record, one note per commit

**Prompts can contain things you'd rather not publish.** Notes are *not* pushed by
default; `git push` leaves them behind. If you ever want them on the remote it's an
explicit `git push origin refs/notes/pblame`. Until then, nothing leaves your machine.

## How it works, briefly

`UserPromptSubmit` snapshots the working tree; `Stop` snapshots it again. The diff between
the two is exactly that turn's work, so edits you make by hand between prompts stay
unattributed — they're yours, not the model's. At commit time the pending prompts attach
to the commit as a note. `pblame blame` then joins `git blame` (which already follows
lines across later commits, renames included) against those notes.

## Known limits

- **One Claude Code session per repo at a time.** Two at once won't lose data, but their
  turns overlap in the snapshots and lines get attributed to the wrong prompt.
- **A prompt that changes no file leaves no record** (questions, "it already does that").
- Amend and rebase are handled (`post-rewrite`). Content that moves *between files*, or a
  whole-file reformat, will still lose attribution.
- Each prompt costs one `git add -A` into a temporary index. On a very large working tree
  that's a noticeable pause per turn; `pblame doctor` runs the same operation, so its
  speed tells you what to expect.
- Git worktrees and submodules (where `.git` is a file) aren't handled yet.
- Text files only.

## Removing it

```
pblame uninstall .           # stops recording, keeps the history
pblame uninstall . --purge   # stops recording and deletes the history
```

Both leave any hooks and settings of your own exactly as they were.
