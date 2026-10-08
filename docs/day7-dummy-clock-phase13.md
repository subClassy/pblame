# Day 7 — dummy_clock validation: sharing, search, repair

Same shape as [day 6a](day6-a-dummy-clock-validation.md): hostile, in-scope, aimed at the
features merged since. Phases 1 and 3 have only ever been exercised on scratch repos and
one copy of dummy_clock — this runs them on the real thing.

Run in `C:\Users\subCl\Documents\Fun_stuff\apps\dummy_clock`. Set the alias once so you
are not typing `&` everywhere:

```powershell
Set-Alias pblame "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe"
```

**This run changes your real repo.** Step 0 takes a backup, step 9 undoes the rest.

---

## 0 — baseline and a way back

```powershell
cd C:\Users\subCl\Documents\Fun_stuff\apps
Copy-Item -Recurse dummy_clock dummy_clock.backup
cd dummy_clock
pblame init .                      # picks up every hook, including the sharing two
pblame doctor                      # read the "live snapshot" line: that is your per-prompt cost
pblame search | Out-File -Encoding utf8 ..\before-search.txt
```

`doctor` should now say *Recording is live and healthy*. Note the snapshot timing — this
is the first time you will have seen it on a real repo.

## 1 — repair the polluted prompts (merged this session)

Five of your recorded prompts still carry `<ide_opened_file>` wrappers.

```powershell
pblame repair                      # preview only, writes nothing
pblame repair --write
pblame search "look nicer"         # the prompt should now read as a sentence
```

Expect: *Repaired 5 prompts*, and `pblame search` output that is readable rather than
dominated by editor boilerplate. Compare against `before-search.txt`.

Then check the side effect that matters: those wrappers contained your Windows username,
so the home-path detections should now be gone.

```powershell
pblame doctor                      # "secrets in prompts" should say none detected
```

## 2 — search, properly

```powershell
pblame search ring                 # text
pblame search --path styles.css    # one file
pblame search --path "*.js" --since 3w
pblame search --model sonnet
pblame search "stopwatch" --json | ConvertFrom-Json | Select-Object -Expand count
pblame search definitely-not-there ; $LASTEXITCODE   # expect 1, like grep
```

The question to actually answer while doing this: **would you use it?** If you find
yourself reaching for `git log` instead, say so — that matters more than whether the
flags work.

## 3 — a local remote, and sharing

No GitHub needed.

```powershell
cd ..
git init --bare clock_remote.git
cd dummy_clock
git remote add origin ..\clock_remote.git
git push origin main

pblame push                        # refuses: sharing is off
pblame share
pblame push --dry-run              # read this carefully - it is the consent story
pblame push
```

Expect the refusal first, then a preview naming every prompt that would leave, then
*Shared N prompts*. After the repair in step 1 it should report **0 secrets redacted**.

## 4 — the hooks do it for you

```powershell
# record a real prompt in a fresh Claude Code session, then:
git commit -am "clock: a small change"     # post-commit attaches
git push origin main                        # pre-push shares, no command needed
```

Expect one `pblame` line inside each git command's output.

## 5 — be your own teammate

```powershell
cd ..
git clone clock_remote.git teammate
cd teammate
pblame init . ; pblame share ; pblame pull
pblame search ring                 # YOUR prompts, in a repo that never recorded them
pblame blame time.js               # attribution with no local record at all
pblame show 0461c2b                # the 7 Sep prompt
```

**The moment to look for:** run `pblame show 0a59a13` in both folders. Identical prompt,
two views — verbatim for you, redacted for everyone else.

## 6 — concurrent sharing (fix #8, never tried on real data)

```powershell
cd ..\teammate
# record a prompt here, commit, then:
pblame push
cd ..\dummy_clock
# record a different prompt here, commit, then:
pblame push                        # rejected, merged, retried
pblame pull
pblame search --limit 5            # both prompts present, neither lost
```

This is the case blameprompt's force refspec destroys. Nothing should disappear.

## 7 — rewriting history with sharing on

```powershell
git commit --amend -m "clock: amended with sharing on"
pblame show HEAD                   # receipts carried over
pblame push                        # the mirror follows
```

## 8 — report back

```powershell
pblame doctor
pblame search --limit 30
pblame show HEAD
git log --oneline --graph -8
Get-Content .git\pblame\hook.log   # must be empty
Get-Content .git\pblame\staging.json
```

Plus `before-search.txt` so I can diff what repair changed.

## 9 — undo

```powershell
cd ..
Remove-Item -Recurse -Force teammate, clock_remote.git
cd dummy_clock
git remote remove origin
Remove-Item .pblame.local.json
# and if anything went wrong, the backup is beside it:
#   Remove-Item -Recurse -Force dummy_clock ; Rename-Item dummy_clock.backup dummy_clock
```

---

## If something looks wrong

`pblame doctor` first. Exit code 1 means recording is not reliable — stop and tell me
rather than prompting further.

## What I expect to break

Honestly: step 6, and step 4's interaction with it. Concurrent push has only been tested
against synthetic repos with one file, and the retry path depends on git rejecting a push
in exactly the way the test simulates. If anything is going to surprise us it is there.
