# Day 8 findings — verifying the fixes

From [day8-fix-verification.md](day8-fix-verification.md). Nothing fixed; each entry is
what happened, why, and what the fix would be. Numbering continues from
[day7-findings.md](day7-findings.md).

## Verified so far

**Fix 5 — a push only writes what changed.** Exactly as intended, on real history:

```
pblame push                    ->  Shared 4 new prompts to origin (28 total)
Measure-Command { pblame push} ->  0.477s
pblame push                    ->  Already shared, 28 prompts on origin
git rev-parse refs/notes/pblame-shared   ->  unchanged
```

The "4 new" was honest: four local notes genuinely differed from the mirror (the four
`repair` had rewritten). A read-only re-plan afterwards reports `new now: 0`. The delta
message works, the no-op is sub-second, and the ref does not move.

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

## Working as intended, worth recording

- **A broken config fails closed on sharing and open on recording.** `push` and
  `push --dry-run` both refused while `.pblame.json` was unreadable, and the mirror ref did
  not move. Recording, by contrast, would have continued with default redaction
  (`_scan_secrets` swallows `ConfigError`). That asymmetry is deliberate — recording must
  never stop, sharing must never proceed under rules nobody can read — and this run
  demonstrated it by accident. `doctor` also reports the unreadable config as a failure.
