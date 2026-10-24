# The demo: how the site's videos and data are made

Everything on the site is real: real Claude Code writing a real project, recorded by
real pblame hooks, filmed by [vhs](https://github.com/charmbracelet/vhs) in a real
terminal. This folder is how to do it again.

**Costs:** roughly ten Claude Code prompts on whoever's account runs it, and about
twenty minutes, most of it waiting for Claude.

## Once per machine

```powershell
scoop install vhs                      # pulls in ttyd and ffmpeg
```

**Trust the demo folder before filming.** Claude Code asks whether to trust a new folder,
and the dialog now defaults to *"No, exit"* — a tape that presses Enter blind quits
Claude. Run `bash build_envdiff.sh` first (it creates `C:\demo\envdiff`), then once:

```powershell
cd C:\demo\envdiff ; claude      # choose "Yes, I trust this folder", then /exit
```

## Run it, in order

Run from this folder. Each step depends on the one before.

| | Step | Notes |
|---|---|---|
| 1 | `bash build_envdiff.sh` | Fresh repo at `C:\demo\envdiff`, five prompts through headless Claude, two commits |
| 2 | `vhs hero-a.tape` | **The prompt the hero films**, typed live into Claude Code. Waits up to 330 s |
| 3 | `vhs hero-b.tape` | Commits it and blames it. **Check the `-L` range first** — see below |
| 4 | `bash assemble_hero.sh` | Cuts 2 and 3 into `out/hero.mp4`. **Its timestamps are per take** |
| 5 | `bash build_after_hero.sh` | Rename, `--json`, and a fixup, through headless Claude |
| 6 | `vhs clip-search.tape` | Read-only |
| 7 | `vhs clip-travels.tape` | Adds a remote and a teammate clone |
| 8 | `vhs clip-survives.tape` | Rewrites history — last on purpose |
| 9 | encode into `site/media/` | the `ffmpeg` lines in [the site section](#the-site) |
| 10 | `python build_site.py --repo <url>` | Writes `site/index.html` from the template |

`out/` holds raw renders and is gitignored.

## What changes between takes

Claude answers differently every time, so three things are worked out from each take
rather than written in advance:

- **The `-L` window in `hero-b.tape`.** Read the receipt's ranges after step 2:
  `.git/pblame/staging.json` in the demo repo lists the lines the prompt changed. Pick a
  window that shows them next to the earlier, precise prompt.
- **The cut points in `assemble_hero.sh`.** `ffmpeg -i out/hero-a.mp4 -vf
  freezedetect=n=0.001:d=4 -f null -` shows where Claude was thinking (a long freeze) and
  where it finished (the final freeze).
- **The promo mask.** Claude Code's header sometimes carries a promotion that names your
  plan's currency. `assemble_hero.sh` paints over that one row until it scrolls away; find
  the scroll time with `signalstats` on that row, as the script's comments describe.

## Rules the tapes follow

- **No account details on screen.** The full welcome box shows the account's name and
  email, so `hero-a.tape` sends `/clear` off camera and films the compact header.
- **No username in any path.** The project lives at `C:\demo\envdiff`, and the tapes find
  pblame relative to this folder.
- **Clean environment.** A session started from inside another Claude Code session
  inherits markers that switch transcript saving off — and then the model is recorded as
  `unknown`. Every tape and script strips `CLAUDE*` and `ANTHROPIC*` variables first.
- **Speed-ups are labelled.** `assemble_hero.sh` stamps `8x` / `3x` on any stretch it
  speeds up, and nothing else is altered except that one promo row.
- **The page shows what a teammate sees.** `build_site.py` redacts prompt text with the
  same function a push uses, and refuses to write the page if a known secret survives.

## The site

```bash
cd tools/demo/out
for c in travels search survives; do
  ffmpeg -y -i clip-$c.mp4 -vf "fps=30,format=yuv420p" -c:v libx264 -crf 22 \
         -preset slow -movflags +faststart ../../../site/media/$c.mp4
done
cp hero.mp4 ../../../site/media/hero.mp4
# posters: the frame that shows the result, not the empty prompt at the start
ffmpeg -y -sseof -1 -i hero.mp4 -frames:v 1 -q:v 3 ../../../site/media/hero.jpg
```

Then `python build_site.py --repo https://github.com/<you>/pblame`. Add
`--preview <file>` for a standalone copy with the media inlined.
