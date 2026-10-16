# Hero, part A: a real prompt typed into real Claude Code.
# Part B (hero-b.tape) commits and blames; it is a separate take because the
# line range to blame is only known once Claude has written the code.

Output out/hero-a.mp4

Set Shell powershell
Set FontSize 16
Set Width 1280
Set Height 720
Set Padding 24
Set TypingSpeed 55ms
Set Theme { "name": "pblame", "background": "#12151a", "foreground": "#d6dbe0", "cursor": "#34e39b", "selection": "#2a3340", "black": "#12151a", "red": "#ef8178", "green": "#6fd79a", "yellow": "#e3bd63", "blue": "#7fa9f0", "magenta": "#ca93e8", "cyan": "#5fc9d8", "white": "#d6dbe0", "brightBlack": "#7b8691", "brightRed": "#ef8178", "brightGreen": "#6fd79a", "brightYellow": "#e3bd63", "brightBlue": "#7fa9f0", "brightMagenta": "#ca93e8", "brightCyan": "#5fc9d8", "brightWhite": "#f2f5f7" }

Hide
# Behave like a fresh terminal even when launched from inside a Claude session:
# inherited markers turn transcript saving off and the model becomes "unknown".
Type `Get-ChildItem Env: | Where-Object { $_.Name -like 'CLAUDE*' -or $_.Name -like 'ANTHROPIC*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }`
Enter
Type `cd C:\demo\envdiff`
Enter
Type `claude --model claude-sonnet-5 --permission-mode auto`
Enter
# The folder must already be trusted (see README.md here): the trust dialog
# now defaults to "No, exit", so pressing Enter blind quits Claude Code.
Wait+Screen@40s /auto mode on|shift.tab/
Sleep 1s
# The full welcome box shows the account's name and email. /clear swaps it for
# the compact header, which shows neither.
Type `/clear`
Sleep 500ms
Enter
Sleep 3s
Show

Sleep 1.5s
Type `this thing handles secrets, make it safer`
Sleep 1.2s
Enter
# Real work takes real time. The idle tail is trimmed afterwards, and any
# stretch that is sped up is labelled as such on screen.
Sleep 330s
Screenshot out/hero-a-end.png
