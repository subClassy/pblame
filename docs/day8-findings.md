# Day 8 findings — verifying the fixes

From [day8-fix-verification.md](day8-fix-verification.md), steps 0-9 complete.
Numbering continues from [day7-findings.md](day7-findings.md).

**Status: five fixed, one needs no fix, one open by decision.** Findings 9, 12, 13, 15 and
14's reporting half are fixed on `fix/day8-findings`, each with a regression. 11 needs no
code. 10 and the rest of 14 are one bug whose fix deletes data, so `doctor` now reports it
and the removal is yours to call — see [the prune decision](#the-prune-decision) at the
bottom. Finding 15 was not in your run; it only shows up with a second author.

## All seven fixes verified

| Fix | Evidence |
|---|---|
| **5** no-op push | `0.477s`, *"Already shared, 28 prompts"*, mirror ref unchanged |
| **5** retroactive redaction | a `duck` → `[BIRD]` rule appeared in `--dry-run`, pushed as new with *"3 secrets redacted"*, ref moved; removing the rule reverted it and moved the ref again |
| **2** redirected output | `Select-String -Pattern "—"` matched, `Format-Hex` showed `E2 80 94`, and the 🕐 survived the round trip |
| **1** `--path` | all five shell forms matched: bare, `.\`, `./`, uppercase, glob |
| **4** blank lines | **0** bare-blank groups rendered, **7** blank lines still carrying a prompt in `--json` — rendering cleaned, data intact |
| **6** rewrite | amend: both refs empty on the old sha, both present on the new. Squash: *"carried 1 prompt"* twice and `show HEAD` lists **both** commits' prompts with their files |
| **3** refusal | names `pblame share`, not the committed config |
| **7** purge | all three refs deleted, `search` finds nothing, `git log` and the working tree untouched — and `refs/notes/commits` from another tool survived |
| **8** cleanup | ran clean; only `refs/notes/pblame` left behind, `doctor` still healthy |

Phase 1 and 3 are now exercised end to end on real history, across two repos, with the
hooks firing rather than explicit commands.

## Confirmed bugs

### 9. A UTF-8 BOM makes any config unreadable — **fixed**

```
✗ cannot read ...\.pblame.json: Unexpected UTF-8 BOM (decode using utf-8-sig)
```

**Not your mistake — the script's.** `Out-File -Encoding utf8` in PowerShell 5.1 *always*
writes a BOM, and so does Notepad. Every config we read uses `encoding="utf-8"`, which
rejects one.

**Reason.** `config._read` and the settings readers in `adapters/claude_code.py`,
`doctor.py` and `cmd_share` all use plain `utf-8`. Our own writes never emit a BOM, so this
only bites files a human or a shell created — which is every file we ask people to edit:
`.pblame.json`, `.pblame.local.json`, `.claude/settings.json`, `.claude/settings.local.json`.

**Fixed** in `2e77ec9`. Every read of a user-editable file now uses `config.USER_TEXT`
(`utf-8-sig`), which strips a BOM when present and is identical to `utf-8` when absent:
both configs, both Claude Code settings files, the git hooks, the ignore file, the hook
log. Writes stay plain `utf-8` — we never emit a BOM, and that is what makes a rewritten
git hook come out with its shebang first instead of behind a BOM `sh` will not honour.

Six regressions in `tests/test_day8_fixes.py`; five of them fail without the fix, and the
sixth is the no-BOM control that must keep passing.

**The script also needs fixing**, since it is what produced the BOM. In PowerShell 5.1 the
BOM-free forms are `[IO.File]::WriteAllText($path, $json)` or, for ASCII JSON,
`Set-Content -Encoding ascii`.

### 10. The mirror keeps notes for commits that no longer exist — **open by decision**

dummy_clock's mirror covers 16 commits while the local record covers 14:

```
0569c910  commit   unreachable   "Replace the duck with a 8 bit duck format"
e1fe23f5  missing  unreachable   "Change the font to more nerdy one"
```

`0569c910` is the pre-amend commit from day 7, orphaned in the mirror by finding 6 before
it was fixed. `e1fe23f5` is the teammate's commit — its object was never in this repo and
the clone that had it is deleted.

**Reason.** Fix 6 stops *new* orphans but collects no existing ones, and nothing else
prunes the mirror. It grows by one entry per rewritten commit, forever.

**Why this is not a one-line fix.** "The commit object is missing locally" is *not* proof
the commit is dead — a teammate may have it, and that is exactly the normal state for
shared notes, as `e1fe23f5` shows. Dropping anything whose object we lack would delete
teammates' work.

**What shipped** (`58b6c59`): `snapshot.unreachable` answers the only safe question — which
of these commits are *here* and reachable from no ref, the ones git would drop at the next
`gc` — and `doctor` reports the count as a warning:

```
! shared mirror          1 of 4 notes point at commits a rewrite left behind (cd77e20)
```

That turns invisible rot into a number, without deleting anything. The removal itself is
[the prune decision](#the-prune-decision).

Harmless today: `blame` never looks up a commit it cannot see, and `search` shows the
teammate's prompt as `(shared)`, which is arguably correct.

### 11. The mirror's own history is 86 commits deep for 28 prompts — **no fix needed**

`git rev-list --count refs/notes/pblame-shared` → 86.

**Reason.** Accumulated churn from day 7's pushes, each of which rewrote every note before
finding 5 was fixed. Growth has stopped; the depth remains.

**Fix.** Nothing urgent — `git gc` packs it and it costs no correctness. Worth knowing that
the fix stopped the bleeding without healing the scar, and that a repo tested before the fix
carries it.

### 12. A rejected push reports "Already shared" when it did share — **fixed**

From step 7. dummy_clock had just recorded a prompt, yet:

```
pblame push   ->  Already shared, 29 prompts on origin
```

The prompt *was* shared — `mate` pulled and saw it. Only the message is wrong.

**Reason.** Mine, and a direct consequence of the regression fix. `push` re-plans after a
rejection so the retry does not write stale lists, then returns that second plan. By then
the first attempt's `stage` has already written the new note, so the re-plan sees it in the
mirror and marks everything `is_new=False`. The caller computes `new == 0` and says
"Already shared".

**Fixed** in `c158148`. The re-plan is for staging only; the report comes from the first
plan, which is what this push contributed, measured before it ran.

Proved by reverting just the `return`: with the old line the new regression fails with the
prompt missing from what the push claims to have shared. Confirmed by hand too — the retry
now says *"Shared 1 new prompt to origin (3 total)"*.

### 13. "N new prompts" counts prompts in changed notes, not changed prompts — **fixed**

Step 1: a rule affecting the word `duck` touched two prompts, and the message said
**4 new prompts** with 3 secrets redacted. The 3 was right (the word appears three times);
the 4 is every receipt living in the two notes that changed, not the two that changed.

**Reason.** `sum(len(item.receipts) for item in fresh)` counts a whole note when any part
of it differs.

**Fixed** in `c158148`. `Planned` gained a `changed` list — the receipts whose
serialisation differs from the mirror's copy of the same prompt. `is_new` still decides
whether to write the note; `changed` is what gets reported.

### 14. Dead notes propagate to teammates and make the totals disagree — **reporting fixed**

`mate` — a fresh clone that never had the pre-amend commit — showed:

```
0569c91  2026-10-09 01:57  claude-opus-5  (shared)
  Replace the duck with a 8 bit duck format
```

And the two repos disagreed on how many prompts exist: dummy_clock *"6 of 31"*, mate
*"3 of 32"*.

**Reason.** Finding 10's consequence rather than a separate bug. The mirror carries notes
for commits that no longer exist, those notes travel on push, and every clone inherits
them. Because `index.load` dedups by prompt id and the live and dead copies of a prompt sit
on different commits, the count each repo reports depends on which copies it happens to
hold.

It also answers *"why does `pull` say 17 commits?"* — that number is how many commits the
**mirror** has notes for, not how many arrived: 14 real, plus mate's new one, plus the two
dead ones. Accurate, but inflated by entries that will never match a commit again.

**Fixed** in `c158148`, the reporting half. `pull` now returns both numbers and leads with
the one you asked for:

```
✓ Pulled 2 new prompts from origin
  shared history       2 commits
```

and, when nothing arrived, *"Up to date"* with the coverage underneath. The disagreeing
totals are the data half, and they need [the prune](#the-prune-decision).

### 15. "N prompts on origin" counted only our own — **fixed**

Found while smoke-testing finding 12, not in your run, because dummy_clock has one author
and there the two numbers coincide. With a teammate they do not:

```
bob:  Shared 1 new prompt to origin (1 total)     # origin held 3
```

**Reason.** `total` summed our planned receipts. Our local record holds only our prompts,
so the total was "mine in the mirror" wearing the label "on origin".

**Fixed.** `share.shared_total` counts distinct prompts in the mirror, which is what "on
origin" means. The `--dry-run` preview still counts ours, correctly — it is a preview of
what *we* would send.

Same family, same commit: a push in a repo with nothing recorded said *"Already shared, 0
prompts on origin"*. It now says nothing is recorded, and says nothing at all when it runs
inside `git push`.

## The prune decision

Findings 10 and 14's data half need notes deleted. The design is settled; whether to build
it is not, and the honest answer is **not yet**.

**The rule.** Remove a *mirror* entry when the commit is present locally and reachable from
no ref. Keep it when the object is missing — a commit we never fetched is the normal state
for a shared note. Never touch `refs/notes/pblame`: that is the verbatim source of truth,
and an orphan there is a remap bug, which `rewrite` and `repair` already handle.

**Why that rule is safe where a naive one is not.** The mirror is *derived*: `plan` rebuilds
our half of it from the local record on every push. Pruning our own entry is self-healing —
if the commit comes back, the next push re-stages it. The only irrecoverable loss is a
teammate's entry on a commit we have but nothing points at, which is a prompt about code
that no longer exists.

**Two things that argue for waiting.**

- With 9, 12, 13, 14-reporting and 15 fixed, the remaining harm is cosmetic: a phantom
  `search` hit and two repos disagreeing on "N of M". No data is lost or wrong.
- Growth already stopped. Fix 6 was the source, and dummy_clock's two entries both predate
  it. `doctor` will now say if that is ever untrue again.

**And one false positive I could not design away.** Fetch a teammate's branch, have every
ref to it disappear locally (remote-tracking ref pruned, branch deleted) while the branch
is still alive for them, and prune deletes their notes for it. Self-healing — their next
push restores them — but it is churn caused by a cleanup nobody asked for, and since a
deletion propagates, it is churn every clone sees.

**One thing that argues for building it: a deletion does propagate.** I had assumed a
union merge could not express one, which would have made prune purely local and left every
clone with its own junk forever. Tested directly, on plain git notes, and it is not so:

- clone strictly behind → fast-forward, note gone.
- clone with its own unpushed notes commit → three-way merge against the base, the
  one-sided deletion still wins (3 notes before, 2 after).

So one repo that *can* see a commit is dead prunes it, and everyone else converges on the
next pull — which matters because the clone in finding 14 is missing the object and could
never have decided that for itself. Nor does pblame re-add it: `plan` only stages notes it
has a local receipt for, and a mirror-only orphan has none.

**Trigger to build it:** `doctor` reporting dead notes in double figures, or a real
complaint about a phantom prompt. Until then the warning is the whole fix — but the
blocker is appetite for an irreversible delete, not the mechanics.

## Closed

- **`claude-opus-5-5` and `claude-sonnet-5-5` are genuine.** Counted directly in the
  transcripts: 326 `claude-opus-5`, 232 `claude-sonnet-5`, 11 `claude-sonnet-5-5`, 10
  `claude-opus-5-5`. We read the field faithfully; nothing to fix.
- **An absolute `--path` does not match, and will not be fixed.** Decided: nobody would type
  it. Revisit only if it becomes a noticed problem.

## Working as intended, worth recording

- **A broken config fails closed on sharing and open on recording.** `push` and
  `push --dry-run` both refused while `.pblame.json` was unreadable, and the mirror ref did
  not move. Recording, by contrast, would have continued with default redaction
  (`_scan_secrets` swallows `ConfigError`). That asymmetry is deliberate — recording must
  never stop, sharing must never proceed under rules nobody can read — and this run
  demonstrated it by accident. `doctor` also reports the unreadable config as a failure.
