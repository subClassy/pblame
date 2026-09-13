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
    renames,
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


def _union_ranges(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(a + b):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _absorb(target: Receipt, source: Receipt) -> None:
    """Fold source's files into target's, unioning ranges per path."""
    by_path = {f.path: f for f in target.files}
    for f in source.files:
        if f.path in by_path:
            by_path[f.path].ranges = _union_ranges(by_path[f.path].ranges, f.ranges)
        else:
            target.files.append(f)
            by_path[f.path] = f


def merge_into(repo: Path, sha: str, receipts: list[Receipt]) -> None:
    """Add receipts to a commit's note.

    The same prompt can legitimately reach one commit twice: attach splits a
    receipt across commits by file, and a later squash reunites those
    commits. Dropping the second copy would lose its files, so copies of one
    prompt are merged, not deduplicated.
    """
    existing = read(repo, sha)
    by_id = {r.prompt.id: r for r in existing}
    for r in receipts:
        if r.prompt.id in by_id:
            _absorb(by_id[r.prompt.id], r)
        else:
            existing.append(r)
            by_id[r.prompt.id] = r
    if existing:
        write(repo, sha, existing)


def remove(repo: Path, sha: str) -> None:
    try:
        git(repo, "notes", "--ref", NOTES_REF, "remove", sha)
    except GitError:
        pass  # nothing there to remove


def _close_orphans(repo: Path, state: staging.StagingState) -> None:
    """Close receipts a dead session left open.

    `find_open` matches on session_id, so a receipt orphaned by an interrupt
    plus a session change would otherwise stay open forever and never attach.

    An orphan's work ends where the *next* prompt began — not at the commit.
    Closing it against the commit tree would swallow every later prompt's
    work as its own. Ranges computed at that boundary are then realigned to
    the current tree, which the closed receipts were already tracking.
    """
    now = None
    receipts = state.receipts
    for i, r in enumerate(receipts):
        if not r.is_open:
            continue
        if now is None:
            now = snapshot_tree(repo)
        end = receipts[i + 1].pre_tree if i + 1 < len(receipts) else now

        r.post_tree = end
        hunks = diff_hunks(repo, r.pre_tree, end)
        r.files = [
            FileChange(path=p, ranges=hunks.get(p, []))
            for p in sorted(touched_paths(repo, r.pre_tree, end))
        ]
        if end != now:
            staging.apply_renames([r], renames(repo, end, now))
            staging.apply_offsets([r], hunk_offsets(repo, end, now))
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
