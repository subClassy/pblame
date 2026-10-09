# Day 7 findings — observations from the run, nothing fixed yet

From the terminal log of [day7-dummy-clock-phase13.md](day7-dummy-clock-phase13.md),
steps 0–9, complete.

Nothing in this file has been fixed. Each entry is what happened, why, and what the fix
would be.

## What worked, on real data

- **Concurrent sharing — the thing I expected to break.** Teammate recorded and pushed,
  dummy_clock recorded and pushed, then pulled: `search --limit 5` shows your
  `Replace the duck with a 8 bit duck format` next to the teammate's
  `Change the font to more nerdy one  (shared)`. Neither was lost. This is the case
  blameprompt's force refspec destroys.
- **A clone with no local record gets full attribution.** `pblame blame time.js` in
  `teammate` — 67/163 lines from 14 prompts, a repo that never recorded anything.
- **The hooks carried it.** `git commit` → *attached 1 prompt*; `git push` → *shared 27
  prompts from 13 commits*. No pblame command typed.
- **Repair did what it was for.** 10 prompts across 8 notes, and
  `pblame push --dry-run` then reported **0 secrets redacted** where it previously found 5.
- **First real snapshot cost:** 83ms, ~165ms per prompt, on a repo with ~5 files.
- **`post-rewrite` with sharing on.** The amend carried the receipt onto `3435950`, and
  `pblame show HEAD` found it there.
- **The counts reconcile.** `search` reports 29 of 29 while `push` reports 28 from 14
  commits: 28 local plus the teammate's one shared prompt. The stale mirror copy created by
  the amend (finding 6) is suppressed because `index.load` folds by prompt id and prefers
  local — which is why it is 29 and not 30.
- **`hook.log` stayed empty for the entire run**, across nine steps, two repos, an amend
  and concurrent pushes.

## Confirmed bugs

### 1. `--path` rejects a shell-completed path

```
pblame search --path styles.css      ->  8 prompts
pblame search --path .\styles.css    ->  No prompts matched
```

**Reason.** `index._matches_path` compares the pattern straight against stored paths,
which are POSIX (`styles.css`). PowerShell tab-completion produces `.\styles.css` — a
backslash and a leading `./`. Neither `fnmatch` nor the substring check matches.

**Fix.** Normalise the pattern before matching: backslashes to forward slashes, strip any
leading `./`. Reproduced.

### 2. Redirected output mangles non-ASCII

`before-search.txt` contains `Change the title to "Clock ù a tiny time widget"`. The em
dash is intact in the record — `push --dry-run` prints it correctly.

**Reason.** `cli.main` sets `errors="replace"` on stdout but never the *encoding*, so a
redirected stream keeps the Windows locale codepage. Verified the byte on the pipe: the em
dash leaves as cp1252 `0x97`, and PowerShell decodes it as cp437, where `0x97` is `ù`.

**Fix.** When stdout/stderr is not a tty, reconfigure to UTF-8 — a pipe or a file is
nobody's console. Keep the console's own encoding when it *is* a tty, so the existing ASCII
glyph fallback still applies. `--json` is unaffected (`json.dumps` escapes non-ASCII).

### 3. The push refusal names the wrong file and the wrong remedy

```
✗ sharing is off for this repo. Run `pblame push --dry-run` ... then set
  {"share": {"enabled": true}} in .pblame.json
```

**Reason.** Written before the config split and before `pblame share` existed. Sharing now
lives in `.pblame.local.json`, and `.pblame.json` is the committed file that deliberately
*cannot* enable it — so the message tells you to do the one thing we designed against.

**Fix.** Point at `pblame share`.

### 4. Blank lines get their own prompt header in `blame`

In `blame time.js`, lines 47, 53 and 82 are each a single blank line rendered as its own
group, costing a three-line prompt header apiece.

**Reason.** `blame._groups` starts a new group on any change of owner, and a blank line's
owner is arbitrary — whichever prompt's range happens to cover it. Four of these in one
file is a lot of noise in the output that is supposed to be the demo.

**Fix.** A blank line never starts a group; it joins the current one. Rendering only —
`--json` keeps reporting the true owner. Which prompt "owns" whitespace is not information
anyone needs.

### 5. Every push re-does the whole history — the worst one found

```
pblame push   ->  Shared 28 prompts from 14 commits
```

That count is the cumulative total, not what this push added, and the number is honest
about what the code actually did: it re-read, re-redacted and rewrote **every** note.

Measured on a synthetic 60-commit repo:

| | |
|---|---|
| first push | 7.3s |
| second push, nothing changed | 9.0s |
| notes commits on the mirror | 60 → 120 (+60 for an unchanged push) |
| extrapolated at 500 commits | ~75s per push, +500 notes commits each time |

The real run showed it too: 15 notes commits for 5 prompts after three pushes.

**Reason.** Two, both avoidable:

* `share.plan` calls `notes.read` once per commit — a subprocess each. This is the exact
  pattern already fixed in `index.load`, and the batch reader built for it was not reused.
* `share.stage` calls `merge_into` for every commit unconditionally, and `merge_into`
  always writes. `git notes add` creates a commit per note, so the mirror grows by N
  commits per push even when the content is byte-identical.

**It also invalidates a decision made on the record.** The `pre-push` hook runs in the
foreground, chosen over blameprompt's backgrounding because "one extra round trip for one
small ref beats a backgrounded failure nobody sees". That assumed the work was small. On a
500-commit repo `git push` would block for over a minute, every time.

