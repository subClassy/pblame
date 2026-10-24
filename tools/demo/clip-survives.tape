# Feature: attribution survives a squash and a rename.
Output out/clip-survives.mp4
Source "common.tape"
# Off camera: let the interactive rebase run without opening an editor.
Type `$env:GIT_SEQUENCE_EDITOR = "true" ; Clear-Host`
Enter
Show

Sleep 600ms
Type `git log --oneline -3`
Enter
Sleep 2.5s
Type `git rebase -q -i --autosquash HEAD~2`
Enter
Sleep 3s
Type `pblame show HEAD`
Enter
Sleep 4.5s

Hide
Type `Clear-Host`
Enter
Show
Type `pblame blame dotenv_loader.py -L 1,4`
Enter
Sleep 5s
