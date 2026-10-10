# Day 9 — verifying the day-8 fixes on the real dummy_clock

**Run by me, on the terminal, 10 Oct 2026.** Every day-8 fix is about sharing, config
reading or reporting — none of them needs a prompt to be recorded — so for the first time
the whole verification could run without a Claude Code session. That is why this one is
mine rather than yours.

**Verdict: all six day-8 fixes hold on real history, and the run found three more bugs —
17, 18 and 19 — all now fixed. Finding 19 is a secret leak and the most important thing
in this document.**

`dummy_clock` was backed up to `dummy_clock.day9backup` first and restored exactly
afterwards: same verbatim notes ref (`ffff64d`), same HEAD (`6445008`), clean working
tree, only `refs/notes/pblame` left, `doctor` healthy.

The only thing a script cannot do is record a prompt, so the teammate's prompt in step 3
was written with [tools/forge_receipt.py](../tools/forge_receipt.py), which builds the same
`Receipt` the recorder builds and writes it to the local ref. Everything else is the real
commands. `$forge` below is that script's path.

---

## The script

```powershell
Set-Alias pblame "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location C:\Users\subCl\Documents\Fun_stuff\apps
```

### 0 — stage

```powershell
git init -q --bare clock_remote.git
cd dummy_clock ; git remote add origin ..\clock_remote.git ; git push -q origin main
pblame share ; pblame push ; pblame doctor
```

### 1 — finding 9: a BOM must not make a config unreadable

```powershell
'{ "redaction": { "custom_patterns": [ { "pattern": "succinct", "replacement": "[TERSE]" } ] } }' |
  Out-File -Encoding utf8 .pblame.json      # PowerShell 5.1 always writes a BOM here
Format-Hex .pblame.json | Select-Object -First 1
pblame push --dry-run | Select-String "TERSE"
pblame doctor | Select-String "config|secrets"
```

### 2 — finding 13: count changed prompts, not prompts in changed notes

```powershell
pblame push        # "succinct" is in 2 prompts, which live in notes holding 5 receipts
```

### 3 — findings 12 + 15: a rejected push, with a teammate

```powershell
cd .. ; git clone -q clock_remote.git mate ; cd mate
git config user.email mate@e.com ; git config user.name mate
pblame init . ; pblame share ; pblame pull
python $forge . "make the duck blink every ten seconds" index.html
pblame push                                  # mate gets there first

cd ..\dummy_clock
# add a second rule so we have something of our own to contribute
pblame push                                  # rejected -> pull -> re-plan -> retry
pblame search "blink" --limit 3              # mate's prompt must still be there
```

### 4 — finding 17: the secret count

```powershell
# a third rule, touching one prompt in a note whose other two are already redacted
pblame push
pblame push --dry-run | Select-Object -Last 3
```

### 5 — the doctor mirror check, on a commit nothing else references

```powershell
cd ..\mate
git -c core.hooksPath=.git/nohooks commit -q -m "mate: a local-only commit"
python $forge . "add a local-only helper" matelocal.js
pblame push ; pblame doctor | Select-String "shared mirror"
git -c core.hooksPath=.git/nohooks commit -q --amend -m "rewritten, hooks bypassed"
pblame doctor | Select-String "shared mirror"
```

### 6 — the no-op push message, in an empty repo

```powershell
pblame push                                  # with nothing recorded
git push origin main                         # the hook must stay silent
```

### 7 — regression: the core features on real data

```powershell
cd ..\dummy_clock
pblame blame time.js --no-color
pblame search --path .\styles.css --limit 2
pblame show HEAD
```

### 8 — restore

```powershell
Remove-Item .pblame.json
git remote remove origin ; pblame share --off
git update-ref -d refs/notes/pblame-shared ; git update-ref -d refs/notes/pblame-remote
cd .. ; Remove-Item -Recurse -Force mate, clock_remote.git, emptyrepo, emptyremote.git
```

---

## Results

| Fix | Expected | Observed |
|---|---|---|
| **9** BOM | config readable | `EF BB BF` confirmed in the file; `--dry-run` previewed both `[TERSE]` prompts; `doctor` reported no config error |
| **13** changed count | 2, not 5 | *"Shared 2 new prompts to origin (29 total) / 2 secrets redacted"*. Measured independently first: 2 notes differed, holding 5 receipts, of which 2 changed |
| **12** rejected push | reports what it shared | *"Shared 1 new prompt to origin (30 total)"* on the retry — not *"Already shared"* |
| **15** total on origin | includes the teammate's | mate's own first push said *"(30 total)"*, i.e. 29 inherited plus its own, where it used to say *"(1 total)"* |
| **14** pull reporting | what arrived, then coverage | *"Pulled 29 new prompts from origin / shared history 14 commits"* |
| **17** secret count | 1, not 3 | *"1 new prompt, 1 secret redacted"* for a prompt whose note holds two already-redacted neighbours; `--dry-run` still reports the whole payload's *"4 secrets redacted"* |
| no-op push | says nothing is recorded | *"Nothing recorded yet, so nothing to share"*, and silent inside `git push` |
| **10** doctor, mirror | warns on a dead note | clean before, *"1 of 15 notes point at commits a rewrite left behind (4fc2d70)"* after |
| regression | blame, search, show | `time.js` still attributed across the `clock.js` rename; `--path .\styles.css` matched; `show HEAD` lists our prompt and the teammate's |