**Fix.**

1. `plan` uses `index.notes_by_commit` — two subprocesses instead of N.
2. `stage` compares the redacted receipts against what the shared note already holds and
   writes only on a difference. Nothing changed means nothing written, while a changed
   redaction pattern still gets applied retroactively.
3. Report the delta: *"Shared 2 new prompts (28 total)"*.

With 1 and 2 the no-op push should fall well under a second, which also rescues the
foreground choice rather than forcing a retreat to backgrounding.

### 6. A rewrite fixes the local record and leaves the mirror stale

After `git commit --amend`:

```
local ref  - note on old sha: 0 | on new sha: 1     correct
shared ref - note on old sha: 1 | on new sha: 0     stale
```

**Reason.** `notes.remap` takes a `ref` argument and the `post-rewrite` hook never passes
one, so every call defaults to the local ref. The mirror keeps the note on a commit that no
longer exists, and holds nothing for the replacement until the next push re-stages it.

Consequences: the mirror accumulates notes for unreachable commits with nothing to clean
them, and the shared record disagrees with the local one after any amend or rebase. Not
visible in `search` today only because `index.load` prefers the local copy.

**Fix.** Remap both refs in `cmd_rewrite`. Deleting the orphaned mirror entry is the part
that actually needs the ref argument.

### 7. `uninstall --purge` says the prompts are gone and leaves a full copy

```
deleted  refs/notes/pblame (every recorded prompt)
refs left behind:        refs/notes/pblame-shared
prompts still readable:  "text":"the only prompt"
```

**Reason.** `cmd_uninstall` deletes `notes.NOTES_REF` and `.git/pblame/`, and knows nothing
about `SHARED_REF` or `FETCH_REF` — both added later for sharing. The mirror is redacted, so
no *secret* survives, but the prompt text does, in full.

This is the one finding that is a broken promise rather than a rough edge. `--purge` exists
for the person who wants the record gone, and it tells them it is gone while it is not.

**Fix.** Purge every pblame ref, not the one the code knew about first. Worth a test that
enumerates `refs/notes/pblame*` afterwards rather than naming them, so the next ref added
cannot be forgotten the same way.

### 8. The cleanup step does not clean up

Three gaps in step 9 of the script, all mine:

* `Remove-Item -Recurse -Force teammate` failed with *"being used by another process"* —
  `code .` had been run in that folder. It succeeded on a retry. The script should say to
  close the editor first.
* `dummy_clock.backup` and `before-search.txt` are never removed, so the run leaves litter
  beside the repo.
* The sharing refs (`refs/notes/pblame-shared`, and `pblame-remote` in a repo that pulled)
  survive `git remote remove` and deleting the local config. Nothing in the script removes
  them, and per finding 7 `uninstall --purge` would not have either.

## Not bugs — recorded so we do not "fix" them later

- **`--path "*.js" --since 3w` returned nothing, correctly.** The newest prompts at that
  point were 13 Sep and three weeks back was 18 Sep. **The script's expectation was wrong,
  not the tool.**
- **`8b731e5` and the teammate's `e1fe23f` show no author.** `index._commit_meta` reads
  `git log --all`, and neither commit exists in the repo being searched — one was orphaned
  by an old amend, the other is the teammate's commit whose *code* was never pulled into
  dummy_clock, only its notes. Working as designed, and arguably the honest answer.
- **The teammate's first two pushes said "Shared 0 prompts from 0 commits".** Correct: they
  had no *local* receipts, only pulled ones, and `share.push` returns early. Mildly
  misleading wording — it reports 0 while the mirror holds 13 commits. Low priority.
- **After repair, `pblame show 0a59a13` is identical in both repos.** The only redacted
  content in dummy_clock *was* the home path, and repair removed it at the source. So the
  verbatim-vs-redacted contrast the script asked you to look for no longer exists here.
  Not a bug — but the demo will need a prompt carrying a real secret to show it.
- **`before-search.txt` holds 20 of 26 prompts.** Default `--limit 20`. The script should
  have said `--limit 0`.

## Open questions

- **Attribution granularity is visible at scale now.** In `blame time.js`, lines 33–34 are
  comment prose attributed to *"Remove the stopwatch mode completely"*. Plausible — the
  deletion did reflow that comment — but a reviewer reading the demo will question it.
  This is the documented last-writer-wins plus offset-remap limit, not a regression. Worth
  deciding whether the demo names it out loud or avoids files where it shows.
- **`claude-opus-5-5` appears as a model id** on the teammate's prompt. Probably genuine;
  worth one glance at the transcript to rule out a parsing artifact.

## Verdict

Nine steps, two repos, five scratch reproductions. Seven bugs, of which **one is a broken
promise** (finding 7) and **one is a scaling fault that undermines a documented design
decision** (finding 5). Nothing silently lost data, and `hook.log` stayed empty throughout,
which is the property this project has paid most to earn.

Fix order, worst first:

1. **7** — purge leaves a full copy of every prompt. A trust bug.
2. **5** — every push redoes the whole history; ~75s per push at 500 commits.
3. **6** — a rewrite leaves the mirror stale and unreachable notes uncollected.
4. **3** — the push refusal names a file that deliberately cannot do what it asks.
5. **1, 2** — `--path` with a shell-completed path; redirected output mangles non-ASCII.
6. **4, 8** — blank-line groups in `blame`; the cleanup step.
