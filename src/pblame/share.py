"""Sharing: push a redacted mirror of the record, pull what teammates shared.

Three refs, and the split between them is the whole safety story:

  refs/notes/pblame          local, verbatim. Never pushed. What blame reads.
  refs/notes/pblame-shared   the redacted mirror. This is what travels, and
                             it is also where teammates' notes land.
  refs/notes/pblame-remote   scratch ref a fetch writes into.

Because the mirror is a separate ref, a pull can never overwrite the
author's own prompts, and a push never needs --force: the mirror only ever
moves forward, and a rejected push is resolved by pulling and merging rather
than by clobbering.

blameprompt pushes and fetches the single ref with a `+` force refspec, so
the second developer to push silently overwrites the first.
"""

import copy
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from . import notes, redact
from .snapshot import GitError, git
from .ui import plural
from .config import Config
from .snapshot import GitError, git


class ShareDisabled(RuntimeError):
    pass


@dataclass
class Planned:
    """One commit's worth of what would leave this machine."""
    sha: str
    receipts: list  # redacted
    detections: list = field(default_factory=list)


def redact_receipt(receipt, cfg) -> tuple[object, list]:
    """A copy with its prompt text filtered. `secrets` is kept deliberately:
    a reviewer seeing that an AWS key was removed here learns something, and
    it costs nothing to say so."""
    result = redact.redact(receipt.prompt.text, cfg)
    out = copy.deepcopy(receipt)
    # Report what redaction just did, not what an old capture-time scan
    # recorded: receipts written before that scan existed carry nothing, and
    # patterns change over time.
    out.prompt = dataclasses.replace(
        out.prompt, text=result.text, secrets=redact.summarize(result.detections))
    return out, result.detections


def plan(repo: Path, cfg: Config) -> list[Planned]:
    """What `push` would send, commit by commit."""
    planned = []
    for sha in notes.commits_with_notes(repo, notes.NOTES_REF):
        receipts, detections = [], []
        for r in notes.read(repo, sha, notes.NOTES_REF):
            clean, found = redact_receipt(r, cfg.redaction)
            receipts.append(clean)
            detections += found
        if receipts:
            planned.append(Planned(sha, receipts, detections))
    return planned


def stage(repo: Path, planned: list[Planned]) -> None:
    """Write the redacted receipts into the mirror ref, merging rather than
    overwriting so a teammate's note for the same commit survives."""
    for item in planned:
        notes.merge_into(repo, item.sha, item.receipts, notes.SHARED_REF)


def _ref_exists(repo: Path, ref: str) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", ref)
        return True
    except GitError:
        return False


def pull(repo: Path, cfg: Config) -> int:
    """Fetch what others shared and merge it into the mirror. Returns the
    number of commits the mirror now has notes for."""
    remote = cfg.share.remote
    try:
        # Force is safe here and nowhere else: FETCH_REF is our own scratch ref.
        git(repo, "fetch", remote, f"+{notes.NOTES_REF}:{notes.FETCH_REF}")
    except GitError as e:
        # Nobody has shared anything yet — that is the normal first-pull case,
        # not a failure.
        if "couldn't find remote ref" in str(e) or "not our ref" in str(e):
            return len(notes.commits_with_notes(repo, notes.SHARED_REF))
        raise
    if not _ref_exists(repo, notes.FETCH_REF):
        return 0

    if _ref_exists(repo, notes.SHARED_REF):
        # union is a correct merge because the payload is JSONL; a line-wise
        # merge of pretty-printed JSON would not be valid JSON.
        git(repo, "notes", "--ref", notes.SHARED_REF,
            "merge", "--strategy=union", notes.FETCH_REF)
    else:
        git(repo, "update-ref", notes.SHARED_REF, notes.FETCH_REF)
    return len(notes.commits_with_notes(repo, notes.SHARED_REF))


def push(repo: Path, cfg: Config) -> list[Planned]:
    """Redact, stage into the mirror, and push it to the remote's notes ref."""
    if not cfg.share.enabled:
        raise ShareDisabled(
            "Sharing is off for this repo. `pblame push --dry-run` shows exactly what "
            "would be sent, and `pblame share` turns it on."
        )
    planned = plan(repo, cfg)
    if not planned:
        return []
    stage(repo, planned)

    refspec = f"{notes.SHARED_REF}:{notes.NOTES_REF}"
    try:
        # --no-verify keeps this from re-entering the pre-push hook.
        git(repo, "push", "--no-verify", cfg.share.remote, refspec)
    except GitError:
        # Someone else pushed first. Merge their work in and try once more —
        # never force, or we would delete what they shared.
        pull(repo, cfg)
        stage(repo, planned)
        # --no-verify keeps this from re-entering the pre-push hook.
        git(repo, "push", "--no-verify", cfg.share.remote, refspec)
    return planned


def describe(planned: list[Planned], redacted_only: bool = False) -> str:
    """Human-readable preview: exactly the text that would leave."""
    if not planned:
        return "  nothing recorded yet"
    lines, total, hits = [], 0, 0
    for item in planned:
        shown = [r for r in item.receipts
                 if not redacted_only or r.prompt.secrets]
        total += len(item.receipts)
        hits += len(item.detections)
        if not shown:
            continue
        lines.append(f"  {item.sha[:7]}")
        for r in shown:
            lines.append(f"    {r.prompt.text.strip() or '(empty)'}")
            if r.prompt.secrets:
                found = ", ".join(sorted(r.prompt.secrets))
                lines.append(f"      ^ redacted: {found}")
        lines.append("")
    lines.append(f"  {total} prompt{plural(total)} across {len(planned)}"
                 f" commit{plural(len(planned))}, {hits} secret{plural(hits)} redacted")
    return "\n".join(lines)
