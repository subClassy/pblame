# git-ai teardown — what to copy, what not to

Researched 16 Oct 2026 from git-ai's README, docs, and its published standard
(`specs/git_ai_standard_v3.0.0.md`). git-ai is **Apache-2.0**, so code can be borrowed with
attribution in `NOTICE`, the same way blameprompt's MIT code was.

## The one-paragraph version

git-ai is the closest thing to pblame that exists, and better funded in attention: its
founders joined OpenAI's Codex team on 12 Sep 2026 (founders hired, not company acquired;
the open-source project continues). It does what we do — line-level attribution to agent,
model and session, stored in git notes, surviving rewrites — across 14 agents to our one.

**But its notes do not carry the prompt.** They carry hashed session IDs. The transcript
stays on the author's machine, or in git-ai's paid Teams prompt store. A teammate who
clones a git-ai repo can see *that* Claude wrote a line, not *what Claude was told*. In
pblame the redacted prompt travels in git, to anyone who pulls, with no server. That gap,
and what it lets us say about each prompt, is the whole positioning:

> **git-ai tells you how much of your code an AI wrote. pblame tells you what it was told
> — and whether that was a decision or a shrug.**

Their pitch is measurement, which is why Codex wanted them: *how much AI code, at what
cost, with what return.* Ours is review: *what was asked, and was it specified.* Different
buyer questions. We should not try to out-measure them.

---

## Side by side

| | git-ai | pblame |
|---|---|---|
| Capture | Agent hook calls `git-ai checkpoint` **after every tool call** | `UserPromptSubmit` + `Stop` — **one diff per turn** |
| Git integration | "No git hooks, does not wrap git" — a daemon reconciles notes 5–100ms after operations | `post-commit`, `post-rewrite`, `pre-push`, `post-merge` |
| Notes ref | `refs/notes/ai`, one note per commit | `refs/notes/pblame` + `pblame-shared` mirror |
| Note format | Attestation section, `---`, JSON metadata. Lines keyed by session hash | JSONL, version line first, receipt per prompt |
| **Prompt text** | **Not in git.** Local, or Teams cloud store | **In git**, verbatim locally, redacted in the shared mirror |
| Redaction | "Scanned and redacted, saved outside git" | At the machine boundary, on push, with consent |
| Human lines | `h_` keys from IDE-observed typing; else "untracked" | Unattributed = not from a recorded prompt |
| Accepted / overridden | Tracked per prompt (`accepted_lines`, `overriden_lines`) | Backlog |
| Rewrites | rebase, squash, amend, cherry-pick, stash, reset, merge, pull | amend, rebase, squash, merge, rename |
| Server-side squash-merge | CI action, or Teams | **Nothing** |
| Stats | `git ai stats` → human/AI %, JSON; a `you ██░░ ai` bar on every commit | None |
| Search | None found | `pblame search` by text, path, date, model, author |
| Install | One-line curl / PowerShell, global, **no per-repo setup** | wheel + `pblame init` **per repo** |
| Agents | 14 + 4 background agents | Claude Code |
| Spec | Published, versioned, RFC 2119, with errata | `{"pblame":1}` line; format undocumented |
| Health check | Agent hooks checked and repaired daily | `pblame doctor`, on demand |

---

## Engineering: copy these

Ranked by how much it hurts not to have it.

### 1. Stop depending on `post-commit` firing — **finding 20, confirmed**

Tested 16 Oct: in a repo with `core.hooksPath` set (which husky does, and husky is in a
large share of JavaScript repos), git ignores `.git/hooks`. Our `post-commit` never runs,
the receipt sits in staging forever, and **`doctor` reports "post-commit hook installed ✓
— Recording is live"**. Silent failure, the exact class this project exists to refuse.

git-ai sidesteps it by not using git hooks at all. The cheap version of their idea for us:
**attach lazily.** Every `UserPromptSubmit`, every `Stop`, and every pblame command already
runs in the repo; each can check whether HEAD moved since staging and attach then.
`post-commit` becomes an optimisation instead of a dependency. `doctor` must detect
`core.hooksPath` regardless. *Do not* install into `.husky/` — that directory is committed,
and our hook embeds an absolute path to the local binary.

### 2. Server-side squash-merge — blocks Phase 2

