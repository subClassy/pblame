# The demo, as a script vhs can run. Real commands in a real terminal.
#
#   scoop install vhs          (pulls ttyd and ffmpeg too)
#   cd tools ; vhs demo.tape
#
# Nothing here writes to the repo being filmed: every command is read-only.
# Retiming is editing two numbers, not re-recording, which is the whole point
# of keeping the demo as a file.

Output pblame-demo.mp4

Set Shell powershell
Set FontSize 16
Set Width 1280
Set Height 560
Set Padding 24
Set Theme { "name": "pblame", "background": "#12151a", "foreground": "#d6dbe0", "cursor": "#34e39b", "selection": "#2a3340", "black": "#12151a", "red": "#ef8178", "green": "#6fd79a", "yellow": "#e3bd63", "blue": "#7fa9f0", "magenta": "#ca93e8", "cyan": "#5fc9d8", "white": "#d6dbe0", "brightBlack": "#7b8691", "brightRed": "#ef8178", "brightGreen": "#6fd79a", "brightYellow": "#e3bd63", "brightBlue": "#7fa9f0", "brightMagenta": "#ca93e8", "brightCyan": "#5fc9d8", "brightWhite": "#f2f5f7" }

# Setup, off camera. The encoding line is not optional: the demo contains an
# em dash and a clock emoji, and PowerShell decodes a native command's bytes
# with its own setting rather than ours.
Hide
Type `$env:Path = "C:\Users\subCl\Documents\Fun_stuff\prompt_version_system\.venv\Scripts;" + $env:Path`
Enter
Type `[Console]::OutputEncoding = [Text.Encoding]::UTF8`
Enter
Type `cd C:\Users\subCl\Documents\Fun_stuff\apps\dummy_clock`
Enter
Type `Clear-Host`
Enter
Show

# 1 ---- what git can tell you -------------------------------------------
Type `git blame -L 136,140 --date=short time.js`
Sleep 500ms
Enter
Sleep 5s

Hide
Type `Clear-Host`
Enter
Show

# 2 ---- the same five lines, with the intent behind them -----------------
Type `pblame blame time.js -L 136,140`
Sleep 500ms
Enter
Sleep 9s

Hide
Type `Clear-Host`
Enter
Show

# 3 ---- it is a searchable library --------------------------------------
Type `pblame search "switch to"`
Sleep 500ms
Enter
Sleep 4s
Type `pblame search --path styles.css --limit 2`
Sleep 500ms
Enter
Sleep 5s

Hide
Type `Clear-Host`
Enter
Show

# 4 ---- the objection: my prompts have secrets in them -------------------
# prod.env is a prop, written off camera and deleted at the end. The AWS key
# is AWS's own documentation example, so nothing here is a live credential.
Hide
Type `Set-Content prod.env -Encoding ascii @("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE","DATABASE_PASSWORD=hunter2correct","CLIENT_SECRET=abc123def456ghi789","ADMIN_EMAIL=ops@acme.io","LOG_LEVEL=debug")`
Enter
Type `Clear-Host`
Enter
Show

Type `pblame redact prod.env`
Sleep 500ms
Enter
Sleep 5s
Type `pblame push --dry-run --secrets-only`
Sleep 500ms
Enter
Sleep 5s

Hide
Type `Clear-Host`
Enter
Show

# 5 ---- and it says so when it stops working ----------------------------
Type `pblame doctor`
Sleep 500ms
Enter
Sleep 7s

# Put the prop back in the bin.
Hide
Type `Remove-Item prod.env -ErrorAction SilentlyContinue`
Enter
Show
