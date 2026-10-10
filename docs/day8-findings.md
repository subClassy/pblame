# Day 8 findings — verifying the fixes

From [day8-fix-verification.md](day8-fix-verification.md), steps 0-9 complete. Nothing
fixed; each entry is what happened, why, and what the fix would be. Numbering continues
from [day7-findings.md](day7-findings.md).

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

### 9. A UTF-8 BOM makes any config unreadable

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

**Fix.** Read user-editable files with `encoding="utf-8-sig"`, which strips a BOM when
present and is identical to `utf-8` when absent. Verified both cases. The hook log and the
git hook files should get it too — anything a person might open in an editor.

**The script also needs fixing**, since it is what produced the BOM. In PowerShell 5.1 the
BOM-free forms are `[IO.File]::WriteAllText($path, $json)` or, for ASCII JSON,
`Set-Content -Encoding ascii`.

### 10. The mirror keeps notes for commits that no longer exist

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
teammates' work. A safe prune can only remove notes for commits that are present but
unreachable, and even then only after a `git gc` would have dropped them. Worth designing
rather than patching.

Harmless today: `blame` never looks up a commit it cannot see, and `search` shows the
teammate's prompt as `(shared)`, which is arguably correct.

### 11. The mirror's own history is 86 commits deep for 28 prompts

`git rev-list --count refs/notes/pblame-shared` → 86.

**Reason.** Accumulated churn from day 7's pushes, each of which rewrote every note before
finding 5 was fixed. Growth has stopped; the depth remains.

**Fix.** Nothing urgent — `git gc` packs it and it costs no correctness. Worth knowing that
the fix stopped the bleeding without healing the scar, and that a repo tested before the fix
carries it.

### 12. A rejected push reports "Already shared" when it did share

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

**Fix.** Report from the *first* plan and use the re-plan only for staging. The number the
developer wants is what this push contributed, measured before it ran.

### 13. "N new prompts" counts prompts in changed notes, not changed prompts

Step 1: a rule affecting the word `duck` touched two prompts, and the message said
**4 new prompts** with 3 secrets redacted. The 3 was right (the word appears three times);
the 4 is every receipt living in the two notes that changed, not the two that changed.

**Reason.** `sum(len(item.receipts) for item in fresh)` counts a whole note when any part
of it differs.

**Fix.** Count receipts whose serialisation actually changed. Needs the before-and-after
per receipt, which `plan` already has in hand.

### 14. Dead notes propagate to teammates and make the totals disagree

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

**Fix.** The prune from finding 10, which still needs designing — a missing commit object
is not proof the commit is dead.

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
