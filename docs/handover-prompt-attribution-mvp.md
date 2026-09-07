# Handover Summary — Week-1 MVP of a prompt-attribution layer over git ("git blame, plus the prompt")

## Where we are

The goal is a working one-week demo of a tool that records the prompt behind every AI-generated code change and lets you run a `pblame` command that shows, line by line, which English instruction produced that line. Nothing has been built yet — this session was entirely research, idea-validation and planning. The immediate next action is to scaffold the Python project and build the filesystem-watching recorder (day 1 of the five-day plan below).

The user is proficient in Python, uses Claude Code as their agent, and is moving to Claude Code in VS Code to build this.

## What was done in this session

This session started somewhere completely different and converged on the current idea. The path matters because it rules out several plausible-looking directions.

**Starting point (rejected).** The user brought a pitch document for a *livestreaming platform for vibe coders* — a Twitch competitor where viewers could watch people build software, see a live product preview, browse prompt history, and one-click fork the build. Business model: take rate on creator earnings, feature bounties, fork licences, creator studio subscription, devtool sponsorship. Projected ~$18m ARR.

**Research performed (web searches) and what it found:**

- **Twitch's "Software and Game Development" category is tiny and flat.** July 2026: 1,819 average concurrent viewers, 126 average channels, 1.31M hours watched for the month. Live at time of checking: 619 viewers across 115 channels. Top streams in category sit at 240/232/117 viewers. Source: streamscharts.com. This is the number that killed the streaming platform — the business model needed 5,000 monetising creators.
- **The category's flagship creator is small.** BridgeMind (Matthew Miller), "Vibe Coding an App Until I Make $1,000,000", is at $249,144 ARR on day 211 (~$20k/mo), ~97k YouTube subscribers. Also: BridgeMind already ran its own "Vibeathon" competition on 3 August 2026 with a $5,000 prize pool — which was the exact go-to-market launch event the pitch proposed.
- **Numbers in the original doc that DID verify:** GitGuardian State of Secrets Sprawl 2026 — 28.65M new hardcoded secrets in public GitHub commits in 2025, +34% YoY, largest single-year jump recorded; AI-assisted commits leak at ~3.2% vs ~1.5% human baseline (~2x). AI coding tools market $12.8B in 2026, up from $5.1B in 2024. Cursor ~$4B ARR. Livecoding.tv history (1M+ users since 2015, rebranded to LiveEdu, creators left for Twitch).
- **Numbers that are soft:** the "$4.7B vibe coding market" figure traces to Business Research Company and is widely recycled; Mordor Intelligence puts a similarly-named market at $7.06B for 2026. Treat as directional only. Prefer the $12.8B AI-coding-tools figure.
- **Two developments that post-date the pitch doc:** SpaceX agreed to acquire Cursor/Anysphere for ~$60B (announced June 2026, closing Q3 2026). And AI coding tool *traffic* is falling even as revenue climbs — Lovable down 40%, Vercel v0 down 64% since May, Bolt.new down 27% since June (Forbes/Barclays), suggesting the non-technical "would click fork" wave is churning out.
- **Supporting stats for the CURRENT idea:** 46% of new code is AI-generated; developer trust in AI output fell from 40% to 29% (Stack Overflow 2025); 41% of developers admit pushing AI-generated code to production without full review; Gartner projects 40% of new enterprise production software built with vibe coding techniques by 2028; Veracode found 45% of AI-generated code contains OWASP Top 10 vulnerabilities.

**Pivot reasoning.** The only genuinely durable insight in the original pitch was *prompt → diff → feature provenance*. Stripped of the streaming layer, that becomes an "intent layer for AI-generated code": a system of record for why code exists, not just what changed. `git blame` returns a human who accepted a suggestion; the prompt, model, context and rejected alternatives are all discarded at commit time. Enterprises are heading for majority-AI-written codebases with no way to interrogate them.

**Dead ends explicitly ruled out — do not re-walk these:**

1. **The livestreaming platform.** Ruled out on audience size (see Twitch numbers above), not on product quality. "Build it and they'll come" was explicitly considered and rejected: Livecoding.tv already ran that experiment, got 1M+ signups, and the creators left for Twitch. The category has been offered a video player for a decade.
2. **An individual/solo developer SaaS tier.** A solo dev has no code-review problem; the product's value is between people. Start at team pricing.
3. **Replacing git.** The user was clear and correct: this is an attribution *layer over* git. Git stays the source of truth. Replacing git means replacing GitHub, CI and everything downstream, and asking teams to migrate critical infrastructure to a seed-stage company.
4. **Building the risk-scoring/prediction feature early.** It's the interesting screen but it's a research bet that needs outcome data (reverts, hotfixes, incidents) that doesn't exist yet. Explicitly deferred to milestone 5.

