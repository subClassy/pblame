# pblame

**git blame, for the prompt.** Every line Claude Code writes is traced to the instruction
that produced it — kept in your repo as git notes, travelling with your code, redacted
before it leaves your machine.

**Just prompt and commit** — no workflow changes. Then ask any line what it was asked for:

```
$ pblame blame envdiff.py -L 18,35
envdiff.py:18,35  18/18 lines from 2 prompt(s)

  ▎ this thing handles secrets, make it safer
  ▎ claude-sonnet-5 - 54d7048 - 2026-10-16 03:57
  ▎ 18 │ SENSITIVE_MARKERS = (
  ▎ 19 │     "PASSWORD", "PASS", "SECRET", "TOKEN", "KEY",
  ▎ 20 │     "CREDENTIAL", "AUTH", "PRIVATE", "CERT",
  ▎ 21 │ )
  ▎ 22 │
  ▎ 23 │ # Keys come from untrusted .env files. Strip control/escape characters
  ▎ 24 │ # before printing so a crafted key can't inject terminal escape sequences
  ▎ 25 │ # (e.g. to spoof the diff output or hide a real difference).
  ▎ 26 │ _CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
  ▎ 27 │
  ▎ 28 │
  ▎ 29 │ def sanitize(text):
  ▎ 30 │     return _CONTROL_CHARS.sub("?", text)
  ▎ 31 │
  ▎ 32 │

  ▎ For context, my staging .env has lines like
  ▎ DATABASE_PASSWORD=[REDACTED_PASSWORD] and
  ▎ AWS_ACCESS_KEY_ID=[REDACTED_AWS_KEY] - do not put any of that in the
  ▎ code. Make --show-values refuse to print the value of any key whose name
  ▎ contains PASSWORD, SECRET, TOKEN or KEY.
  ▎ claude-sonnet-5 - e6c706c - 2026-10-16 03:46
  ▎ 33 │ def is_sensitive(key):
  ▎ 34 │     upper = key.upper()
  ▎ 35 │     return any(marker in upper for marker in SENSITIVE_MARKERS)
```

That is real output, from a teammate's clone. The list that decides what counts as a
secret was last rewritten by a seven-word prompt; the precise rule it rests on sits three
lines below. The teammate sees both — with the author's password and key redacted.

**[See it happen →](__SITE__)** real Claude Code, one prompt, one commit, and an
interactive blame of the whole file.

## Install

Requires Python 3.10+, git 2.31+, and Claude Code (terminal or VS Code).

```
pipx install git+__REPO__
```

Then, in each repo you want recorded:

```
cd your-project
pblame init .
pblame doctor          # must say "Recording is live"
```

**Open a fresh Claude Code session after `init`** — hooks load when a session starts.
`init` writes two Claude Code hooks into `.claude/settings.local.json` (personal,
gitignored) and four git hooks. Existing hooks and settings are kept, not replaced.

## Our choices

- **Local-first.** No server, no account, no telemetry. The record is git notes in your
  own repo.
- **Verbatim for you, redacted for everyone else.** Your copy keeps exactly what you typed.
  Redaction happens when a prompt crosses the machine boundary, so a false positive costs
  fidelity in the shared copy, never in your history.
- **The prompt travels with the code.** Sharing is plain `git push` and `git pull` of a
  notes ref. A teammate sees the instruction behind every line without asking you for it.
- **Sharing is each person's decision.** It is switched on from a gitignored file, so no
  one can turn it on for a whole team by committing a config.
- **Measured, not promised.** `pblame doctor` times the recorder on *your* repo and tells
  you what it found, including when something is broken.

## What it does

| | |
|---|---|
| `pblame blame <file> [-L 18,35]` | the file, annotated with the prompt behind each line (`--json` for machines) |
| `pblame show [commit]` | every prompt recorded on a commit, with the files and line ranges it produced |
| `pblame search <words>` | find a prompt across all recorded history |
| `pblame doctor` | is this repo actually recording right now? |
| `pblame share` | opt in to sharing with your team (`--off` to stop) |
| `pblame push` / `pull` | share, or fetch what teammates shared (`push --dry-run` previews) |
| `pblame redact <file>` | see what redaction would do to some text |
| `pblame repair` | re-clean prompts recorded by an older version (`--write` to apply) |
| `pblame uninstall` | remove the hooks; history is kept (`--purge` deletes it too) |

`blame`, `search` and `doctor` take `--color` to keep colour through a pipe, as in
`pblame blame app.py --color | less -R`.

### Search what was asked

