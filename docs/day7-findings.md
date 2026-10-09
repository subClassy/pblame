# Day 7 findings — observations from the run, nothing fixed yet

From the terminal log of [day7-dummy-clock-phase13.md](day7-dummy-clock-phase13.md),
steps 0–6. Steps 7–9 still to come; their findings get appended here.

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

## Steps 7–9

Not yet run. Step 7 (amend with sharing on) is meant for **dummy_clock** — the repo with
the real history, where `post-rewrite` has notes worth carrying. One caveat the script
omits: dummy_clock has already pushed, so an amend makes the branch diverge from the
remote. Do **not** `git push` the branch afterwards; `pblame push` alone is the step.
