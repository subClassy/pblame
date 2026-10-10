"""Give a repo one recorded prompt without a Claude Code session.

Only for verification: the hooks are what do this in real use. It writes the
same Receipt shape the recorder writes, onto the local verbatim ref.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pblame import notes
from pblame.models import FileChange, PromptEvent, Receipt
from pblame.snapshot import git

repo = Path(sys.argv[1]).resolve()
text = sys.argv[2]
path = sys.argv[3]

sha = git(repo, "rev-parse", "HEAD")
receipt = Receipt(
    prompt=PromptEvent(id=uuid.uuid4().hex, text=text, model="claude-opus-5",
                       timestamp=datetime.now(timezone.utc), session_id="verify"),
    pre_tree="a" * 40,
    post_tree=git(repo, "rev-parse", "HEAD^{tree}"),
    files=[FileChange(path=path, ranges=[(1, 1)])],
)
notes.merge_into(repo, sha, [receipt])
print(f"recorded on {sha[:7]}: {text}")
