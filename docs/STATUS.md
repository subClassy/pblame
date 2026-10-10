# Status — where everything stands

Start here. Written 2026-10-08, after search and repair merged.

## The docs, and whether to trust them

| Doc | Status | Read it for |
|---|---|---|
| **[roadmap.md](roadmap.md)** | **live** | The plan. Phases, gates, measured limits, known debt. |
| [day7-dummy-clock-phase13.md](day7-dummy-clock-phase13.md) | done (8 Oct) | Validating sharing, search and repair on the real dummy_clock. |
| [day7-findings.md](day7-findings.md) | closed — 7 fixed | What the run found and how each was fixed. |
| [day8-fix-verification.md](day8-fix-verification.md) | done (9 Oct) | Hostile verification of the seven day-7 fixes, plus the regression they caused. |
| [day8-findings.md](day8-findings.md) | **open — 6 bugs, unfixed** | All 7 fixes verified. A BOM breaks configs; the mirror keeps dead notes; push miscounts. |
| [day6-b-envdiff-demo.md](day6-b-envdiff-demo.md) | **scheduled — after day 8** | The demo recording. Never run. Still the only planned artifact to show anyone. |
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

200 tests. Validated across three hostile runs on a real repo.

## Agreed sequence from here

1. ✔ `pblame repair` — built and merged
2. ✔ merge `feat/search` into main
3. ✔ day 7 validation — found 7 bugs, see [day7-findings.md](day7-findings.md)
4. ✔ fixed all 7, merged (`7065826`) — plus a regression the fixing caused
5. ✔ day 8 verification — all 7 fixes hold; 6 new findings, none blocking
6. **→ record [the envdiff demo](day6-b-envdiff-demo.md)** (yours)
7. fix the day-8 findings (none block the demo)
8. then Phase 2 — the GitHub PR surface

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
touched in four weeks, and the only external tester never reported back. Steps 3 and 4
above exist to change that. More features before then would be guessing.