**Product shape agreed (for context, NOT for week 1):** a recorder plugin plus a review surface with three screens — (1) PR sidebar showing what each hunk was asked for and how it was produced, (2) risk score at merge time predicting revert/hotfix likelihood from provenance shape, (3) query interface over history for audit and incident review. Pricing: Team ~$25–40/seat/mo, Business ~$60–90/seat/mo, Enterprise custom/annual. Week 1 builds a sliver of screen 1 as a CLI only.

## Current blocker or next step

No blocker. Work is unstarted and fully specified. Next concrete action: scaffold the Python project and build the recorder skeleton (day 1 below).

One open item the user needs to decide before day 5: **which repo is the demo subject.** It must be something real, built in roughly 20 prompts — a CLI tool or small web app. A suggestion raised at the end of this session and worth taking seriously: **the recorder could record itself being built**, which is a strong demo narrative. Pick this before day 5, not on day 5.

## Technical context the next session needs

**The load-bearing simplification for week 1: one prompt = one commit.** This is what makes the week possible. If each prompt produces exactly one commit, then `git blame` already does all the line-tracking work — including following lines across later commits — so no attribution/anchoring code needs to be written at all. The entire attribution problem collapses to a lookup from commit SHA to prompt text.

**Be honest that this assumption is wrong long-term.** "One prompt, one commit" is not a simplification to relax later; it inverts who controls history. Real teams commit when they decide, squash on merge, and rebase before review. A tool that creates commits per prompt fights the developer's workflow. Milestone 2 (see roadmap) replaces it entirely.

