# Day 6b — the demo recording: `envdiff`

> **Status: scheduled, never run.** Still the only planned artifact to show anyone,
> and still blocked on nothing but doing it. Run after
> [day 7](day7-dummy-clock-phase13.md).

A CLI that compares two `.env` files and reports what's missing, extra or changed —
**without printing secret values**. Chosen because a reviewer understands it in one
sentence, it fits in two short files you can read on one screen, and its security
behaviour gives the demo its argument.

Unlike [day 6a](day6-a-dummy-clock-validation.md), this run is **not** trying to break
anything. Prompt as you normally would; the shape below just guarantees the story lands.

## Setup

```
mkdir C:\Users\subCl\Documents\Fun_stuff\apps\envdiff
cd C:\Users\subCl\Documents\Fun_stuff\apps\envdiff
git init -b main
C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe init .
```

Then open that folder as its own Claude Code session. `PB` below = that same exe path.

**Before prompt 1, and again around prompt 5, run:**

```
PB doctor
```

It must say *Recording is live*. This is the whole point of having it: the day-5
run lost 26 minutes to a recorder that had silently stopped, and nothing on screen
said so. Two seconds here beats discovering it at prompt 20.

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

```
git add -A && git commit -m "envdiff: compare two .env files"
PB show HEAD     # expect 4 receipts
```

## Phase 2 — parsing edge cases (prompts 5–8) → commit

5. `Handle comments (#), blank lines, and inline "export KEY=value" syntax in load_env.`
6. `Handle values wrapped in single or double quotes, stripping the quotes but preserving any inside them.`
7. `What should happen if the same key appears twice in one file?` ← *question only, no edits; should leave no receipt*
8. `If a key is duplicated, keep the last occurrence and collect a warning; print warnings to stderr after the report.`

```
git add -A && git commit -m "envdiff: parsing edge cases"
```

## Phase 3 — the security thread (prompts 9–12) → commit

9. `this thing handles secrets, make it safer` ← **the vague one. Do not clarify it.**
10. `Add a --json flag that emits the same report as machine-readable JSON.`
11. `Set the exit code to 1 when there are any differences and 0 when the files match, so it can gate CI.`
12. `In the human-readable report never print a value. For a changed key print only the key name and the character lengths of the old and new values. For missing or extra keys print the key name alone. Add a --show-values flag that opts out of this, and have it print a warning to stderr when used.`

```
git add -A && git commit -m "envdiff: redaction, json output, exit codes"
PB blame envdiff.py     # <- check the contrast is visible here
```

## Phase 4 — refactor, delete, rename (prompts 13–16) → two commits

13. `Rename parse.py to envfile.py and update the import.`
14. `Remove the --show-values flag and everything that supported it. It is a footgun.` ← *deletion-only*
15. **Manual edit first:** open `envdiff.py` yourself and add a comment line at the top, save. Then prompt: `Add a --quiet flag that suppresses the headings and prints one key per line.`
16. `Extract the report rendering into a render_report function.`

Commit **only** `envfile.py` first, then the rest:

```
git add envfile.py && git commit -m "envdiff: rename parse module"
git add -A && git commit -m "envdiff: quiet mode, drop --show-values"
```

## Phase 5 — tests and finish (prompts 17–20) → commit

17. `Write tests/test_envfile.py covering comments, quotes, duplicate keys and export syntax.`
18. `Write tests/test_envdiff.py covering missing, extra, changed and identical files, including the exit codes.`
19. `Write a README with a one-line description, install steps, and one example of the output.`
20. `make it feel more finished` ← *vague, final*

```
git add -A && git commit -m "envdiff: tests and README"
```

---

## When you're done

```
PB blame envdiff.py
PB blame envfile.py
PB show HEAD
git log --oneline
cat .git/pblame/hook.log        # must be empty
```

I'll go through the output and pick the exact file and screen region to open the demo on.

## Notes

- If a prompt produces something you dislike, **say so in a follow-up prompt** rather than
  hand-editing. Corrections are good demo material — they show a prompt trail, which is
  the product.
- Prompt 15's manual edit is deliberate: it should appear as unattributed next to
  attributed lines.
- Don't tidy history at the end. The commits are the demo.
