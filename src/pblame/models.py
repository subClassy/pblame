"""Core data model for the staging → attach → blame pipeline.

A Receipt is one agent turn: the prompt that started it, the tree snapshots
bounding it, and the file line ranges it produced. Receipts accumulate in
staging while the developer works and attach to whatever commit they make
(git notes, day 3). See docs/gameplan-v2.md.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PromptEvent:
    id: str
    text: str
    model: str  # empty until the turn closes; read from the transcript at Stop
    timestamp: datetime
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "model": self.model,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PromptEvent":
        return cls(
            id=d["id"],
            text=d["text"],
            model=d["model"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            session_id=d["session_id"],
        )


@dataclass
class FileChange:
    path: str
    ranges: list[tuple[int, int]]  # inclusive 1-based line ranges in the post-turn tree

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "ranges": [list(r) for r in self.ranges]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileChange":
        return cls(path=d["path"], ranges=[(r[0], r[1]) for r in d["ranges"]])


@dataclass
class Receipt:
    prompt: PromptEvent
    pre_tree: str
    post_tree: str | None = None  # None while the turn is still running
    files: list[FileChange] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.post_tree is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt.to_dict(),
            "pre_tree": self.pre_tree,
            "post_tree": self.post_tree,
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Receipt":
        return cls(
            prompt=PromptEvent.from_dict(d["prompt"]),
            pre_tree=d["pre_tree"],
            post_tree=d["post_tree"],
            files=[FileChange.from_dict(f) for f in d["files"]],
        )
