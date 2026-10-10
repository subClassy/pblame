# Recording the demo — the manual

For you, at the keyboard. [The build document](day6-b-envdiff-demo.md) makes the subject;
this one turns it into a file you can send someone. Read it once end to end before you
start, because step 1 constrains everything after it.

Target: **one take, 2 to 3 minutes, no edit beyond trimming the ends.** Anything longer
gets scrubbed rather than watched, and anything that needs editing does not get re-recorded
when we change our minds.

---

## 0 — decide what this is for first

Two different artifacts, and conflating them is how demos die half-finished:

| | **The 2-minute pitch** | **The 8-minute walkthrough** |
|---|---|---|
| For | an EM who has not heard of this | someone who already said "show me more" |
| Shows | one `blame`, one `search`, the secret beat | the whole surface, including `doctor` and sharing |
| Needs | the vague-vs-precise contrast on screen | a second repo, a remote |

**Record the 2-minute one.** It is the thing that gets you the reviewer conversations the
[roadmap](roadmap.md#running-alongside-not-after) is waiting on. The walkthrough is worth
making only once someone has asked.

---

## 1 — the terminal, before anything else

This matters more than any other setup step: **the recording is only as legible as the
terminal**, and a 14pt terminal on a 4K screen is unreadable in a video player.

```powershell
# Windows Terminal: Settings -> your profile -> Appearance
#   Font: Cascadia Mono or JetBrains Mono, size 18-20
#   Colour scheme: One Half Dark or Campbell  (NOT a low-contrast theme)
#   Cursor: filled box, blinking off
```

Then size the window to **100 columns by 30 rows** and leave it there:

```powershell
$h = (Get-Host).UI.RawUI
$h.WindowSize = New-Object Management.Automation.Host.Size(100, 30)
```

100×30 at 18pt lands near 1280×720, which is what a video player shows without scaling.
`pblame blame` lays out against terminal width, so **set this before you record, not
after** — the output wraps differently and a re-record will not match your narration.

### Two things specific to this tool

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Alias pblame "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe"
```

The first line is not optional. We emit UTF-8 correctly now, but PowerShell decodes a
native command's bytes with *its* own setting, and the demo deliberately contains an em
dash. Without it you get `ù` on camera. The second is so the prompt reads `pblame blame`
and not a 90-character path — **do this, it is the difference between looking like a tool
and looking like a script**.

### Clear the screen properly

A stray scroll on camera reveals your fumbling, so the scrollback has to be gone, not
just scrolled past. `Clear-Host` is the one to use:

```powershell
Clear-Host
```

To be certain the buffer is empty — the thing that actually matters — use Windows
Terminal's own **Clear Buffer**: `Ctrl`+`Shift`+`P`, type "clear", pick *Clear Buffer*.
Bind it to a key if you are doing several takes.

*(Do not bother with `[Console]::SetWindowPosition(0,0)`. I tried it; it throws "The
handle is invalid" depending on the host.)*

---

## 2 — capture

| Tool | Why | Cost |
|---|---|---|
| **ScreenToGif** | records a window region, trims and exports MP4/GIF in the same app, no account | free, recommended |
| OBS Studio | better quality, scene control | free, 20 minutes of setup |
| Xbox Game Bar (`Win`+`G`) | already installed | captures the whole window only, no trimming |

**Use ScreenToGif.** Region capture, 30fps, record only the terminal window — not the
desktop, not a second monitor, nothing with your email address or a client name in it.

Settings that matter:
- **30fps.** 60 doubles the file for text that does not move.
- **MP4, not GIF.** A 2-minute GIF of a terminal is 40MB+ and loops distractingly.
- **No webcam, no mouse highlight.** Nothing to look at but the text.

### Audio: don't

Record **silent** and write the narration as a caption or a README beside the file.
Reasons: you will re-record four times to get the words right, your room is not quiet,
and a silent 2-minute terminal clip with a three-line written pitch is more likely to be
watched in a Slack DM than a video someone has to find headphones for.

If you do want voice, record it as a **separate** pass over the finished video rather than
live — then a fluffed sentence costs you the audio take, not the whole thing.

---

## 3 — before you hit record

A checklist, because each of these has ruined a take:

- [ ] `pblame doctor` says **Recording is live and healthy**, with no warnings
- [ ] `git log --oneline` shows the 5–6 demo commits and nothing embarrassing
- [ ] `Get-Content .git\pblame\hook.log` is empty or the file is absent
- [ ] `pblame share --off` — sharing is **off**, so the `share` beat starts from zero
- [ ] Working tree clean: `git status --short` prints nothing
- [ ] Notifications silenced (`Win`+`A` → Focus assist → Alarms only)
- [ ] Browser, Slack, mail **closed**, not minimised — alt-tab is not the risk, a toast is
- [ ] You have run the whole sequence once already, untimed, to know what the output looks like
- [ ] Terminal is 100×30 and the alias is set in *this* session

The last one bites every time: the alias and the encoding line do not survive a new tab.

---

## 4 — the shot list

Type each command. **Do not paste** — paste appears instantly and reads as fake. Type
at normal speed and pause 2 seconds after each output before the next command.

### Beat 1 — the hook (0:00–0:20)

```powershell
git blame -L 40,48 envdiff.py
```

Say (caption): *"Standard git blame. Himank, Tuesday, one commit. That is everything git
can tell you about why this line exists."*

### Beat 2 — the same lines, with intent (0:20–1:10)

```powershell
pblame blame envdiff.py
```

Let it render. Then scroll to the redaction block and hold there. **This is the shot.**
Caption:

> *"Same lines. This one came from 'this thing handles secrets, make it safer'. The one
> below it came from a prompt that specified the exact rule — no values, key names and
> lengths only. Same author, same commit, same review. Only one of them was a decision."*

Hold for 4 seconds. It is the only moment in the video that needs time to land.

### Beat 3 — it is a library, not just a view (1:10–1:40)

```powershell
pblame search "make it"
```

Caption: *"Every instruction anyone gave this codebase, searchable. Two of them were
'make it' something."*

```powershell
pblame search --path envfile.py
```

Caption: *"Including prompts from before that file was renamed."*

### Beat 4 — the objection, answered (1:40–2:10)

Someone is already thinking *"so my prompts are now in the repo forever?"* Answer it
before they ask:

```powershell
pblame doctor
```

Point at the `secrets in prompts` line. Caption: *"My prompt history has an AWS key in
it. It knows."*

```powershell
pblame push --dry-run --secrets-only
```

Caption: *"And that is exactly what leaves when I share — the key removed, the fact that
a key was removed kept. The verbatim text never leaves this machine."*

### Beat 5 — stop

Stop recording on the last line of output. **No sign-off, no "so yeah".** Trim the
trailing second in ScreenToGif.

---

## 5 — after

1. Trim the first and last second. Nothing else.
2. Export **MP4, 30fps, original size**. Expect 3–8MB.
3. Name it `pblame-demo-2min-2026-10-10.mp4` — dated, because there will be a second one.
4. Write the three-line pitch in the message you send it with, not in the video:

> `git blame` tells you who wrote a line. This tells you what they asked for.
> Every line here is traceable to the English instruction that produced it — and you can
> see which instructions were actually decisions and which were "make it safer".
> Two minutes, no audio.

5. Keep the raw capture until someone has watched it.

---

## 6 — if it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `ù` or `?` where an em dash should be | `[Console]::OutputEncoding` not set in this session | set it, re-record |
| `pblame blame` wraps badly | terminal resized after you planned the shot | restore 100×30 |
| `blame` shows fewer prompts than expected | you amended or rebased after the build | `pblame doctor`, check `recorded history` for orphans |
| `doctor` warns about an open receipt | a Claude Code session is still running | close it, re-run |
| `search` finds nothing | wrong directory | `cd` to the envdiff repo |
| Output is correct but boring | you are filming the wrong file | the contrast is in `envdiff.py`'s redaction block — find it before recording |

**If a take is 80% good, keep it and move on.** The point of this is to get three EMs to
react, not to be a good video. A second take costs 20 minutes; not having the
conversation has cost four weeks.
