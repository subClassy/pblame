"""Receipt staging: .git/pblame/staging.json in the recorded repo.

Receipts land here as agent turns happen and leave when `pblame attach`
writes them to git notes at commit time. Inside .git so they are never part
of the recorded tree. last_tree tracks the most recent snapshot so each
tree transition (agent turn or human gap) has its line offsets applied to
older staged receipts exactly once.
"""

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .models import Receipt

LOCK_TIMEOUT = 10.0


@dataclass
class StagingState:
    last_tree: str | None = None
    receipts: list[Receipt] = field(default_factory=list)


def _dir(repo: Path) -> Path:
    return repo / ".git" / "pblame"


def _path(repo: Path) -> Path:
    return _dir(repo) / "staging.json"


@contextmanager
def lock(repo: Path, timeout: float = LOCK_TIMEOUT):
    """Serialize read-modify-write of the staging file.

    Two agent sessions in one repo would otherwise both load, both mutate,
    and the second save would silently discard the first's receipt. On
    timeout we proceed anyway: losing a lock is better than blocking, or
    failing, somebody's agent turn.
    """
    path = _dir(repo)
    path.mkdir(exist_ok=True)
    lock_path = path / "staging.lock"
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                # Assume the holder died and took the lock file with it.
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock_path.unlink()
            except OSError:
                pass


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


def _shift_at(line: int, deltas: list[tuple[int, int]]) -> int:
    return sum(d for at, d in deltas if at <= line)


def remap_range(start: int, end: int, deltas: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Map one old-coordinate range into new coordinates. An insertion landing
    inside the range splits it in two — the lines above the insertion keep
    their old position while the lines below slide down."""
    pieces: list[tuple[int, int]] = []
    seg_start = start
    for at, delta in sorted(deltas):
        if delta > 0 and seg_start < at <= end:
            pieces.append((seg_start, at - 1))
            seg_start = at
    pieces.append((seg_start, end))

    # Endpoints shift independently so a deletion inside the range shrinks it.
    remapped = []
    for s, e in pieces:
        new_s = max(s + _shift_at(s, deltas), 1)
        remapped.append((new_s, max(e + _shift_at(e, deltas), new_s)))
    return remapped


def apply_offsets(receipts: list[Receipt], offsets: dict[str, list[tuple[int, int]]]) -> None:
    """Realign closed receipts' recorded ranges after a newer diff inserted or
    deleted lines, so ranges stay valid in the latest tree's coordinates."""
    if not offsets:
        return
    for r in receipts:
        if r.is_open:
            continue
        for fc in r.files:
            deltas = offsets.get(fc.path)
            if not deltas:
                continue
            fc.ranges = [
                piece for start, end in fc.ranges
                for piece in remap_range(start, end, deltas)
            ]


def apply_renames(receipts: list[Receipt], moved: dict[str, str]) -> None:
    """Follow renames so an earlier prompt keeps owning its lines under the
    file's new name instead of silently losing them."""
    if not moved:
        return
    for r in receipts:
        for fc in r.files:
            if fc.path in moved:
                fc.path = moved[fc.path]
