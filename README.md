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
| `pblame share` | opt in to sharing prompts with your team (`--off` to stop) |
| `pblame push` / `pull` | share, or fetch what teammates shared (`push --dry-run` to preview) |
| `pblame redact <file>` | see what redaction would do to some text, without recording |
| `pblame uninstall` | remove the hooks; recorded history is kept (`--purge` deletes that too) |

## Sharing with a team

Off by default. Nothing leaves your machine until you say so:

```
pblame share                 # opt in — writes .pblame.local.json, gitignored
pblame push --dry-run        # exactly what would be sent, sent nowhere
pblame push                  # send it
```

After that, `git push` shares automatically and `git pull` fetches what your
teammates shared. A new teammate runs `pblame init` then `pblame pull` once.

**Your prompts are redacted on the way out, never on the way in.** Locally the record
keeps exactly what you typed — it is inside `.git`, as private as the code beside it.
Redaction runs when a receipt crosses the machine boundary, so a false positive costs
fidelity in the shared copy and never in your own history. `pblame blame` shows you the
verbatim text and shows teammates the redacted text.

What gets filtered: API keys, AWS/GitHub/Slack tokens, private keys, JWTs, bearer tokens,
`password = …` values, emails, and home-directory paths, plus anything with high enough
entropy to look like a secret. Keyed patterns keep the key and drop the value, so
`password = "hunter2"` becomes `password = "[REDACTED_PASSWORD]"` — that a password was
set is useful, the value is not. Tune it with `pblame redact` before you turn sharing on.

Two config files, split by who the decision belongs to:

| | |
|---|---|
| `.pblame.json` | **committed.** Redaction rules, so the whole team filters the same way. |
| `.pblame.local.json` | **gitignored.** Whether *you* share. A teammate committing `share.enabled` can never switch it on for you. |

```json
// .pblame.json — team-wide
{
  "redaction": {
    "mode": "replace",
    "custom_patterns": [
      { "pattern": "CUST-\\d{6,}", "replacement": "[REDACTED_CUSTOMER_ID]" }
    ]
  }
}
```

`mode: "hash"` replaces secrets with a stable `[SHA256:…]` instead, so a reader can tell
the same secret appeared twice without learning it.

Sharing uses three refs. `refs/notes/pblame` is your verbatim record and is never pushed;
`refs/notes/pblame-shared` is the redacted mirror that travels; `refs/notes/pblame-remote`
is scratch space for a fetch. Because the mirror is separate, pulling cannot overwrite
your own prompts, and pushing never needs `--force` — a rejected push is resolved by
merging, not clobbering.

## What gets recorded, and where

For each prompt: the prompt text, the model, a timestamp, the session id, and the files
and line ranges the turn changed. Nothing else — no tool calls, no responses, no tokens.

Everything stays in your repo:

- `.git/pblame/staging.json` — prompts since your last commit
- `.git/pblame/hook.log` — errors, if a hook ever fails (should stay empty)
- `refs/notes/pblame` — the permanent record, one note per commit

**Prompts can contain things you'd rather not publish.** Nothing is shared until you run
`pblame share` — see below. Until then `git push` leaves the notes behind and nothing
leaves your machine.

## How it works, briefly

`UserPromptSubmit` snapshots the working tree; `Stop` snapshots it again. The diff between
the two is exactly that turn's work, so edits you make by hand between prompts stay
unattributed — they're yours, not the model's. At commit time the pending prompts attach
to the commit as a note. `pblame blame` then joins `git blame` (which already follows
lines across later commits, renames included) against those notes.

## Known limits

- **Whoever can read the repo can read the shared prompts.** There is no per-person
  access control, and notes are not encrypted at rest.
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
