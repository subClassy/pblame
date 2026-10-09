# Day 8 — verifying the seven fixes, brutally

Every step attacks a fix from [day7-findings.md](day7-findings.md) and tries to make it
fail. Where a fix is destructive to prove, it is proved on a **throwaway clone** so your
real history is never the thing at risk.

```powershell
Set-Alias pblame "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe"
[Console]::OutputEncoding = [Text.Encoding]::UTF8   # needed for step 2; see why there
cd C:\Users\subCl\Documents\Fun_stuff\apps
```

`dummy_clock.backup` from day 7 is still your safety net. Step 9 cleans up.

---

## 0 — set the stage

```powershell
cd dummy_clock
pblame init .
git init --bare ..\clock_remote.git
git remote add origin ..\clock_remote.git
git push origin main
pblame share
pblame push
pblame doctor
```

Note the `live snapshot` number — it should still be ~80ms. If the push took more than a
second or two for 14 commits, fix 5 regressed.

## 1 — fix 5: a push that changes nothing must do nothing

```powershell
git rev-parse refs/notes/pblame-shared        # remember this
Measure-Command { pblame push } | Select-Object TotalSeconds
pblame push
git rev-parse refs/notes/pblame-shared        # must be IDENTICAL
git rev-list --count refs/notes/pblame-shared # must not have grown
```

**Expect:** *"Already shared, N prompts on origin"*, the ref unchanged, and well under a
second. Before the fix this was 9s on 60 commits and added one notes commit per recorded
commit, every time.

### and it must still apply a *changed* redaction rule retroactively

This is the subtle half — my first attempt at fix 5 broke exactly this.

```powershell
pblame search "duck" --limit 1                      # pick a word in a real prompt
'{ "redaction": { "custom_patterns": [ { "pattern": "duck", "replacement": "[BIRD]" } ] } }' |
  Out-File -Encoding utf8 .pblame.json
pblame push --dry-run | Select-String "BIRD"        # the preview must show it
pblame push                                         # must report NEW prompts, not "already shared"
git rev-parse refs/notes/pblame-shared              # must have MOVED now
Remove-Item .pblame.json
pblame push                                         # reverts, moves again
```

**Expect:** skipping unchanged notes must not mean the mirror can never improve.

## 2 — fix 2: redirected output is UTF-8, not the Windows codepage

```powershell
pblame search "em dash" --limit 1 | Out-File -Encoding utf8 ..\enc.txt
Select-String -Path ..\enc.txt -Pattern "—"          # must MATCH
Format-Hex ..\enc.txt | Select-String "E2 80 94"     # the em dash, as UTF-8 bytes
```

**Expect:** both match. Before the fix the em dash left as cp1252 `0x97` and PowerShell
decoded it as cp437, giving `ù` — which is what your day-7 `before-search.txt` shows.

The `[Console]::OutputEncoding` line at the top is the PowerShell half: we now emit UTF-8
correctly, but PowerShell still decodes a native command's bytes using *its* setting. Try
it without that line to see the difference — the file will be wrong even though our bytes
are right.

## 3 — fix 1: `--path` takes whatever the shell produces

```powershell
pblame search --path styles.css   --limit 1
pblame search --path .\styles.css --limit 1
pblame search --path ./styles.css --limit 1
pblame search --path STYLES.CSS   --limit 1
pblame search --path "*.css"      --limit 1
pblame search --path (Resolve-Path .\styles.css).Path --limit 1   # full absolute path
```

**Expect:** the first five all find prompts. The sixth is the interesting one — an absolute
path is *not* handled, and I want to know whether you would ever type it. If yes, that is a
new finding, not a regression.

## 4 — fix 4: blank lines take no prompt header

```powershell
pblame blame time.js --no-color > ..\blame.txt
Select-String -Path ..\blame.txt -Pattern '^\s*\|\s*$' | Measure-Object | Select Count
pblame blame time.js --json | ConvertFrom-Json |
  Select-Object -Expand lines | Where-Object { $_.text -eq "" -and $_.prompt } |
  Measure-Object | Select Count
```

**Expect:** zero bare-blank groups in the rendering, but a non-zero count in the JSON —
the grouping is a display choice and must not change the data.

