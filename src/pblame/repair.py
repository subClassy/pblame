"""Recompute derived fields on prompts already recorded.

Two things go stale in a note:

* **Editor context.** Claude Code wraps the typed prompt in
  `<ide_opened_file>` and friends. `clean_prompt` strips that now, but
  prompts recorded before it existed still carry the wrapper — and in a
  prompt library that noise pushes the actual sentence out of view.
* **The secret scan.** Receipts written before that scan existed report no
  secrets, so `doctor` under-reports what is sitting in the record.

Cleaning the text also removes whatever was hiding inside the wrapper: the
home paths that leaked to a remote lived in `<ide_opened_file>` lines, so a
repair deletes them at the source rather than relying on redaction.

This rewrites recorded history, so it previews by default. The notes ref
keeps a reflog, so `refs/notes/pblame@{1}` is the way back.
"""

import copy
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from . import index, notes, redact
from .adapters.claude_code import clean_prompt
from .config import Config
from .models import Receipt

REFS = (notes.NOTES_REF, notes.SHARED_REF)


@dataclass
class Repair:
    """One note's worth of repair, with the differences that justify it."""
    ref: str
    sha: str
    receipts: list[Receipt] = field(default_factory=list)   # the whole repaired note
    changed: list[tuple[Receipt, Receipt]] = field(default_factory=list)  # before, after


def repaired(receipt: Receipt, cfg) -> Receipt:
    text = clean_prompt(receipt.prompt.text)
    out = copy.deepcopy(receipt)
    out.prompt = dataclasses.replace(
        out.prompt, text=text,
        secrets=redact.summarize(redact.scan(text, cfg)))
    return out


def _differs(before: Receipt, after: Receipt) -> bool:
    return (before.prompt.text != after.prompt.text
            or before.prompt.secrets != after.prompt.secrets)


def plan(repo: Path, cfg: Config, refs=REFS) -> list[Repair]:
    """Notes that would change, newest ref first. Empty means nothing to do."""
    out = []
    for ref in refs:
        for sha, receipts in index.notes_by_commit(repo, ref).items():
            fixed = [repaired(r, cfg.redaction) for r in receipts]
            changed = [(b, a) for b, a in zip(receipts, fixed) if _differs(b, a)]
            if changed:
                out.append(Repair(ref, sha, fixed, changed))
    return out


def apply(repo: Path, plans: list[Repair]) -> int:
    """Write the repaired notes back. Returns the number of prompts changed."""
    for item in plans:
        notes.write(repo, item.sha, item.receipts, item.ref)
    return sum(len(item.changed) for item in plans)


def describe(plans: list[Repair], width: int = 72) -> str:
    if not plans:
        return "  nothing to repair"

    def clip(text: str) -> str:
        flat = " ".join(text.split())
        return flat if len(flat) <= width else flat[: width - 3] + "..."

    lines = []
    for item in plans:
        where = "local" if item.ref == notes.NOTES_REF else "shared"
        lines.append(f"  {item.sha[:7]}  {where}")
        for before, after in item.changed:
            if before.prompt.text != after.prompt.text:
                lines.append(f"    - {clip(before.prompt.text)}")
                lines.append(f"    + {clip(after.prompt.text) or '(empty)'}")
            if before.prompt.secrets != after.prompt.secrets:
                was = ", ".join(sorted(before.prompt.secrets)) or "none"
                now = ", ".join(sorted(after.prompt.secrets)) or "none"
                lines.append(f"      secrets: {was} -> {now}")
        lines.append("")
    total = sum(len(i.changed) for i in plans)
    lines.append(f"  {total} prompt{'' if total == 1 else 's'} across"
                 f" {len(plans)} note{'' if len(plans) == 1 else 's'}")
    return "\n".join(lines)
