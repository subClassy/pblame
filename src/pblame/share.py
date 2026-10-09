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

from . import index, notes, redact
from .config import Config
from .snapshot import GitError, git
from .ui import plural


class ShareDisabled(RuntimeError):
    pass


@dataclass
class Planned:
    """One commit's worth of what would leave this machine."""
    sha: str
    receipts: list  # redacted
    detections: list = field(default_factory=list)
    desired: list = field(default_factory=list)  # the whole note to write
    is_new: bool = True  # False when the mirror already holds exactly this


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
    """What `push` would send, commit by commit.

    Reads both refs in a handful of git calls rather than one per commit:
    doing it per commit cost 9s for a push that changed nothing on a
    60-commit repo, and would be over a minute at 500.
    """
    mirror = index.notes_by_commit(repo, notes.SHARED_REF)
    planned = []
    for sha, local in index.notes_by_commit(repo, notes.NOTES_REF).items():
        receipts, detections = [], []
        for r in local:
            clean, found = redact_receipt(r, cfg.redaction)
            receipts.append(clean)
            detections += found
        if not receipts:
            continue

        # Our redaction supersedes whatever the mirror holds for the same
        # prompt — we authored it, and the pattern set may have changed since.
        # Anything else in that note is a teammate's and must survive.
        existing = mirror.get(sha, [])
        ours = {r.prompt.id for r in receipts}
        desired = notes.fold([r for r in existing if r.prompt.id not in ours] + receipts)

        planned.append(Planned(
            sha, receipts, detections, desired=desired,
            is_new=notes.signature(desired) != notes.signature(existing)))
    return planned


def stage(repo: Path, planned: list[Planned]) -> None:
    """Write the redacted receipts into the mirror, merging rather than
    overwriting so a teammate's note for the same commit survives.

    Only notes that would actually change are written. `git notes add` makes a
    commit per note, so writing unconditionally grew the mirror by one commit
    per recorded commit on every push.
    """
    for item in planned:
        if item.is_new:
            notes.write(repo, item.sha, item.desired, notes.SHARED_REF)


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
