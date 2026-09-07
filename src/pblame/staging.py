"""Receipt staging: .git/pblame/staging.json in the recorded repo.

Receipts land here as agent turns happen and leave when `pblame attach`
writes them to git notes at commit time. Inside .git so they are never part
of the recorded tree. last_tree tracks the most recent snapshot so each
tree transition (agent turn or human gap) has its line offsets applied to
older staged receipts exactly once.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import Receipt


@dataclass
class StagingState:
    last_tree: str | None = None
    receipts: list[Receipt] = field(default_factory=list)


def _path(repo: Path) -> Path:
    return repo / ".git" / "pblame" / "staging.json"


def load(repo: Path) -> StagingState:
    try:
        raw = json.loads(_path(repo).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StagingState()
    return StagingState(
        last_tree=raw.get("last_tree"),
        receipts=[Receipt.from_dict(d) for d in raw.get("receipts", [])],
    )


def save(repo: Path, state: StagingState) -> None:
    path = _path(repo)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name("staging.json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "last_tree": state.last_tree,
                "receipts": [r.to_dict() for r in state.receipts],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)  # atomic, and overwrites on Windows


def find_open(receipts: list[Receipt], session_id: str) -> Receipt | None:
    for r in reversed(receipts):
        if r.is_open and r.prompt.session_id == session_id:
            return r
    return None


def apply_offsets(receipts: list[Receipt], offsets: dict[str, list[tuple[int, int]]]) -> None:
    """Shift closed receipts' recorded ranges to account for a newer diff
    inserting or deleting lines above them, so ranges stay valid in the
    latest tree's coordinates until attach."""
    if not offsets:
        return
    for r in receipts:
        if r.is_open:
            continue
        for fc in r.files:
            deltas = offsets.get(fc.path)
            if not deltas:
                continue
            shifted = []
            for start, end in fc.ranges:
                shift = sum(d for at, d in deltas if at <= start)
                new_start = max(start + shift, 1)
                shifted.append((new_start, new_start + (end - start)))
            fc.ranges = shifted