**Where the agent-agnosticism actually lives — this was a point of confusion, resolve it correctly:**
- *Diff capture IS agent-agnostic.* Watching the filesystem and debouncing until writes stop works identically for Claude Code, Cursor, Aider, or a human typing. This is the strategically important half and it must stay vendor-neutral.
- *Prompt capture is NOT agent-agnostic.* Every agent exposes prompt text differently. Claude Code has hooks that fire on prompt submission — a clean, documented capture point. Cursor has no equivalent (you'd read its local session store or wrap the input).
- Therefore: define ONE `PromptSource` interface, ship ONE adapter (Claude Code) in week 1. The agnostic claim stays honest because the hard half is agnostic and the easy half is pluggable. Neutrality across agents is the actual strategic moat — the standard enterprise pattern is 2–3 tools in combination (prototype in Lovable/Bolt, production in Cursor/Claude Code), so no single vendor can own a record of work spanning their competitors.

**Language choice and reasoning.** Python for week 1 — the user is fluent and it's a week; what carries forward is the interface design, not the code. Longer term the recorder should become **Go**, because it's a daemon that installs on other people's machines and a single static binary beats asking developers to manage a Python environment. That port belongs at milestone 2, when the recorder is being rewritten anyway. Exception: if IDE extensions later become the main prompt-capture route, those must be TypeScript regardless — but that's a thin shim and doesn't change the core choice.

**Why `git notes` for storage.** Notes travel with the repo, require no database or backend, and don't modify commit objects. Use a custom ref (e.g. `refs/notes/prompts`). This is deliberately good enough for months and the read side can later be swapped for a service behind the same interface.

**Two hard problems that week 1 deliberately does NOT solve** (name them when demoing, don't pretend otherwise):
1. *Attribution surviving rewriting.* Rebase, squash, reformat, and later refactoring prompts all rot line-range keys. The real solution needs content-based anchoring, similar to how blame follows moves across commits. This is the genuinely hard engineering and the part a competitor can't shortcut.
2. *One prompt rarely maps to one commit.* Real agent sessions are many prompts, partial acceptances, edits and retries, then one squashed commit. The true data model is a many-to-many session graph flattened onto commits — which is why the `Session` abstraction exists in week 1 even though it's barely used.

## Plan for the next session

### Abstractions to define on day 1 (keep them exactly this thin)

- `PromptEvent` — `id`, `text`, `model`, `timestamp`, `session_id`
- `Attribution` — `commit_sha`, `prompt_id`. **That is all.** The temptation is to store line ranges; resist it, week 1 doesn't need them. (Milestone 2 grows this to `(sha, file, hunk, prompt_id)`.)
- `Session` — ordered list of `PromptEvent`s. Barely used in week 1, but establish it now because it becomes the many-to-many graph later.
- `PromptSource` — the interface with one implementation (Claude Code hook adapter).

### Assumptions to enforce in code and state loudly to any viewer of the demo

- One prompt, one commit. No squashing, no rebasing, no amending.
- Linear history, one branch, one developer, one repo.
- The agent is the only thing editing files during a session. Manual edits between prompts get silently folded into the next prompt's commit. This is wrong and acceptable for now.
- Text files only — no binaries, no generated lockfiles.
- Attribution is whole-hunk: if the agent touched a line, the prompt owns it. No attempt to separate agent-written from human-edited within a hunk.

### Five components, roughly a day each

1. **Day 1 — Recorder skeleton.** Filesystem watcher over the repo; debounce until writes stop; snapshot working tree before and after each agent turn. Respect `.gitignore`. No prompt capture yet — the goal for day 1 is purely to prove turn boundaries can be detected reliably.
2. **Day 2 — Claude Code hook adapter.** Capture prompt text, model, timestamp on prompt submission; write to a session log. Define the `PromptSource` interface here so a second adapter is obviously droppable in later.
3. **Day 3 — Committer.** For each turn boundary with a non-empty diff: stage, commit with a truncated prompt as the commit message, and write the full record (prompt text, model, timestamp, session id) to `git notes` under the custom ref.
4. **Day 4 — `pblame` CLI.** Shell out to `git blame --line-porcelain`, get commit-per-line, join against the notes index, render the file with each line prefixed/annotated by the prompt that produced it. **Give this a full day — the rendering is what makes people understand the idea.** This is the demo.
5. **Day 5 — Build the demo repo.** ~20 prompts of real work, then run `pblame` over it and check whether the output actually reads well. Expect the assumptions to leak here; that is the point of the day.

Days 6–7 are buffer and will be needed.

### The demo moment to aim for

Open a file, run `pblame`, and show every line tracing to the English sentence that caused it. Then show one line that came from a vague one-line prompt sitting next to a line that came from a careful, specific prompt. That contrast is the moment someone sees why this matters for code review.

### Index (day 4, trivial)

Read-side only: `commit_sha → PromptEvent`, built by reading the notes ref, held in memory, rebuilt on each invocation. Do not build a database.

### Optional, only if days 1–4 went well

A one-page web view: same join, rendered as a file with hover-to-see-prompt. The CLI is what proves the idea; the web view is decoration. Skip it without guilt.

## State of things

- **Nothing is built.** No repository, no code, no scaffolding exists yet.
- All work so far is analysis and planning, contained in the previous conversation and in this handover.
- The original pitch document (the livestreaming platform) was provided by the user as an uploaded text file. It is superseded — its only surviving contribution is the prompt-provenance insight.

## References

Post-week-1 roadmap, agreed and sequenced (do not build ahead into these):

1. Week 1 as scoped above.
2. **Decouple recording from committing.** Keep recording prompts and pre/post snapshots continuously, but stop creating commits. When the developer commits normally, map the resulting diff back onto recorded prompt snapshots. One commit then carries several prompt attributions at hunk granularity, and history stays the developer's. This is where `Attribution` grows and `Session` starts earning its keep. Likely also the Go port of the recorder.
3. **Survive rebase and squash** via content-based anchoring.
4. **Multi-developer support and a shared index** (swap the notes read-side for a service).
5. **Join attribution to outcomes** — reverts, hotfixes, incidents — to test whether provenance predicts defects. This is the venture thesis and nothing before it proves it; everything before it builds the instrument that lets the question be asked.

Pitch line that lands with both engineers and executives: **"git blame, for the prompt."** Use it. Do not explain the livestreaming origin — it makes the idea sound smaller than it is.

Honest caveat the user is aware of and should keep stating: screens 1 and 3 of the eventual product are a product; screen 2 (risk prediction) is a research bet. If provenance turns out not to predict defects, what remains is a well-made audit log — a real business, but not the venture-scale one.

## First action recommended for the next session

Read this handover. Then scaffold a new Python project for the recorder and start on **day 1 only**: a filesystem watcher over a target repo that debounces file writes, detects agent turn boundaries, and snapshots the working tree before and after each turn, respecting `.gitignore`. Do not build prompt capture, committing, or `pblame` yet — day 1's single success criterion is reliable turn-boundary detection. Define `PromptEvent`, `Attribution`, `Session` and `PromptSource` as thin dataclasses/protocols up front, but leave `PromptSource` unimplemented until day 2. Do NOT design around rebase/squash survival or multi-prompt commits — those are milestones 2 and 3 and were deliberately excluded; "one prompt = one commit" is the enforced week-1 assumption and it is what makes `git blame` do the attribution work for free.