## 5 — fix 6: a rewrite moves *every* ref

```powershell
$old = git rev-parse HEAD
git commit --amend -m "day8: amended"
$new = git rev-parse HEAD

git notes --ref refs/notes/pblame        list $old   # empty
git notes --ref refs/notes/pblame-shared list $old   # empty  <- the fix
git notes --ref refs/notes/pblame        list $new   # has one
git notes --ref refs/notes/pblame-shared list $new   # has one
```

Then the harder one — a squash, which remaps two commits onto one:

```powershell
$env:GIT_SEQUENCE_EDITOR = '"C:/Program Files/Git/usr/bin/sed.exe" -i "2s/^pick/squash/"'
git rebase -i HEAD~2
Remove-Item Env:GIT_SEQUENCE_EDITOR
pblame show HEAD                     # receipts from BOTH commits, files reunited
git for-each-ref refs/notes/         # no stray refs
```

**Expect:** no orphaned note on either ref, and the squashed commit carrying both commits'
prompts with every file listed.

## 6 — fix 3: the refusal says the right thing

```powershell
pblame share --off
pblame push
pblame share
```

**Expect:** it names `pblame share`, not `.pblame.json` — the committed file that
deliberately *cannot* enable sharing.

## 7 — the regression I found while writing this: a rejected push must not eat a teammate's work

The one worth the most attention, because fix 5 caused it and only a contrived test caught
it.

```powershell
cd ..
git clone clock_remote.git mate
cd mate
git config user.email mate@e.com ; git config user.name mate
pblame init . ; pblame share ; pblame pull
```

Now, **in a Claude Code session inside `mate`**, record one prompt and commit it, then:

```powershell
pblame push
cd ..\dummy_clock
```

And in a session inside `dummy_clock`, record a different prompt, commit, then:

```powershell
pblame push          # rejected, pulls, re-plans, retries
pblame pull
pblame search --limit 6
```

**Expect both prompts present.** Before the fix, the retry wrote a plan computed before the
pull and deleted what the pull had just brought in.

## 8 — fix 7: purge leaves nothing, on a clone

**Do this in the clone, never in `dummy_clock`.** Purge is irreversible by design.

```powershell
cd ..\mate
pblame pull                                   # make sure it holds the full shared record
git for-each-ref refs/notes/                  # expect pblame and pblame-shared, maybe -remote
pblame search --limit 3                       # prompts are readable

pblame uninstall . --purge

git for-each-ref refs/notes/                  # NO pblame* refs at all
pblame search --limit 3                       # nothing to find
git log --oneline -3                          # the code and history are untouched
Get-ChildItem                                 # files still there
```

**Expect:** every `refs/notes/pblame*` gone, no prompt text recoverable, and the repository
itself completely intact. Before the fix, `pblame-shared` survived holding a full readable
copy while the command said *"every recorded prompt is gone"*.

Then prove it refuses to overreach:

```powershell
git notes --ref refs/notes/commits add -m "someone else's note" HEAD
pblame init . ; pblame uninstall . --purge
git notes --ref refs/notes/commits show HEAD  # must still be there
```

## 9 — clean up

**Close any editor open on `mate` first** or `Remove-Item` will fail on a locked folder.

```powershell
cd ..
Remove-Item -Recurse -Force mate, clock_remote.git

cd dummy_clock
git remote remove origin
pblame share --off
git update-ref -d refs/notes/pblame-shared
git update-ref -d refs/notes/pblame-remote
git for-each-ref refs/notes/        # only refs/notes/pblame should remain
pblame doctor                       # still healthy

cd ..
Remove-Item enc.txt, blame.txt
# dummy_clock.backup stays until you are happy. To roll the whole run back:
#   Remove-Item -Recurse -Force dummy_clock ; Rename-Item dummy_clock.backup dummy_clock
```

Note that step 5 rewrote two commits, so `dummy_clock`'s history now differs from the
backup's. That is expected.

---

## What I expect to break

Step 7, still. It is the only one whose fix came from a test I had to contrive rather than
from behaviour I observed, and the real version has two live Claude Code sessions, real
timing, and the hooks firing rather than explicit commands. If anything surprises us it is
there — or in step 3's absolute path, which I know is unhandled and want your judgement on.
