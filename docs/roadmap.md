# Roadmap — from the week-1 MVP to a product

Written 2026-09-28, updated 2026-10-08. Supersedes the week planning in
[gameplan-v2.md](gameplan-v2.md), which stays the record of *why* the architecture is what
it is. [STATUS.md](STATUS.md) indexes every document and the backlog.

## Status quo

**The recorder works.** `pblame init / doctor / blame / show / uninstall`, packaged as a
wheel, 76 tests, validated across two hostile runs on a real repo (rename, deletion,
interrupt, session change, partial commit, amend, squash, merge, concurrent sessions).
Milestone 2 is done; milestone 3 is half done — amend and rebase are handled, content
moving between files is not.

**One person can see the record.** That is the whole gap. `git push` leaves notes behind
and we install no push hook, so the prompt history lives on exactly one machine.

**Validation is thin.** One external tester, mid-test. No reviewer has been shown the
output. Nothing built so far tests the venture thesis; it builds the instrument that
lets the question be asked.

Effort below is in focused working days, not calendar days — the "one week" MVP took
about three calendar weeks of intermittent work, and that ratio will hold.

## Phase 1 — make the record shareable ✔ done (merged 2026-09-29)

Branch `feat/sharing-redaction`. Spec: [spec-sharing-redaction.md](spec-sharing-redaction.md).

Prompts are not safe to publish by default, so this is a trust problem wearing a
plumbing costume. Three parts, in order:

1. **Note format → JSONL**, so `git notes merge` works natively. A prerequisite, and
   cheap now / expensive once anyone has data.
2. **Redaction at the machine boundary** with a detect-and-warn pass at capture.
3. **Opt-in sharing** — `pblame push` / `pull`, a preview of exactly what would leave,
   and never an automatic first push.

