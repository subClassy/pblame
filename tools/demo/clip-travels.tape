# Feature: the prompt travels with the code, the secrets do not.
# Your record is verbatim. A teammate pulls a redacted copy through plain git.
Output out/clip-travels.mp4
Source "common.tape"
# Off camera: a remote, the code pushed to it, sharing turned on.
Type `git init -q --bare C:\demo\envdiff-remote.git ; git remote add origin C:\demo\envdiff-remote.git ; git push -q origin main 2>$null ; pblame share | Out-Null`
Enter
Type `Clear-Host`
Enter
Show

Sleep 600ms
Type `pblame blame envdiff.py -L 33,35`
Enter
Sleep 4.5s
Type `pblame push`
Enter
Sleep 3s

Hide
Type `Clear-Host`
Enter
Show
Type `git clone -q C:\demo\envdiff-remote.git C:\demo\teammate ; cd C:\demo\teammate`
Enter
Sleep 1.5s
Type `pblame pull`
Enter
Sleep 2.5s
Type `pblame blame envdiff.py -L 33,35`
Enter
Sleep 6s
