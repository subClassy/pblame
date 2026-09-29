# Roadmap — from the week-1 MVP to a product

Written 2026-09-28. Supersedes the week planning in [gameplan-v2.md](gameplan-v2.md),
which stays the record of *why* the architecture is what it is.

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

## Phase 1 — make the record shareable (≈5 days) ← next

Branch `feat/sharing-redaction`. Spec: [spec-sharing-redaction.md](spec-sharing-redaction.md).

Prompts are not safe to publish by default, so this is a trust problem wearing a
plumbing costume. Three parts, in order:

1. **Note format → JSONL**, so `git notes merge` works natively. A prerequisite, and
   cheap now / expensive once anyone has data.
2. **Redaction at the machine boundary** with a detect-and-warn pass at capture.
3. **Opt-in sharing** — `pblame push` / `pull`, a preview of exactly what would leave,
   and never an automatic first push.

**Gate:** would your friend turn this on for his team's repo after reading what it sends?
If the answer needs a caveat, the consent model is wrong, not the plumbing.

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

## Phase 3 — query and audit (≈5 days)

Screen 3: search across recorded history. "Show me everything the model wrote in
`payments/` last quarter", "which prompts touched auth", "what was asked for before this
incident". Needs the read side behind an interface so notes can later be swapped for a
service (milestone 4 of the original plan).

This is the half of the product that sells to compliance rather than to engineers, and
it is the cheapest one to build on top of what exists.

## Phase 4 — the outcomes join (open-ended, a research bet)

Screen 2: join attribution to reverts, hotfixes and incidents, and test whether the
*shape* of provenance predicts defects. Needs months of recorded history from real teams
before the question can even be asked.

Nothing before this proves the venture thesis. If provenance turns out not to predict
defects, what remains is a well-made audit log — a real business, not a venture-scale one.
Keep saying that out loud.

## Running alongside, not after

- **Reviewer validation (≈1 day, do it during Phase 1).** Put `pblame blame` on a real
  file in front of three to five engineering managers and watch whether they lean in. It
  is the cheapest way to learn whether Phase 2 should be a PR comment, a check
  annotation, or something else — and those lead to different products.
- **The demo recording ([day6-b](day6-b-envdiff-demo.md)).** Still unrecorded. Worth 40
  minutes before any of those conversations; dummy_clock cannot serve as the artifact
  because of the blackout hole in its history.
- **The Go or Rust port.** The gameplan put this at milestone 2 and we skipped it.
  Distribution friction is real — the friend needed Python and a wheel — and blameprompt
  is immune by construction to the encoding bug class that cost us 26 minutes of
  recording. Not urgent at one tester. Reconsider at five, or the first time someone
  cannot install Python.

## What could stop this

| Risk | Where it shows |
|---|---|
| Prompts are too sensitive to share at all | Phase 1 gate. Would make this a single-player tool, and kill team pricing. |
| Reviewers do not care why a line exists | Phase 2 gate. Product survives as audit, at lower price. |
| Provenance does not predict defects | Phase 4. The venture thesis dies; the product does not. |
| blameprompt ships the team surface first | They have the plumbing and 13 adapters, and an enterprise page. Our lead is attribution correctness, which is invisible until someone compares. |