```
pblame search "rate limit"              # words in the prompt text
pblame search --path src/auth.py        # everything that touched a file
pblame search --path "*.css" --since 2w # a glob, recently
pblame search --model sonnet            # by model
pblame search --author bob --mine       # by author; --mine skips teammates'
pblame search "retry" --regex --json    # regex, machine-readable
```

Exit status is non-zero when nothing matched, so it composes in a shell the way `grep`
does. It reads the whole notes tree in a constant number of git calls, so it stays fast on
a repo with thousands of recorded commits.

### Share with a team

Off by default. Nothing leaves your machine until you say so:

```
pblame share                 # opt in — writes .pblame.local.json, gitignored
pblame push --dry-run        # exactly what would be sent, sent nowhere
pblame push                  # send it
```

After that, `git push` shares and `git pull` fetches what teammates shared. A new
teammate runs `pblame init` then `pblame pull` once.

Redacted on the way out: API keys, AWS/GitHub/Slack tokens, private keys, JWTs, bearer
tokens, `*_PASSWORD=` and `*_SECRET=` values, emails, home-directory paths, and anything
with enough entropy to look like a secret. Keyed patterns keep the key and drop the value —
that a password was set is useful, the value is not.

Redaction rules are team-wide and committed; whether *you* share is personal and not:

| | |
|---|---|
| `.pblame.json` | **committed.** Redaction rules, so everyone filters the same way. |
| `.pblame.local.json` | **gitignored.** Whether you share. |

```json
{
  "redaction": {
    "mode": "replace",
    "custom_patterns": [
      { "pattern": "CUST-\\d{6,}", "replacement": "[REDACTED_CUSTOMER_ID]" }
    ]
  }
}
```

`"mode": "hash"` replaces secrets with a stable `[SHA256:…]`, so a reader can tell the same
secret appeared twice without learning it.

## FAQ

**Does it slow anything down?**
Two places, both measured. Each prompt costs two snapshots of the working tree —
typically under 200 ms, about 190 ms on a 20,000-file repo; `pblame doctor` times it on
yours. And each `git commit` gets slower by about 300 ms, because the commit hook starts
Python to attach what was recorded (430 ms against 125 ms without it, measured on
Windows). Other git commands are unaffected unless sharing is on.

**What happens when I rebase, squash or amend?**
The notes are carried onto the rewritten commits by a `post-rewrite` hook. Renames are
followed too: attribution is stored against each line's position in the commit that wrote
it, so `git blame` does the tracking. Server-side "Squash and merge" on GitHub is not
handled yet — see the table below.

**Does it use git hooks?**
Yes — `post-commit`, `post-rewrite`, `pre-push`, `post-merge`. They are marked sections,
so hooks of your own survive install and uninstall. **Repos that set `core.hooksPath`,
as husky does, are not attributed yet**; that fix is in progress.

**What exactly is recorded?**
For each prompt: its text, the model, a timestamp, the session id, and the files and line
ranges the turn changed. No responses, no tool calls, no token counts. Edits you make by
hand between prompts stay unattributed — they are yours.

**Can my teammates see my prompts?**
Only if you run `pblame share`, and then only the redacted copy. Whoever can read the
repo can read what was shared; there is no per-person access control.

**What if I stop using it?**
`pblame uninstall` removes the hooks and keeps the history; `--purge` deletes every
pblame ref too. Either way your own hooks and settings are left as they were.

**How is this different from git-ai?**
[git-ai](https://github.com/git-ai-project/git-ai) tracks 14 agents and reports how much
of your code AI wrote. Its notes carry session identifiers, and the prompts themselves are
stored outside git. pblame supports one agent, and its notes carry the prompt — so a
teammate who pulls can read what was asked, redacted, without a prompt server.

## What it handles

| | |
|---|---|
| Amend, rebase, interactive squash | handled |
| Renames — by you or by the agent | handled |
| Merge commits, partial commits | handled |
| Sharing with a team, redacted, over git | handled |
| Claude Code, terminal or VS Code | supported |
| GitHub's "Squash and merge" button | planned |
| `cherry-pick`, `reset --soft` | planned |
| Cursor, Codex, Copilot | not yet |
| Repos using husky / `core.hooksPath` | **not attributed — fix in progress** |
| Git worktrees and submodules | not yet |
| One Claude Code session per repo at a time | two at once overlap their snapshots |
| A prompt that changes no file | leaves no record |

Everyone sharing a repo needs a similar pblame version: notes from this version read as
empty to one from before sharing landed.

## Acknowledgements

The redaction pattern table, the hunk line-offset table and the git-hook installation
pattern are derived from [blameprompt](https://github.com/Ekaanth/blameprompt) (MIT).
See [NOTICE](NOTICE).

## License

<!-- TODO before publishing: choose a license and add LICENSE. -->
Not yet chosen.
