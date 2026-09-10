"""Attach staged receipts to commits as git notes under refs/notes/pblame.

Notes travel with the repo, need no backend, and never modify commit
objects. Payload: {"version": 1, "receipts": [...]}.
"""

import copy
import dataclasses
import json
from pathlib import Path

from . import staging
from .models import FileChange, Receipt
from .snapshot import (
    GitError,
    commit_paths,
    diff_hunks,
    git,
    hunk_offsets,
    snapshot_tree,
    touched_paths,
)

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


def merge_into(repo: Path, sha: str, receipts: list[Receipt]) -> None:
    """Add receipts to a commit's note, deduplicating by prompt id."""
    existing = read(repo, sha)
    known = {r.prompt.id for r in existing}
    combined = existing + [r for r in receipts if r.prompt.id not in known]
    if combined:
        write(repo, sha, combined)


def remove(repo: Path, sha: str) -> None:
    try:
        git(repo, "notes", "--ref", NOTES_REF, "remove", sha)
    except GitError:
        pass  # nothing there to remove


def _close_orphans(repo: Path, state: staging.StagingState) -> None:
    """Close receipts a dead session left open.

    `find_open` matches on session_id, so a receipt orphaned by an interrupt
    plus a session change would otherwise stay open forever and never attach.
    At commit time all work is done, so closing them here is safe.
    """
    tree = None
    for r in state.receipts:
        if not r.is_open:
            continue
        if tree is None:
            tree = snapshot_tree(repo)
        r.post_tree = tree
        hunks = diff_hunks(repo, r.pre_tree, tree)
        r.files = [
            FileChange(path=p, ranges=hunks.get(p, []))
            for p in sorted(touched_paths(repo, r.pre_tree, tree))
        ]
        if not r.prompt.model:
            # The turn never reached Stop, so no transcript was ever read.
            r.prompt = dataclasses.replace(r.prompt, model="unknown")


def _split(receipt: Receipt, paths: set[str]) -> tuple[Receipt | None, Receipt | None]:
    """Divide a receipt into (part inside this commit, part still pending).

    One prompt often edits files the developer commits separately; attaching
    it whole would drag ranges for files this commit never touched.
    """
    inside = [f for f in receipt.files if f.path in paths]
    outside = [f for f in receipt.files if f.path not in paths]
    if not inside:
        return None, receipt
    if not outside:
        return receipt, None
    here, pending = copy.deepcopy(receipt), copy.deepcopy(receipt)
    here.files, pending.files = inside, outside
    return here, pending


def attach_staged(repo: Path, sha: str = "HEAD") -> list[Receipt]:
    """Attach the parts of staged receipts that touch files this commit
    changed; returns what was attached. Anything else stays staged for a
    later commit. Receipts touching no file at all are dropped."""
    with staging.lock(repo):
        state = staging.load(repo)
        if not state.receipts:
            return []
        _close_orphans(repo, state)

        paths = commit_paths(repo, sha)
        attached, pending = [], []
        for r in state.receipts:
            here, rest = _split(r, paths)
            if here:
                attached.append(here)
            if rest and rest.files:
                pending.append(rest)

        if attached:
            merge_into(repo, git(repo, "rev-parse", sha), attached)

        state.receipts = pending
        staging.save(repo, state)
        return attached


def remap(repo: Path, old_sha: str, new_sha: str) -> int:
    """Move a note from a rewritten commit onto its replacement, shifting
    ranges by whatever the rewrite changed. Returns receipts carried over.

    Without this, amend/rebase/squash strands every note on a commit no
    longer reachable, silently losing the attribution.
    """
    receipts = read(repo, old_sha)
    if not receipts:
        return 0
    staging.apply_offsets(receipts, hunk_offsets(repo, old_sha, new_sha))
    merge_into(repo, new_sha, receipts)
    remove(repo, old_sha)
    return len(receipts)
