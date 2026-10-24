# Status — where everything stands

Start here. Written 2026-10-08, after search and repair merged. Updated 10 Oct, after
the day-9 verification run.

## The docs, and whether to trust them

| Doc | Status | Read it for |
|---|---|---|
| **[roadmap.md](roadmap.md)** | **live** | The plan. Phases, gates, measured limits, known debt. |
| [day7-dummy-clock-phase13.md](day7-dummy-clock-phase13.md) | done (8 Oct) | Validating sharing, search and repair on the real dummy_clock. |
| [day7-findings.md](day7-findings.md) | closed — 7 fixed | What the run found and how each was fixed. |
| [day8-fix-verification.md](day8-fix-verification.md) | done (9 Oct) | Hostile verification of the seven day-7 fixes, plus the regression they caused. |
| [day9-fix-verification.md](day9-fix-verification.md) | **done (10 Oct)** | The day-8 fixes verified on real history, by me, from the terminal. Found two more, both fixed. |
| [git-ai-teardown.md](git-ai-teardown.md) | **live** | The nearest competitor: what to copy in engineering and marketing, and what to keep different. |
| [day10-findings.md](day10-findings.md) | **open — 9 findings** | From building the site. 20 is a silent failure in husky repos; 21–28 are smaller. |
| [demo-recording-manual.md](demo-recording-manual.md) | **superseded** | The dummy_clock video. Replaced by the site and [tools/demo/](../tools/demo/README.md); its hand-recording section still applies to Phase 2. |
| [day8-findings.md](day8-findings.md) | **5 fixed, 1 open by decision** | All 7 day-7 fixes verified. The BOM and every miscounted total are fixed; dead mirror notes are reported, not removed. |
| [day6-b-envdiff-demo.md](day6-b-envdiff-demo.md) | **ready — yours, next** | The 20 prompts that build the demo subject. Updated 10 Oct with a secrets prompt and the search/sharing beats. |
| [spec-sharing-redaction.md](spec-sharing-redaction.md) | delivered | Why sharing is shaped as it is. Two deviations, listed below. |
| [gameplan-v2.md](gameplan-v2.md) | **partly outdated** | Architecture rationale and the day-5a findings: still true. Its "Revised week" schedule is dead — superseded by roadmap.md. |
| [handover-prompt-attribution-mvp.md](handover-prompt-attribution-mvp.md) | historical | Product thesis, pricing, and the ruled-out dead ends, which all still stand. Its week-1 plan does not. |
| [day5-stress-script.md](day5-stress-script.md) | done, archive | Executed 8–10 Sep. Findings folded into gameplan-v2. |
| [day6-a-dummy-clock-validation.md](day6-a-dummy-clock-validation.md) | done, archive | Executed 13 Sep. Found two bugs unit tests could not. |

## Built and merged

| | |
|---|---|
| Recording | `init`, `doctor`, `uninstall`, hooks for capture + attach + rewrite |
| Attribution | `blame`, `show` — joined on the commit-time path and line number |
| Sharing (Phase 1) | `share`, `push`, `pull`, `redact` — redacted mirror, opt-in per developer |
| Search (Phase 3) | `search` by text, path, date, model, author |
| Maintenance | `repair` — re-cleans prompts recorded by an older version |
| Removal | `uninstall --purge` — every pblame ref, enumerated not named |

238 tests. Validated across four hostile runs on a real repo.

## Agreed sequence from here

1. ✔ `pblame repair` — built and merged
2. ✔ merge `feat/search` into main
3. ✔ day 7 validation — found 7 bugs, see [day7-findings.md](day7-findings.md)
4. ✔ fixed all 7, merged (`7065826`) — plus a regression the fixing caused
5. ✔ day 8 verification — all 7 fixes hold; 6 new findings, none blocking
6. ✔ fixed 5 of them; the 6th is a decision, see the backlog
7. ✔ [day 9](day9-fix-verification.md) — verified them on real history; found and fixed
   three more, including a redaction gap that leaked prefixed secret keys
8. ✔ the demo — rendered from dummy_clock's real history, as
   [a video](../tools/demo.tape) and [a page](demo-recording-manual.md#the-page).
   The envdiff build is now optional polish, not a blocker.
9. ✔ [git-ai teardown](git-ai-teardown.md) — the nearest competitor; its founders joined
   Codex. Its notes carry session IDs, not prompts: ours travelling in git is the line to
   lead with.
10. ✔ the site — real Claude Code filmed writing envdiff, an interactive blame, three
    feature clips. Built in `site/`, previewed privately, **not yet published**: the
    [pre-publish decisions](day10-findings.md) are yours. Pipeline in
    [tools/demo/README.md](../tools/demo/README.md).
11. **→ finding 20** (husky silently disables attribution) — before anyone installs from
    the public repo
12. then Phase 2 — the GitHub PR surface, which needs the squash-merge action from the
    teardown first

Dropped by decision: chasing the external tester's feedback.

## Deviations from the specs, recorded

- **`post-checkout` was specified and not built.** Git never clones `.git/hooks`, so it
  cannot help a fresh clone, and hooking every branch switch would mean a network fetch
  each time. `post-merge` does the useful half: pull code, get the prompts with it.
- **Sharing is opt-in from a gitignored file**, which the spec did not anticipate. A
  committed `share.enabled` would start a teammate's prompts leaving their machine the
  moment they pulled.

## Backlog — not scheduled, not forgotten

Roughly by how much it would hurt to need it and not have it.

| | Why it is waiting |
|---|---|
| **Pruning dead mirror notes** | The mirror keeps a note per commit a rewrite abandoned, and they travel to every clone. `doctor` now counts them; deleting them is not reversible and the gain is cosmetic. Design and trigger in [day8-findings.md](day8-findings.md#the-prune-decision). |
| **Note version check** | A pblame from before Phase 1 reads JSONL notes as *empty*, silently. The `{"pblame":1}` line exists to be checked. Fix before a second person installs. Detail in [roadmap.md](roadmap.md#known-debt-deliberately-unpaid). |
| **Content-based anchoring** | The real milestone 3. `-M` plus offset remapping handles renames, amends and rebases; text that moves *between* files or survives a reformat still loses attribution. |
| **Accepted vs overridden lines** | blameprompt's `compute_acceptance_stats` — how much of the agent's output the human kept. A review signal we do not capture, and it feeds Phase 4. |
| **Coverage / gap reporting** | "This commit's lines are 94% accounted for." `doctor` reports health but not completeness, and completeness is what an auditor asks about. |
| **Go or Rust port** | Distribution friction is real and the encoding bug class cannot occur there. Reconsider at five testers, or the first person who cannot install Python. |
| **Worktrees and submodules** | `init` and the snapshot assume `.git` is a directory. Snapshots degrade to the slow path rather than breaking. |
| **No-op prompts** | A prompt the agent declined ("it already does that") leaves no record. Arguably audit-relevant, definitely noise for blame. Undecided. |
| **Shared index as a service** | Milestone 4. Notes-on-a-remote is deliberately enough for now; the read side already sits behind `index.Entry` so the source can change. |
| **Compliance export** | Phase 3 answers queries interactively. A report an auditor can keep is a different artifact. Wait until someone asks. |

## The thing no document fixes

Three phases are built and **nobody is using it, including us** — dummy_clock has not been
touched in four weeks, and the only external tester never reported back. Step 8 above is
the one that changes that. More features before then would be guessing.

Day 9 is a small argument for the opposite view: running the tool in earnest found a
secret-redaction gap that 219 passing tests did not. Use before build, every time.
