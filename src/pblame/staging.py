"""Receipt staging: .git/pblame/staging.json in the recorded repo.

Receipts land here as agent turns happen and leave when `pblame attach`
(day 3) writes them to git notes at commit time. Inside .git so they are
never part of the recorded tree.
"""

import json
import os
from pathlib import Path

from .models import Receipt


def _path(repo: Path) -> Path:
    return repo / ".git" / "pblame" / "staging.json"


def load(repo: Path) -> list[Receipt]:
    try:
        raw = json.loads(_path(repo).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [Receipt.from_dict(d) for d in raw.get("receipts", [])]


def save(repo: Path, receipts: list[Receipt]) -> None:
    path = _path(repo)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name("staging.json.tmp")
    tmp.write_text(
        json.dumps({"receipts": [r.to_dict() for r in receipts]}, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)  # atomic, and overwrites on Windows


def find_open(receipts: list[Receipt], session_id: str) -> Receipt | None:
    for r in reversed(receipts):
        if r.is_open and r.prompt.session_id == session_id:
            return r
    return None
