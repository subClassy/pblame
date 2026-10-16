# Hero, part B: commit what Claude wrote in part A, then blame it.
# The -L window was chosen after part A, from the receipt's own line ranges:
# 16-28 is what "make it safer" wrote, 31-33 is the precise prompt before it.

Output out/hero-b.mp4

Set Shell powershell
Set FontSize 16
Set Width 1280
Set Height 720
Set Padding 24
Set TypingSpeed 45ms
Set Theme { "name": "pblame", "background": "#12151a", "foreground": "#d6dbe0", "cursor": "#34e39b", "selection": "#2a3340", "black": "#12151a", "red": "#ef8178", "green": "#6fd79a", "yellow": "#e3bd63", "blue": "#7fa9f0", "magenta": "#ca93e8", "cyan": "#5fc9d8", "white": "#d6dbe0", "brightBlack": "#7b8691", "brightRed": "#ef8178", "brightGreen": "#6fd79a", "brightYellow": "#e3bd63", "brightBlue": "#7fa9f0", "brightMagenta": "#ca93e8", "brightCyan": "#5fc9d8", "brightWhite": "#f2f5f7" }

Hide
# vhs starts in the directory it was run from: tools/demo.
Type `$env:Path = (Resolve-Path ..\..\.venv\Scripts).Path + ";" + $env:Path`
Enter
Type `[Console]::OutputEncoding = [Text.Encoding]::UTF8`
Enter
Type `cd C:\demo\envdiff`
Enter
Type `Clear-Host`
Enter
Show

Sleep 800ms
Type `git commit -qam "envdiff: make it safer"`
Sleep 400ms
Enter
Sleep 2.5s
Hide
Type `Clear-Host`
Enter
Show
Type `pblame blame envdiff.py -L 16,33`
Sleep 400ms
Enter
Sleep 9s
