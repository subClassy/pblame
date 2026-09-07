"""Claude Code adapter.

Two hooks (installed by `pblame init`, day 3) both run `pblame hook claude`
with the event JSON on stdin:

  UserPromptSubmit — opens a receipt with a pre-turn tree snapshot
  Stop             — closes it: post-turn snapshot, per-file line ranges,
                     model read from the session transcript

The diff between the two snapshots is exactly this turn's work, so manual
edits between turns are never attributed to a prompt.
"""

import dataclasses
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import staging
from ..models import FileChange, PromptEvent, Receipt
from ..snapshot import diff_hunks, repo_root, snapshot_tree


def handle(payload: dict) -> None:
    event = payload.get("hook_event_name")
    if event not in ("UserPromptSubmit", "Stop"):
        return
    repo = repo_root(Path(payload.get("cwd") or "."))
    receipts = staging.load(repo)
    tree = snapshot_tree(repo)

    if event == "UserPromptSubmit":
        # A still-open receipt means the previous turn never saw Stop
        # (interrupt or crash): close it at this boundary instead.
        _close(repo, receipts, payload, tree)
        receipts.append(
            Receipt(
                prompt=PromptEvent(
                    id=uuid.uuid4().hex,
                    text=payload.get("prompt", ""),
                    model="",
                    timestamp=datetime.now(timezone.utc),
                    session_id=payload.get("session_id", ""),
                ),
                pre_tree=tree,
            )
        )
    else:  # Stop
        _close(repo, receipts, payload, tree)

    staging.save(repo, receipts)


def _close(repo: Path, receipts: list[Receipt], payload: dict, post_tree: str) -> None:
    receipt = staging.find_open(receipts, payload.get("session_id", ""))
    if receipt is None:
        return
    receipt.post_tree = post_tree
    receipt.files = [
        FileChange(path=path, ranges=ranges)
        for path, ranges in diff_hunks(repo, receipt.pre_tree, post_tree).items()
    ]
    model = _model_from_transcript(payload.get("transcript_path"))
    receipt.prompt = dataclasses.replace(receipt.prompt, model=model)


def _model_from_transcript(path: str | None) -> str:
    """Last assistant message's model from the session's JSONL transcript."""
    if not path:
        return "unknown"
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "unknown"
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message")
        if isinstance(msg, dict) and msg.get("model"):
            return msg["model"]
    return "unknown"
