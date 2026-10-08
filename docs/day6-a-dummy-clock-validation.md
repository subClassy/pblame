# Day 6a — dummy_clock validation run

> **Status: done (13 Sep), kept as a record.** All eight day-5b fixes confirmed on real
> history, plus two bugs no unit test had caught — both from fixes interacting. The
> successor is [day7-dummy-clock-phase13.md](day7-dummy-clock-phase13.md).

Short, hostile, in-scope. Every step attacks a fix landed in `21db8d8`, using a repo
that already holds **real prompts recorded on 7 Sep**. The strongest thing this can prove
is that day-1 attribution survives a rename three days later.

Run in a Claude Code session whose project folder is
`C:\Users\subCl\Documents\Fun_stuff\apps\dummy_clock`. Hooks are already reinstalled
(`post-commit` + `post-rewrite`); don't run `init` again. Staging was cleared of one
stale receipt, so it starts empty.

`PB` = `C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe`

**Baseline first** — confirm recording is live, then capture what day-1 prompts own:

```
PB doctor                 # must say "Recording is live" before you prompt
PB blame clock.js > before.txt
PB show 0461c2b
```

---

### 1 — rename, the big one (fix #2)

> `Rename clock.js to time.js and update the reference in index.html.`

**Then check immediately:** `PB blame time.js`

Expect: the day-1 prompt *"Create a small functioning clock in js."* still owns its lines
under the new name, and the renaming prompt owns only the `index.html` reference. If the
rename prompt claims the whole file, fix #2 regressed.

### 2 — deletion only (fix #3)

> `Remove the stopwatch mode completely — the button, the handlers and its CSS.`

Expect: a receipt that survives with `(no surviving lines)` on the deleted paths rather
than vanishing. It should still appear in `PB show` after the commit.

### 3 — non-ASCII, the bug that killed the last run (fix #1)

> `Change the title to "Clock — a tiny time widget" using a real em dash, and add a 🕐 to the toggle button label.`

Expect: recording keeps working. **Check `.git/pblame/hook.log` right after this one** —
it must stay empty. Any line in it means a hook errored.

### 4 — interrupt, then switch sessions (fix #5)

> `Rewrite the ring animation to use requestAnimationFrame instead of setInterval, and document why.`

**Press ESC** partway through. Then **exit the session entirely** and start a fresh one.
Do not prompt again in the old session.

### 5 — partial commit (fix #6)

In the new session:

> `Add a small "last updated" caption under the date.`

Then commit **only the JS**:

```
git add time.js && git commit -m "clock: rAF ring, caption logic"
PB show HEAD          # should NOT contain CSS/HTML ranges
cat .git/pblame/staging.json   # the rest still pending
git add -A && git commit -m "clock: caption markup and styles"
PB show HEAD          # the remainder lands here
```

The orphan from step 4 should attach at the first commit despite its session being dead.

### 6 — rewrite history (fix #7)

```
git commit --amend -m "clock: rAF ring, caption logic (amended)"
PB show HEAD
```

Expect `[pblame] carried N prompt receipt(s) onto rewritten commits` and the receipts
still present. Then squash:

```
git rebase -i HEAD~2     # mark the second commit 'squash'
PB show HEAD
```

Expect receipts from **both** commits merged onto the squashed one.

### 7 — concurrent sessions (fix #8)

Open a **second** Claude Code session in the same repo. Prompt in both, roughly together:

- Session A: `Add a title attribute to the toggle button.`
- Session B: `Add a subtle box-shadow to the clock container.`

Then `git add -A && git commit -m "clock: two sessions"`.

Expect **both** prompts in `PB show HEAD`. Previously the second writer silently
overwrote the first. Attribution may be imprecise — snapshots still interleave, and that
remains a stated assumption — but nothing should be *lost*.

---

### Report back

```
PB blame time.js
PB blame index.html
PB show HEAD
git log --oneline --graph
cat .git/pblame/hook.log      # must be empty
cat .git/pblame/staging.json
```

Plus `before.txt` so I can diff day-1 attribution across the rename.

---

## If something looks wrong at any point

Run `PB doctor` first. It checks the whole chain in one shot: hooks registered
(exactly once), the binary they point at still existing, git hooks installed, a live
snapshot of this working tree, the hook log, stale open receipts, and what history
already holds. Exit code 1 means recording is not reliable - stop and fix before
prompting further.
