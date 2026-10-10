# The demo build: `envdiff`

> **Status: ready to run.** Everything it depends on is built, merged and verified on
> real history ([day 9](day9-fix-verification.md)). This document is the *build* — the
> 20 prompts that create the subject. [The recording manual](demo-recording-manual.md)
> is the separate document for actually capturing it.

A CLI that compares two `.env` files and reports what's missing, extra or changed —
**without printing secret values**. Chosen because a reviewer understands it in one
sentence, it fits in two short files you can read on one screen, and its security
behaviour gives the demo its argument.

Unlike [day 6a](day6-a-dummy-clock-validation.md), this run is **not** trying to break
anything. Prompt as you normally would; the shape below just guarantees the story lands.

**Budget:** the 20 prompts are roughly 60–90 minutes of normal working pace. If you want
to cut it short, [the minimum viable build](#if-you-want-to-cut-it-short) at the bottom
gets you the central moment in 12.

## Setup

```powershell
mkdir C:\Users\subCl\Documents\Fun_stuff\apps\envdiff
cd C:\Users\subCl\Documents\Fun_stuff\apps\envdiff
git init -b main
C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe init .
```

Then open that folder as its own Claude Code session. `PB` below = that same exe path;
set `Set-Alias pblame <that path>` in the terminal you run checks from.

**Before prompt 1, and again around prompt 10, run:**

```powershell
pblame doctor
```

It must say *Recording is live*. This is the whole point of having it: the day-5 run
lost 26 minutes to a recorder that had silently stopped, and nothing on screen said so.
Two seconds here beats discovering it at prompt 20.

## The demo moment this is built around

Two prompts touch the same security behaviour:

- **#9 is deliberately vague** — "make it safer"
- **#12 is deliberately precise** — an exact redaction rule

In the final `pblame blame`, their lines sit near each other. The pitch, out loud:

> *"This line redacts secrets. Who decided that, and what exactly did they ask for?
> `git blame` says Himank, Tuesday. `pblame` says nobody decided — someone typed
> 'make it safer' and shipped whatever came back. The line four rows down came from a
> prompt that specified the rule exactly. Same author, same commit, same review. Only
> one of them was actually a decision."*

Everything else exists to make that moment readable.

---

## Phase 1 — core (prompts 1–4) → commit

1. `Write envdiff.py: a CLI that takes two .env file paths and prints which keys are only in the first, only in the second, and which have different values. Plain stdlib, no dependencies.`
2. `Move the .env parsing into parse.py as a function load_env(path) -> dict[str, str].`
3. `Sort the output by key name and group it under three headings: Missing, Extra, Changed.`
4. `make the output easier to scan` ← *vague on purpose, cosmetic stakes*

```powershell
git add -A ; git commit -m "envdiff: compare two .env files"
pblame show HEAD     # expect 4 receipts
```

## Phase 2 — parsing edge cases (prompts 5–8) → commit

5. `Handle comments (#), blank lines, and inline "export KEY=value" syntax in load_env.`
6. `Handle values wrapped in single or double quotes, stripping the quotes but preserving any inside them.`
7. `What should happen if the same key appears twice in one file?` ← *question only, no edits; should leave no receipt*
8. `If a key is duplicated, keep the last occurrence and collect a warning; print warnings to stderr after the report.`

```powershell
git add -A ; git commit -m "envdiff: parsing edge cases"
```

## Phase 3 — the security thread (prompts 9–13) → commit

**This is the phase the demo is about. Do not improvise here.**

9. `this thing handles secrets, make it safer` ← **the vague one. Do not clarify it.**
10. `Add a --json flag that emits the same report as machine-readable JSON.`
11. `Set the exit code to 1 when there are any differences and 0 when the files match, so it can gate CI.`
12. `In the human-readable report never print a value. For a changed key print only the key name and the character lengths of the old and new values. For missing or extra keys print the key name alone. Add a --show-values flag that opts out of this, and have it print a warning to stderr when used.`
13. **Paste this one verbatim — it puts real-looking secrets in the record on purpose:**

```
Add tests/fixtures/prod.env and tests/fixtures/staging.env as test data. prod.env should contain:
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
DATABASE_PASSWORD=hunter2correct
CLIENT_SECRET=abc123def456ghi789
ADMIN_EMAIL=ops@acme.io
staging.env should have the same keys with different values, plus one extra key and one missing key.
```

Prompt 13 exists so the record contains secrets. That is what makes the sharing beat
real rather than hypothetical: you can show `doctor` reporting them and `push --dry-run`
removing them. `AKIAIOSFODNN7EXAMPLE` is AWS's own documentation example key, so nothing
here is a live credential.

```powershell
git add -A ; git commit -m "envdiff: redaction, json output, exit codes"
pblame blame envdiff.py     # <- check the contrast from #9 vs #12 is visible here
```

## Phase 4 — refactor, delete, rename (prompts 14–17) → two commits

14. `Rename parse.py to envfile.py and update the import.`
15. `Remove the --show-values flag and everything that supported it. It is a footgun.` ← *deletion-only*
16. **Manual edit first:** open `envdiff.py` yourself and add a comment line at the top, save. Then prompt: `Add a --quiet flag that suppresses the headings and prints one key per line.`
17. `Extract the report rendering into a render_report function.`

Commit **only** `envfile.py` first, then the rest:

```powershell
git add envfile.py ; git commit -m "envdiff: rename parse module"
git add -A ; git commit -m "envdiff: quiet mode, drop --show-values"
```

## Phase 5 — tests and finish (prompts 18–20) → commit

18. `Write tests/test_envfile.py covering comments, quotes, duplicate keys and export syntax.`
19. `Write a README with a one-line description, install steps, and one example of the output.`
20. `make it feel more finished` ← *vague, final*

```powershell
git add -A ; git commit -m "envdiff: tests and README"
```

---

## Phase 6 — the review surface (no prompts, these are demo beats)

New since this document was first written: sharing, redaction and search are all built
and verified. These commands need no prompting, so run them once to confirm the output
is worth filming, then again on camera.

### The prompt library

```powershell
pblame search "secret"
pblame search --path envfile.py
pblame search "make it" --limit 5        # finds both vague prompts
pblame search --since 1d --json | ConvertFrom-Json | Select-Object count
```

The beat: *"every instruction anyone gave this codebase, searchable. Not the diff — the
intent."* `search "make it"` returning the two vague prompts is the quiet joke.

### Secrets, and the machine boundary

```powershell
pblame doctor                             # expect: secrets in prompts ... AWS_KEY (worst CRITICAL)
pblame redact tests\fixtures\prod.env     # the redactor, on the fixture itself
pblame share
pblame push --dry-run --secrets-only      # needs no remote: it sends nothing
```

The beat, and it is the one an EM will actually buy: *"my prompt history has an AWS key
in it. It stays on my machine. When I share attribution with the team, the key does not
go — and the record still says a key was removed here, which is itself useful."*

Then turn it back off so nothing is half-configured on camera:

```powershell
pblame share --off
```

### Survival

```powershell
pblame blame envfile.py        # attribution followed the parse.py -> envfile.py rename
pblame show HEAD~2             # the squashed/partial commits still carry their prompts
```

## When you're done

```powershell
pblame blame envdiff.py
pblame blame envfile.py
pblame show HEAD
pblame doctor
git log --oneline
Get-Content .git\pblame\hook.log        # must be empty or absent
```

Send me that output and I'll pick the exact file and screen region to open the demo on,
and write the final narration against what actually came out rather than what I hoped
would.

## Notes

- If a prompt produces something you dislike, **say so in a follow-up prompt** rather than
  hand-editing. Corrections are good demo material — they show a prompt trail, which is
  the product.
- Prompt 16's manual edit is deliberate: it should appear as unattributed next to
  attributed lines.
- Don't tidy history at the end. The commits are the demo. In particular **do not rebase
  or amend after prompt 20** — a rewrite is handled correctly, but it is one more thing
  that can surprise us on the day.
- Prompt 7 should leave no receipt. If it does, that is a finding worth more than the
  demo — tell me.

## If you want to cut it short

The central moment needs prompts **1, 2, 3, 9, 10, 11, 12, 13, 14, 16, 18, 20** — twelve
prompts, three commits, and it still gives you: the vague-vs-precise contrast, a secret in
the record, a rename to survive, and one unattributed manual edit. Phases 2 and 4's
remaining prompts only add texture.