Landed as specified, plus two things the work itself forced: sharing is opt-in per
developer in a gitignored file (a committed `share.enabled` would have started a
teammate's prompts leaving their machine the moment they pulled), and `pblame doctor`
reports secrets sitting in the record before anyone shares.

**Gate, still open:** would your friend turn this on for his team's repo after reading
`pblame push --dry-run`? Worth asking him directly — it is the one thing that cannot be
determined from here.

**Found while testing:** GitHub does not render git notes anywhere in its UI. Pushed
notes are stored and invisible. Nothing in this phase makes attribution visible to a
reviewer who has not installed pblame, which is the entire reason Phase 2 exists.

## Phase 2 — put it where review happens (≈5 days)

A GitHub Action that reads the notes for a PR's commits and posts what each hunk was
asked for, as a review comment or check summary. This is screen 1 of the product.

Deliberately **not** a standalone web app. Reviewers are already in the PR; a new surface
asks them to change habit for a benefit they have not felt yet. The visual work belongs
here, inside a diff they were going to read anyway.

Depends entirely on Phase 1 — a PR comment needs notes the CI runner can fetch.

**Gate:** does a reviewer change what they say in a review because of it? If they read it
and shrug, screens 1 and 3 are a nicer audit log, not a review tool, and pricing has to
move down accordingly.

## Phase 3 — query and audit ✔ done (merged 2026-10-08)

Screen 3: search across recorded history. "Show me everything the model wrote in
`payments/` last quarter", "which prompts touched auth", "what was asked for before this
incident". Needs the read side behind an interface so notes can later be swapped for a
service (milestone 4 of the original plan).

This is the half of the product that sells to compliance rather than to engineers, and
it is the cheapest one to build on top of what exists.

Taken before Phase 2 because search *is* the prompt-library product, it serves the only
kind of user we actually have, and it needs no GitHub repo or second person to be worth
using.

Delivered as `pblame search` (text, path, date, model, author), plus two things that came
out of measuring rather than assuming: the snapshot index fix (20x, and a correctness bug
with it) and the conclusion that no Python git binding would help. `pblame repair` came
with it, for prompts recorded before the text cleaning existed.

**Gate, unanswered:** do *you* reach for it, or for `git log`? That is what
[day 7](day7-dummy-clock-phase13.md) is for.

## Phase 4 — the outcomes join (open-ended, a research bet)

Screen 2: join attribution to reverts, hotfixes and incidents, and test whether the
*shape* of provenance predicts defects. Needs months of recorded history from real teams
before the question can even be asked.

Nothing before this proves the venture thesis. If provenance turns out not to predict
defects, what remains is a well-made audit log — a real business, not a venture-scale one.
Keep saying that out loud.

## Agreed sequence (2026-10-08)

1. ✔ `pblame repair`
2. ✔ merge search into main
3. **[Day 7 validation](day7-dummy-clock-phase13.md)** — sharing, search and repair on the
   real dummy_clock. Phases 1 and 3 have only been exercised on scratch repos.
4. **[The envdiff demo](day6-b-envdiff-demo.md)** — still the only planned artifact to
   show anyone.
5. Phase 2.

Chasing the external tester was dropped by decision.

## Running alongside, not after

- **Reviewer validation (≈1 day).** Put `pblame blame` on a real file in front of three to
  five engineering managers and watch whether they lean in. It is the cheapest way to
  learn whether Phase 2 should be a PR comment, a check annotation, or something else —
  and those lead to different products. Needs the demo recorded first.
- **Nobody is using this yet, including us.** dummy_clock has gone four weeks without a
  commit and the external tester never reported back. Three phases of engineering against
  zero usage signal is now a larger risk than any missing feature; steps 3 and 4 above are
  the cheapest way to change that.
- **The Go or Rust port.** The gameplan put this at milestone 2 and we skipped it.
  Distribution friction is real — the friend needed Python and a wheel — and blameprompt
  is immune by construction to the encoding bug class that cost us 26 minutes of
  recording. Not urgent at one tester. Reconsider at five, or the first time someone
  cannot install Python.

## Measured scaling limits (2026-09-30)

Where the cost actually is, so nobody optimises by guess:

| | cost | scales with |
|---|---|---|
| `snapshot_tree` (x2 per prompt) | 94ms on 20,000 files | number of tracked files |
| `git blame` | 40ms typical, 330ms at 20,000 commits of one file's history | that file's history depth, and only until every line is attributed |
| `index.load` (search) | 2 subprocesses, any size | nothing — it reads the notes tree in one pass |
| loose objects | ~3 per prompt | normal `git gc` packs them |

**No Python library would help.** Seeding the snapshot index from the repo's real one made
it 20x faster, and after that the remaining 94ms is process spawn, not work: enabling git's
own `core.fsmonitor` and `core.untrackedCache` changed nothing measurable at 20,000 files.
`pygit2` would remove the spawn — about 150ms per prompt — which is invisible next to an
agent turn, and it would add a compiled dependency that the eventual Go port discards.
`dulwich` is pure Python and slower at tree hashing; `GitPython` wraps the same CLI.

The lever that *would* matter past ~100,000 files is `core.fsmonitor`, because the stat
sweep is O(files) even with a warm index. Rather than guess the threshold, `pblame doctor`
reports the measured snapshot time and recommends it when the number gets big.

## Known debt, deliberately unpaid

**Notes are backward but not forward compatible.** Since Phase 1, notes are written as
JSONL. An older pblame reads nothing from them — its parser expects the old
`{"version": 1, "receipts": [...]}` object. Reading *old* notes still works and is
tested, so upgrading is safe; the hazard is two people on different versions sharing a
repo, where the one on the older build silently sees an empty record.

Not worth fixing while there is one tester on a fixed wheel. Worth fixing before a second
person installs: the note's first line already carries `{"pblame":1}`, so the version is
there to check — a reader that finds a version it does not understand should say so rather
than return nothing. Silent emptiness is the failure mode this project has been bitten by
twice.

## What could stop this

| Risk | Where it shows |
|---|---|
| Prompts are too sensitive to share at all | Phase 1 gate. Would make this a single-player tool, and kill team pricing. |
| Reviewers do not care why a line exists | Phase 2 gate. Product survives as audit, at lower price. |
| Provenance does not predict defects | Phase 4. The venture thesis dies; the product does not. |
| blameprompt ships the team surface first | They have the plumbing and 13 adapters, and an enterprise page. Our lead is attribution correctness, which is invisible until someone compares. |