**The redaction boundary held.** After the pushes, the local record still read `succinct`
and `aesthetic` twice and never once contained a replacement token; the mirror was the
exact inverse. That is the whole safety model in one measurement.

## What the run found

### 17. "N secrets redacted" counted the note's secrets, not the prompt's — **fixed**

Finding 13's sibling, and I missed it when fixing 13. A push that re-redacted one prompt
on `5eadbb5` reported **2 secrets** because that note also held a prompt whose secret had
been redacted on an earlier push. `plan` now keeps each detection paired with the receipt
it came from, and the push report counts only the receipts it is sending. The `--dry-run`
preview still counts everything, which is correct for a preview of the whole payload.

### 18. `doctor` only looked for dead notes in the mirror — **fixed**

The mirror check shipped first, but `refs/notes/pblame` has the same rot and it matters
more, because that ref is the only copy of those prompts. `dummy_clock` has one:

```
! recorded history   14 commits carry recorded prompts, 1 of them no longer in history (8b731e5)
```

That is **"Delete date.js and fold its logic back into clock.js."**, attributed to a commit
a day-7 or day-8 rewrite dropped. It has been invisible this whole time. Now folded into
the existing `recorded history` line rather than added as a second warning.

This also revises the prune design: it said *"never touch `refs/notes/pblame`, an orphan
there is a remap bug"*. True, but one exists anyway, so the verbatim ref needs the same
answer eventually — and there the stakes are higher, since nothing can re-derive it.

### 19. Every prefixed secret key escaped redaction — **fixed, and the worst of the three**

Not found by the script. Found while picking secret strings to put in the demo prompts,
by checking what actually fires instead of assuming:

```
'DATABASE_PASSWORD=hunter2correct'  ->  'DATABASE_PASSWORD=hunter2correct'   []
'password=hunter2correct'           ->  'password=[REDACTED_PASSWORD]'       ['PASSWORD']
```

**Reason.** The `PASSWORD` and `TOKEN` rules began with `\b`, and `_` is a word
character, so the boundary **cannot match inside `DATABASE_PASSWORD`**. Only a bare
`password=` was ever caught — which is not how any `.env`, environment variable or config
key is named. `CLIENT_SECRET`, `DB_PASSWORD`, `MYSQL_PWD`, `SESSION_TOKEN`,
`STRIPE_API_KEY`: all of them went to a remote in the clear.

`SESSION_TOKEN=<high entropy>` happened to be caught by the entropy fallback, but that
replaces the *whole* token including the key name, so even the lucky case lost
information the design promises to keep.

**Fixed** by replacing `\b` with `(?<![A-Za-z0-9])`, which allows an underscore prefix
while still refusing mid-word matches — `oauth=` must not read as `auth=`. Seven new
parametrised cases, all failing before the change, plus a guard that the prefix
allowance did not open the door to mid-word false positives.

**Why this one matters more than the rest of this document.** Everything else here was a
wrong number on a screen. This sent secrets to a remote while reporting *"0 secrets
redacted"* — the exact failure the redaction boundary exists to prevent, and the one the
demo was about to claim on camera. 219 tests passed over it; the only reason it surfaced
is that I went to check a pattern by hand instead of trusting the table.

## Two things I got wrong, not the code

- **`search` reports 20 prompts, so I thought the mirror's 29 was wrong.** `search`'s
  `--limit` defaults to 20. There are genuinely 29 recorded prompts across 14 commits.
- **The first orphan test did not warn, and that was correct.** I amended a commit that
  `refs/remotes/origin/main` still pointed at, so it was not dead — it was still on the
  remote. The check refusing to call that dead is the conservatism it was built for. A
  commit that genuinely nothing references does get flagged.

## State afterwards

`dummy_clock` is byte-for-byte where it started, bar the one thing worth keeping: nothing.
No new commits, no moved refs, no config left behind. `dummy_clock.day9backup` can be
deleted whenever you like; `dummy_clock.backup` from day 7 is older and still there.