GitHub's **Squash and merge** button creates a new commit on GitHub's servers. No local
hook sees it, so every prompt on the PR's commits is orphaned the moment it merges. Most
teams squash-merge. git-ai ships an open-source CI action for exactly this. We need one
before the PR surface means anything: on `push` to main, find the PR's original commits
(GitHub's API lists them), union their notes onto the squash commit, push the notes.

### 3. Per-tool-call checkpoints

They checkpoint after every tool call; we diff the whole turn. Ours misattributes any
line *you* type in the editor while Claude is working — it lands inside the turn's diff and
gets the prompt's name on it. Claude Code has a `PostToolUse` hook; snapshotting there
narrows each receipt to what the agent's own edits touched. More snapshots per prompt, so
cost goes up — measure before committing to it.

### 4. A stats line and `pblame stats`

`you ██░░ ai — 6% / 94%` on every commit is the most quoted thing in their README. It is
cheap for us: lines attributed vs not, per commit. It is also the one feature that answers
*their* buyer's question, so it costs us nothing to have the number while leading with ours.

### 5. Rewrites we miss: cherry-pick, `reset --soft`, stash

`post-rewrite` fires for amend and rebase only. **Cherry-pick** loses attribution today.
So does the common squash-by-hand, `git reset --soft HEAD~3 && git commit`. Their spec's
rewrite section is a good checklist; their answer is a daemon, ours could be the lazy
attach from item 1 plus `reflog` inspection.

### 6. Publish the note format as a spec

They have a versioned standard with requirement levels and an errata section (including
admitting a typo became canonical). We have a version line and nothing documenting it.
Writing ours down is a day, and it is also the honest answer to "what if pblame
disappears" — your data is a documented format in your own repo.

### 7. Accepted vs overridden lines

Already in our backlog, from blameprompt. git-ai having it confirms the demand.

### 8. Global install

`pblame init` per repo is friction. Claude Code hooks can live in `~/.claude/settings.json`
and record wherever a session runs. Depends on item 1, because global *git* hooks would
need `core.hooksPath` — which is the thing that breaks us.

## Engineering: deliberately do not copy

- **Prompts outside git.** It is their lean-repo and access-control answer, and it is why
  their open-source version cannot show a teammate the prompt. Ours travelling in git,
  redacted, is the differentiator. Keep it.
- **A background daemon.** Correct for 14 agents and every git operation; heavy for one
  agent and a Python tool. Lazy attach gets most of the benefit with no process to manage.
- **Their note format, as our primary.** Interop is worth considering — *reading*
  `refs/notes/ai` so `pblame blame` shows git-ai's attribution where ours is missing — but
  their format cannot hold prompt text, so it cannot be our format. Revisit if their
  standard is adopted by Codex.

---

## Marketing: copy these

### The README skeleton

Their order, adapted:

1. **Name and one sentence.** What it is, in words a stranger understands.
2. **A one-line promise, then real output.** *"Just prompt and commit — no workflow
   changes"*, followed by a text block of actual terminal output. **Text, not a GIF**, in
   the README: it renders everywhere, is searchable, and loads instantly. The video lives
   on the site.
3. **Install.** Two one-liners. Ours cannot be one line yet; say exactly what it is.
4. **"Our Choices".** Five principles, one line each. This is the section that converts a
   skeptic, because it answers *why should I trust this* before it is asked.
5. **The two or three things it does**, each with its command and real output.
6. **FAQ** that answers the objections out loud: performance, rewrites, hooks, privacy,
   what happens if I stop using it.
7. **A capabilities table with honest ✗ rows.** Their limitations list (`git mv`,
   `filter-repo`) builds more trust than any claim above it. Copy the honesty, not just
   the table.
8. **License.**

### Phrases worth the pattern

- *"No workflow changes"* — true of us too, and the first objection anyone has.
- *"Local-first"*, *"Git native"* — true of us, and more true: no prompt store at all.
- A large single measured number. Theirs is `+0ms`. Ours would be the measured snapshot
  cost — **which is not zero, so say what it is.** `~160ms per prompt, measured on your
  repo by pblame doctor` is a stronger claim than a round number, because it is checkable.

## Marketing: do not copy

- **The 14-logo agent row.** We support Claude Code. Say so plainly; a row of one logo
  reads as honest, a padded row reads as a lie the first time someone tries Cursor.
- **"No git hooks."** We use them. Until item 1 lands, our FAQ should say so and say what
  breaks them.
- **Teams / early-access / book-a-demo CTAs.** There is no Teams. The ask is to try it and
  report back.
- **Leading with measurement.** That is their ground and now Codex's. Lead with intent.

---

## What this changes in the site and README

- **Hero copy leads with the decision-vs-shrug idea**, not "the prompt behind every line"
  — that line is no longer ours alone.
- **The three feature clips pick the three things git-ai does not do:**
  1. **The prompt travels, the secrets don't** — a teammate pulls and sees your prompt,
     redacted, with no server. git-ai's open-source version cannot show this at all.
  2. **Search every instruction** — no equivalent found.
  3. **Survives history rewrites** — parity, not difference, but the first question any
     engineer asks, and the one that makes the rest credible.
- **The README follows the skeleton above**, with an honest capabilities table that
  includes finding 20 until it is fixed.

## Recommended engineering order, after the site ships

1. Finding 20 — lazy attach + `doctor` detects `core.hooksPath`. Silent failure; first.
2. Squash-merge CI action — prerequisite for Phase 2 meaning anything.
3. Stats line — cheap, quotable, answers the other buyer's question.
4. Cherry-pick / `reset --soft` coverage — falls out of 1.
5. Spec document.
6. Per-tool-call checkpoints, after measuring the cost.

Sources: [git-ai on GitHub](https://github.com/git-ai-project/git-ai) ·
[git-ai standard v3.0.0](https://github.com/git-ai-project/git-ai/blob/main/specs/git_ai_standard_v3.0.0.md) ·
[usegitai.com docs](https://usegitai.com/docs) ·
[The New Stack: OpenAI hires Git AI](https://thenewstack.io/openai-hires-git-ai/) ·
[aicatchup on the hire](https://aicatchup.com/news/openai-welcomes-git-ai-agent-attribution)
