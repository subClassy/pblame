# Gameplan v2 — post-blameprompt revision (2026-09-07)

Supersedes the week-1 plan in [handover-prompt-attribution-mvp.md](handover-prompt-attribution-mvp.md).
The product thesis, pricing, roadmap milestones 4–5, and dead-ends list there still stand.

## Why v2

We found [Ekaanth/blameprompt](https://github.com/Ekaanth/blameprompt) (MIT, Rust, ~25k LOC,
13+ agent adapters). Its *application* is a consumer gamification product (developer score,
badges, leaderboard, public profile + cloud sync) — not the B2B review/audit product. But its
*plumbing* implements our milestones 2–3, working:

- Hooks per agent → receipts in a staging file → `post-commit` hook attaches receipts to
  whatever commit the developer makes → git notes (`refs/notes/blameprompt`).
- Rebase/amend survival: `post-rewrite` hook remaps notes to new SHAs, adjusting hunk line
  offsets parsed from `git diff --unified=0`.
- Notes sync: background push on `pre-push`, fetch on `post-checkout`.

Two conclusions:

1. **The plumbing is commoditized.** The moat is up-stack: team review surface, audit/query,
   enterprise trust, outcomes data. (They gesture at enterprise too — watch them.)
2. **Their weak spot is our pitch.** Their blame answers *"AI or human?"*. Line ranges are
   replaced, not unioned, when receipts merge, so *"which prompt owns this line?"* inside a
   multi-prompt commit is lossy. That question is our product.

Decision: **use blameprompt as a reference implementation, not a base.** Port the
architecture in Python; keep our schema and our notes ref; fix the range-loss problem.
(MIT — porting algorithms verbatim later is fine with attribution; see bottom.)

## What v2 changes

1. **"One prompt = one commit" is dead.** Developers commit normally; receipts accumulate in
   staging and attach at commit time. This was milestone 2 — blameprompt proves it fits in
   week 1.
2. **The filesystem watcher is dead.** Claude Code hooks are both the turn boundary *and* the
   trigger for diff capture. Agent-agnosticism lives in the adapter list + git hooks, not in
   fs-watching. (Day 1's snapshot module survives — it's how per-turn diffs are computed.)
3. **Line ranges enter the data model now.** With many prompts per commit, `pblame` must
   split a commit's lines among its prompts.
4. The `Session` dataclass and `PromptSource` protocol are gone: sessions are receipts
   grouped by `session_id` (a class when it earns it); the prompt-source seam is now the
   **adapter contract** — a module in `pblame/adapters/` whose `handle(payload)` turns one
   agent hook event into staging updates. New agent = new module + settings installer.

## Architecture

```
Claude Code hooks                      developer commits normally
 UserPromptSubmit ─┐                              │
 Stop ─────────────┴→ pblame hook claude          ▼
                       │  snapshot tree      post-commit hook → pblame attach
                       ▼                          │
              .git/pblame/staging.json ───────────┴→ git notes refs/notes/pblame
                 (receipts, upserted)                     │
                                                          ▼
                                    pblame blame <file>: git blame --line-porcelain
                                    → line→SHA → note receipts → line→prompt render
```

**Capture semantics.** `UserPromptSubmit` opens a receipt with a pre-turn tree snapshot
(temp-index `git add -A` + `write-tree`, from day 1). `Stop` closes it: post-turn snapshot,
per-file line ranges from `git diff-tree --unified=0 pre post`, model read from the session
transcript. The diff between the two snapshots is *exactly this turn's* work — a genuine
improvement over blameprompt's working-tree-vs-HEAD diffs, and it means **manual edits
between turns are correctly NOT attributed to any prompt** (they stay human). An open
receipt found at the next `UserPromptSubmit` (interrupt/crash ate the Stop) is closed at
that boundary.

**Assumptions (state in demo).** One agent session at a time per repo (parallel sessions
interleave snapshots). Manual edits *during* a turn fold into that turn. Text files only.
Ranges recorded at Stop-time go stale if later prompts insert lines above them before the
commit — day 3 corrects the common case by applying each closing turn's hunk-offset table
to earlier staged receipts (the blameprompt rebase-remap algorithm, applied intra-staging).
Full content-anchoring stays milestone 3.

## Revised week

- **Day 2** ✓ restructure to v2 models; Claude adapter (`pblame hook claude`:
  UserPromptSubmit/Stop → staging receipts with ranges + model).
- **Day 3** ✓ `pblame init` (Claude hooks + a marker-fenced `post-commit` git hook) and
  `pblame attach` (staged receipts → note JSON on `refs/notes/pblame`) + the intra-staging
  offset adjustment.
