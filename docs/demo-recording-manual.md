# Recording the demo — the manual

For you, at the keyboard. [The build document](day6-b-envdiff-demo.md) makes the subject;
this one turns it into a file you can send someone.

**The short version: you do not hand-record anything any more.**

```powershell
cd C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\tools
vhs demo.tape
```

That produces `pblame-demo.mp4` — a real terminal running real commands against
`dummy_clock`, 52 seconds, 1280×560, about 460 KB. It already works; the current render is
in `demo/`, which is gitignored because it is regenerable. Everything below explains how to
change it and when to reach for something else.

---

## 0 — the two artifacts, and which one you have

| | **The pitch** | **The walkthrough** |
|---|---|---|
| For | an EM who has not heard of this | someone who already said "show me more" |
| Shows | `blame`, `search`, the secret beat, `doctor` | the whole surface, two repos, a remote |
| You have | ✔ [the tape](../tools/demo.tape) and [the page](#the-page) | not built — worth doing only once asked |

The pitch is what gets you the reviewer conversations the
[roadmap](roadmap.md#running-alongside-not-after) is waiting on.

## The page

**<https://claude.ai/artifact/NLNq4YEEaZR6hjoHrM8A17>** — the same story in text and
terminal output, with the reasoning written beside each block. Every block is verbatim
stdout from the same commands the tape runs; the only edit is turning the ANSI colour
escapes into CSS.

It needs no player and no download, which makes it the better thing to drop in a Slack DM.
The video is better when someone is watching you talk. **It is private until you share it**
from the page's share menu.

Use whichever suits the recipient. They are built from the same commands.

---

## 1 — how the tape works

[`tools/demo.tape`](../tools/demo.tape) is a [vhs](https://github.com/charmbracelet/vhs)
script. vhs opens a real headless terminal, types the commands, and encodes the result. The
output is a genuine recording — not an animation of captured text — so it cannot drift from
what the tool actually does.

Five beats, each ending with an off-camera `Clear-Host`:

| | Beat | Why it is there |
|---|---|---|
| 1 | `git blame -L 136,140 time.js` | establishes what git can already tell you |
| 2 | `pblame blame time.js -L 136,140` | **the shot.** Four prompts, five lines |
| 3 | `pblame search` twice | it is a library, and it survived a rename |
| 4 | `pblame redact` + `push --dry-run` | answers "so my secrets are in the repo now?" |
| 5 | `pblame doctor` | it tells you when it stops working |

**Beat 2 is the demo.** Line 138 is a hundred characters of user-facing copy that came from
four words — *"switch to more descriptive"* — and directly beneath it line 139 came from a
forty-word specification. Same author, same file, same review. If you cut the video to one
shot, cut it to that one.

### Changing it

- **Timing:** the `Sleep` after each `Enter`. Beat 2 holds 9s because it is the one that
  needs reading time; the rest hold 4–5s.
- **Size:** `Set Width` / `Set Height`. 560 is tuned to the tallest beat — the first render
  used 820 and left a third of every frame empty. If you add a beat with more output, raise
  it and re-check.
- **A GIF as well:** add a second `Output pblame-demo.gif` line. Expect roughly 10× the
  size; MP4 is the one to send.
- **Line 138 is the width constraint.** It is 101 characters, so anything narrower than
  about 1200px wraps it and the punchline loses its shape.

### Setup, off camera

The tape sets `[Console]::OutputEncoding` before filming. **Do not remove that line.** We
emit UTF-8 correctly, but PowerShell decodes a native command's bytes with *its* setting,
and beat 2 contains an em dash and a 🕐. Without it you get `ù` on camera — that is what
day 7's `before-search.txt` shows.

Beat 4 writes a `prod.env` prop off camera and deletes it at the end. The AWS key in it is
AWS's own documentation example, so nothing in the frame is a live credential.

---

## 2 — before you render

- [ ] `pblame doctor` in dummy_clock says *Recording is live* — one warning about
      `8b731e5` is expected and explained in [day 9](day9-fix-verification.md#18-doctor-only-looked-for-dead-notes-in-the-mirror--fixed)
- [ ] `git status --short` in dummy_clock prints nothing
- [ ] you are not mid-session in dummy_clock with an open receipt

The render takes about 90 seconds and needs no attention. It does not touch the repo: every
filmed command is read-only, and the one prop is cleaned up.

---

## 3 — when you still need to record by hand

vhs films a terminal and nothing else. Reach for a screen recorder when the demo needs an
editor, a browser, or a GitHub PR in frame — which is exactly what **Phase 2** will need.

**ScreenToGif** (free, no account) is the one to use: region capture, trims and exports in
the same app. OBS if you want scene control and have 20 minutes.

Then the terminal setup matters again, because you are filming your own:

```powershell
# Windows Terminal -> Settings -> your profile -> Appearance
#   Font: Cascadia Mono or JetBrains Mono, size 18-20
#   Colour scheme: One Half Dark or Campbell  (NOT a low-contrast theme)
#   Cursor: filled box, blinking off
```

```powershell
$h = (Get-Host).UI.RawUI
$h.WindowSize = New-Object Management.Automation.Host.Size(100, 30)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Alias pblame "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts\pblame.exe"
```

The alias is worth the two seconds: it is the difference between looking like a tool and
looking like a script. None of these survive a new tab, which is the thing that ruins takes.

To clear scrollback properly, use `Clear-Host`, or Windows Terminal's **Clear Buffer**
(`Ctrl`+`Shift`+`P`, type "clear"). *(`[Console]::SetWindowPosition(0,0)` throws "The handle
is invalid" on some hosts — I tried it.)*

Settings: **30fps**, **MP4 not GIF**, no webcam, no mouse highlight. Close Slack and mail
rather than minimising them — a toast is the risk, not alt-tab.

---

## 4 — audio: don't

Record silent and write the pitch in the message you send it with. You will re-record four
times getting the words right, your room is not quiet, and a silent clip with three lines of
written framing is more likely to be watched in a DM than a video someone needs headphones
for. If you do want voice, record it as a separate pass over the finished video so a fluffed
sentence costs you the audio take rather than everything.

The three lines to send with it:

> `git blame` tells you who wrote a line. This tells you what they asked for.
> Every line is traceable to the English instruction that produced it — and you can see
> which instructions were decisions and which were "make it look nicer".
> 52 seconds, no audio.

---

## 5 — if it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `vhs: command not found` | not on PATH | `scoop install vhs` — it pulls ttyd and ffmpeg too |
| Render hangs | ttyd port in use | close other vhs runs, retry |
| `ù` where an em dash should be | the encoding line was removed from the tape | put it back |
| Line 138 wraps | `Set Width` below ~1200 | raise it |
| Big empty area under the output | `Set Height` taller than the tallest beat | lower it |
| `doctor` shows an open receipt | a Claude Code session is still live in dummy_clock | close it, re-render |
| Output is right but boring | you are filming the wrong lines | the contrast is `time.js` 136–140, nothing else |

**If a render is 80% good, ship it.** The point is to get three EMs to react, not to make a
good video. Re-rendering costs 90 seconds, so there is no excuse for a bad one — but there
is also no prize for a perfect one.
