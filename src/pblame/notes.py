"""Attach staged receipts to commits as git notes under refs/notes/pblame.

Notes travel with the repo, need no backend, and never modify commit
objects. Payload: {"version": 1, "receipts": [...]}.
"""

from pathlib import Path

import json

from . import staging
from .models import Receipt
from .snapshot import GitError, git

NOTES_REF = "refs/notes/pblame"


def read(repo: Path, sha: str) -> list[Receipt]:
    try:
        out = git(repo, "notes", "--ref", NOTES_REF, "show", sha)
    except GitError:
        return []  # no note on this commit
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [Receipt.from_dict(d) for d in raw.get("receipts", [])]


def write(repo: Path, sha: str, receipts: list[Receipt]) -> None:
    payload = json.dumps(
        {"version": 1, "receipts": [r.to_dict() for r in receipts]}, indent=2
    )
    git(repo, "notes", "--ref", NOTES_REF, "add", "-f", "-F", "-", sha,
        input_text=payload)


def attach_staged(repo: Path, sha: str = "HEAD") -> list[Receipt]:
    """Attach closed staged receipts that touch files changed in `sha`;
    returns what was attached.

    Receipts touching only files not in this commit stay staged for a later
    commit. Closed receipts with no file changes are dropped — there is
    nothing to blame. An existing note (amend) is merged, deduped by prompt
    id.
    """
    state = staging.load(repo)
    if not state.receipts:
        return []

    commit_files = set(
        git(repo, "diff-tree", "-r", "--name-only", "--no-commit-id", "--root", sha).splitlines()
    )
    to_attach = [
        r for r in state.receipts
        if not r.is_open and any(f.path in commit_files for f in r.files)
    ]

    if to_attach:
        sha = git(repo, "rev-parse", sha)  # pin, in case HEAD moves
        existing = read(repo, sha)
        known = {r.prompt.id for r in existing}
        write(repo, sha, existing + [r for r in to_attach if r.prompt.id not in known])

    attached = set(map(id, to_attach))
    state.receipts = [
        r for r in state.receipts
        if id(r) not in attached and (r.is_open or r.files)
    ]
    staging.save(repo, state)
    return to_attach