- **Day 4** ✓ `pblame blame <file>` — annotated-source rendering is the demo. `pblame show
  <sha>` for full prompts.
- **Day 5a** ✓ stress test on a real repo ([day5-stress-script.md](day5-stress-script.md)).
  Its job was to make the assumptions leak, and it did — see below.
- **Day 5b** — fix everything day 5a found. All of it, not just the demo-blocking subset.
- **Day 6** — two recordings: a short 3–4 prompt run on dummy_clock, which keeps the
  original day-1 prompts in play and proves the fixes against existing history; then a
  fresh ~20 prompt demo on a new, instantly-legible subject.
- **Day 7** — buffer + demo narrative.

## Stress-test findings (day 5a) and what they changed

Twenty prompts plus rewrites, a merge, interrupts, session changes and concurrent sessions.
The architecture held: every failure was a bug in a leaf, not a flaw in
staging → attach → notes → blame. Eight findings, all now in scope for day 5b.

1. **Encoding killed recording silently.** `subprocess.run(text=True)` decodes with the
   Windows locale codepage. An agent wrote an emoji into a tracked file, cp1252 could not
   decode git's output, every git call in the recorder raised, and `cmd_hook`'s catch-all
   — which exists so a broken hook never breaks the agent's turn — swallowed it. Recording
   stopped for 26 minutes and five prompts with no trace anywhere.
2. **Rename steals a whole file.** No `-M`, so `diff-tree` saw delete+add and the renaming
   prompt claimed every line of the new path.
3. **Deletion-only prompts vanish.** No surviving lines → empty receipt → dropped.
4. **Prompt text polluted** by `<ide_opened_file>` / `<ide_selection>` wrappers.
5. **Cross-session orphans never close** — `find_open` matches on `session_id`.
6. **Partial commits over-attach** — a receipt attaches whole if *any* of its files is in
   the commit.
7. **Rewriting orphans notes** (the known M3 gap), confirmed with a real casualty.
8. **Merge commits carry nothing**, and concurrent sessions clobber staging.

### Three of these are gameplan changes, not bugs

**Recording integrity is a product requirement.** A record with invisible holes is worse
than no record, because people trust it. The pitch is a system of record; the first
question an auditor asks is whether the log is complete. So: a catch-all that protects the
caller must still leave a trace (`.git/pblame/hook.log`), and the roadmap needs gap
detection and a coverage number — "this commit's lines are 94% accounted for" — plus
eventually `pblame doctor`. Nothing before this makes the record trustworthy.

**Deletions force a data-model decision.** Recording only surviving lines is a coherent
choice for `blame` rendering, but "which prompt deleted the auth check" is the more
important review question, and the current model cannot express it. Decision: a receipt
records the *change*; blame *projects* it onto surviving lines. Files touched with no
surviving lines are kept and shown, not dropped.

**Rename is milestone 3 arriving early.** File identity across history is the same problem
as line identity across history. `-M` is a patch over the anchoring work, not a solution;
M3 pressure shows up sooner than the roadmap assumed.

Smaller, but load-bearing: "one agent session at a time" was an accepted assumption and
finding 8 shows it is real — staging is `load → mutate → save` with no locking. Given this
doc's own claim that teams run 2–3 agents in combination, staging needs a lock now rather
than at M4.

## Non-goals this week (revised after day 5a)

Pulled *into* scope, because the stress test showed they are not optional: rename
tracking (`-M`), deletion-only receipts, prompt-text cleaning, orphan reaping,
per-file attach splitting, `post-rewrite` note remapping (a first cut at M3), merge
commits, and a staging lock.

Still out:

- Content-based anchoring — the real M3. `-M` plus offset remapping handles the common
  cases; text that moves between files, or is reformatted wholesale, still rots.
- Multi-developer, notes push/pull, shared index (M4). Risk scoring (M5).
- Other agent adapters; tokens/cost/tools/subagent capture (blameprompt's receipt schema
  shows the ceiling — we take only prompt, model, timestamps, files+ranges).
- Coverage/gap reporting and `pblame doctor` — named above as a requirement, built after
  the demo.
- Prompts that touch no file at all are still dropped; a prompt that only *deletes* is now
  kept.

## Porting & attribution

Reference clone lives in the session scratchpad only — never vendored into this repo.
If their code is ported near-verbatim (e.g. `rebase_notes.rs` offset table), add a NOTICE
entry: "Portions derived from blameprompt (github.com/Ekaanth/blameprompt), MIT License,
Copyright (c) 2026 BlamePrompt Contributors."
