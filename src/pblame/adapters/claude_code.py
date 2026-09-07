"""Claude Code adapter.

Two hooks (installed by `pblame init`) both run `pblame hook claude` with
the event JSON on stdin:

  UserPromptSubmit — opens a receipt with a pre-turn tree snapshot
  Stop             — closes it: post-turn snapshot, per-file line ranges,
                     model read from the session transcript

The diff between the two snapshots is exactly this turn's work, so manual
edits between turns are never attributed to a prompt. On every event, the
diff since the last snapshot also shifts older staged receipts' ranges
(staging.apply_offsets) so they stay valid in current-tree coordinates.
"""

import dataclasses
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import git_hooks, staging
from ..models import FileChange, PromptEvent, Receipt
from ..snapshot import diff_hunks, hunk_offsets, repo_root, snapshot_tree

HOOK_EVENTS = ("UserPromptSubmit", "Stop")


def handle(payload: dict) -> None:
    event = payload.get("hook_event_name")
    if event not in HOOK_EVENTS:
        return
    repo = repo_root(Path(payload.get("cwd") or "."))
    state = staging.load(repo)
    tree = snapshot_tree(repo)

    # Everything since the last snapshot (this turn, or a human gap) may have
    # shifted lines under older staged receipts — realign them exactly once.
    if state.last_tree and state.last_tree != tree:
        staging.apply_offsets(state.receipts, hunk_offsets(repo, state.last_tree, tree))

    if event == "UserPromptSubmit":
        # A still-open receipt means the previous turn never saw Stop
        # (interrupt or crash): close it at this boundary instead.
        _close(repo, state.receipts, payload, tree)
        state.receipts.append(
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
        _close(repo, state.receipts, payload, tree)

    state.last_tree = tree
    staging.save(repo, state)


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


def install(repo: Path) -> Path:
    """Wire the two hooks into the repo's .claude/settings.json (merged with
    whatever is there; refuses to touch corrupt JSON; idempotent)."""
    path = repo / ".claude" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        settings = json.loads(text) if text.strip() else {}  # raises on corrupt JSON
    else:
        settings = {}

    command = f'"{git_hooks.own_binary()}" hook claude'
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if any("pblame" in json.dumps(e) for e in entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": command}]})

    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path
