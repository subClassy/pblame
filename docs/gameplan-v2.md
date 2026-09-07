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

- **Day 2 (now):** restructure to v2 models; Claude adapter (`pblame hook claude`:
  UserPromptSubmit/Stop → staging receipts with ranges + model). Success = synthetic
  hook-event pipeline verified by tests.
- **Day 3:** `pblame init` (installs Claude hooks into the target repo's
  `.claude/settings.json` + a marker-fenced `post-commit` git hook) and `pblame attach`
  (staged receipts → note JSON on `refs/notes/pblame`, staging cleared) + the intra-staging
  offset adjustment.
- **Day 4:** `pblame blame <file>` — annotated-source rendering is the demo; their table
  output proves the data, ours must make people *see* it. `pblame show <sha>` for full
  prompts.
- **Day 5:** demo repo (~20 prompts, real Claude Code session, normal commits).
- Days 6–7: buffer.

## Non-goals this week (unchanged unless noted)

- Rebase/squash survival of *committed* notes (M3) — but steal their offset algorithm for
  staging, above.
- Multi-developer, notes push/pull, shared index (M4). Risk scoring (M5).
- Other agent adapters; tokens/cost/tools/subagent capture (their receipt schema shows the
  ceiling — we take only prompt, model, timestamps, files+ranges).
- Prompts that change no files are dropped at attach time — nothing to blame.

## Porting & attribution

Reference clone lives in the session scratchpad only — never vendored into this repo.
If their code is ported near-verbatim (e.g. `rebase_notes.rs` offset table), add a NOTICE
entry: "Portions derived from blameprompt (github.com/Ekaanth/blameprompt), MIT License,
Copyright (c) 2026 BlamePrompt Contributors."
