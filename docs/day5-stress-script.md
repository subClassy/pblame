# Day 5 — dummy_clock stress script

> **Status: done (8–10 Sep), kept as a record.** It found eight problems, including a
> recorder that had silently stopped for 26 minutes. All are fixed; the findings live
> in [gameplan-v2.md](gameplan-v2.md#stress-test-findings-day-5a-and-what-they-changed).

20 prompts plus git operations, ordered to attack the assumptions in
[gameplan-v2.md](gameplan-v2.md). Run every prompt in a Claude Code session whose
project folder **is** `C:\Users\subCl\Documents\Fun_stuff\apps\dummy_clock` —
hooks load from that repo's `.claude/`, so a session anywhere else records nothing.

Don't re-run `pblame init`; it's already installed there.

Keep a scratch note of anything surprising. Phases 4 and 6 are *expected* to fail —
that's the point of running them.

`PB` below means `C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe`

---

## Phase 1 — prompt-style contrast, many prompts into one commit

Targets: the demo moment (vague vs. careful), the interior-insertion range split
that already broke once, and no-op prompts.

**1.** `make it look nicer`

**2.** `In clock.js add a 12-hour toggle: keep the existing pad() helper, store state in a module-level use24Hour boolean, expose a toggle button in index.html with id "mode-toggle", and render AM/PM into its own <span id="meridiem"> so CSS can size it independently.`

**3.** `What does setInterval do if the tab is backgrounded?` — a question, no edits.
→ expect: receipt recorded, then dropped at attach (nothing to blame).

**4.** `Add a favicon link and a meta description to the top of index.html's head.`
→ the range-split path: this inserts *above* lines earlier prompts own.

**5.** `Remove the duck's wing path element and its CSS.`
→ deletions contribute no ranges; earlier ranges below must shrink.

**➜ COMMIT A:** `git add -A && git commit -m "clock: 12h toggle, meta, drop wing"`

Check: `PB show HEAD` — expect 4 receipts (not 5; the question was dropped).
Check: `PB blame index.html` — every line should trace to exactly one prompt.

---

## Phase 2 — interrupts and session boundaries

Targets: the orphaned-receipt path, and whether `find_open` can close a receipt
left open by a *different* session (I think it can't — I want to see it).

**6.** `Rewrite style.css to use CSS custom properties for every color, add a full dark mode via prefers-color-scheme, and restyle the toggle button.`
→ **press ESC to interrupt it partway through**, after it has written at least one file.

**7.** `Just finish the color variables, nothing else.`
→ expect: prompt 6's orphan closes here, owning whatever it managed to write.

**➜ Now fully exit the session** (Ctrl+C / close it), then **start a fresh session**
in the same folder.

**8.** `Add a subtle fade-in animation to the clock digits.`

**9.** `Show the current date under the clock in a <div id="date">, formatted like "Mon 8 Sep".`

**➜ COMMIT B:** `git add -A && git commit -m "clock: dark mode, date, animation"`

Check: `PB blame style.css` — if prompt 6's work shows as unattributed, that's the
cross-session orphan gap and I want to know.

---

## Phase 3 — file lifecycle and partial commits

Targets: new files, renames (we don't pass `-M` to blame), deletions, and receipts
whose files aren't in the commit being made.

**10.** `Extract the date logic out of clock.js into a new file date.js and load it from index.html.`

**11.** `Rename style.css to styles.css and update the reference.`
→ expect trouble: blame matches receipts by path, and a rename changes it.

**12.** `Delete date.js and fold its logic back into clock.js.`

**13.** `Add a seconds progress ring around the clock using an SVG circle with stroke-dasharray.`

**➜ PARTIAL COMMIT C:** commit **only** the HTML: `git add index.html && git commit -m "clock: markup for ring and date"`

Check: `PB show HEAD` — receipts touching only CSS/JS should be **absent** here.
Check: `cat .git/pblame/staging.json` — they should still be sitting in staging.

**➜ COMMIT D:** `git add -A && git commit -m "clock: ring and date logic"`

Check: the staged leftovers land here instead.

---

## Phase 4 — history rewriting (known gap, expected to break)

Notes attach to a commit SHA. Rewriting the commit orphans the note; that's
milestone 3 and deliberately unbuilt. Confirm how it fails and how loudly.

**14.** `Make the ring color shift with the hour.`

**➜ AMEND:** `git add -A && git commit --amend -m "clock: ring reacts to hour"`

Check: `PB show HEAD` → expect **no receipts**, and `PB blame clock.js` to lose
attribution for that commit's lines.

**15.** `Add a tooltip on the toggle button explaining the mode.`

**➜ COMMIT E**, then **squash the last two commits**:
`git rebase -i HEAD~2` and mark the second `squash`.

Check: how much attribution survives. Expect: not much.

---

## Phase 5 — branching and merging

Targets: notes on divergent history, and `attach` on a merge commit (`diff-tree`
on a merge behaves differently — I'm unsure this works and want the evidence).

**➜** `git switch -c feature/stopwatch`

**16.** `Add a stopwatch mode: a second button that swaps the clock display for a running timer with start/stop/reset.`

**➜ COMMIT F** on the branch.

**➜** `git switch main`

**17.** `Add a keyboard shortcut: pressing "t" toggles 12/24 hour mode.`

**➜ COMMIT G** on main.

**➜ MERGE:** `git merge feature/stopwatch` (resolve conflicts by hand if any —
manual conflict resolution is itself an untested path).

Check: `PB blame index.html` across the merged history. Does every branch's work
still trace? Does the merge commit itself carry anything?

---

## Phase 6 — text edge cases and concurrency

**18.** Paste a deliberately awful prompt — long, multiline, quotes, unicode:
```
Refactor the clock so it's "resilient" — I mean: (a) it shouldn't drift, (b) 🕐 emoji in the title, (c) handle the edge case where `new Date()` returns something weird, and (d) add a comment block at the top explaining the design decisions in detail, including why setInterval is imperfect for timekeeping and what you'd use instead in production.
```
→ tests JSON escaping, prompt wrapping in the blame render, unicode on a cp1252 console.

**19.** Before prompting, **manually edit** `clock.js` in your editor (add a comment),
save, then prompt: `Add a title attribute to the toggle button.`
→ expect: your manual line stays unattributed, the agent's line doesn't.

**20.** `make it feel more premium` — deliberately vague again, for the demo contrast.

**➜ COMMIT H:** `git add -A && git commit -m "clock: polish"`

**Optional final stress:** open a **second** Claude Code session in the same repo and
prompt in both at once. The gameplan assumes one session at a time; snapshots will
interleave. I expect wrong attribution — worth knowing how wrong.

---

## When you're done

Leave everything as-is and tell me. I'll want:

- `PB blame index.html`, `PB blame clock.js`, `PB blame styles.css`
- `PB show` on a few commits
- `git log --oneline --graph --all`
- `.git/pblame/staging.json` and `.git/pblame/hook.log`

The hook log is the one to watch — anything in it means a hook errored silently
without interrupting your session.
