Set Shell powershell
Set FontSize 16
Set Width 1280
Set Height 640
Set Padding 24
Set TypingSpeed 40ms
Set Theme { "name": "pblame", "background": "#12151a", "foreground": "#d6dbe0", "cursor": "#34e39b", "selection": "#2a3340", "black": "#12151a", "red": "#ef8178", "green": "#6fd79a", "yellow": "#e3bd63", "blue": "#7fa9f0", "magenta": "#ca93e8", "cyan": "#5fc9d8", "white": "#d6dbe0", "brightBlack": "#7b8691", "brightRed": "#ef8178", "brightGreen": "#6fd79a", "brightYellow": "#e3bd63", "brightBlue": "#7fa9f0", "brightMagenta": "#ca93e8", "brightCyan": "#5fc9d8", "brightWhite": "#f2f5f7" }

Hide
Type `Get-ChildItem Env: | Where-Object { $_.Name -like 'CLAUDE*' -or $_.Name -like 'ANTHROPIC*' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }`
Enter
# vhs starts in the directory it was run from: tools/demo.
Type `$env:Path = (Resolve-Path ..\..\.venv\Scripts).Path + ";" + $env:Path`
Enter
Type `[Console]::OutputEncoding = [Text.Encoding]::UTF8`
Enter
# The folder name in the prompt is what tells the viewer whose machine they are on.
Type `function prompt { "$(Split-Path -Leaf (Get-Location))> " }`
Enter
Type `cd C:\demo\envdiff`
Enter
