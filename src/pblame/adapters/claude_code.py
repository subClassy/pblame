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
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import config, git_hooks, redact, staging
from ..models import FileChange, PromptEvent, Receipt
from ..snapshot import (
    diff_hunks,
    hunk_offsets,
    renames,
    repo_root,
    snapshot_tree,
    touched_paths,
)

HOOK_EVENTS = ("UserPromptSubmit", "Stop")

# Claude Code wraps the typed prompt in editor context. The prompt is this
# product's core artifact, so store what the developer actually wrote.
_INJECTED = re.compile(
    r"<(ide_opened_file|ide_selection|system-reminder)>.*?</\1>",
    re.DOTALL,
)


def clean_prompt(text: str) -> str:
    return _INJECTED.sub("", text).strip()


def handle(payload: dict) -> None:
    event = payload.get("hook_event_name")
    if event not in HOOK_EVENTS:
        return
    repo = repo_root(Path(payload.get("cwd") or "."))
    with staging.lock(repo):
        state = staging.load(repo)
        tree = snapshot_tree(repo)

        # Everything since the last snapshot (this turn, or a human gap) may
        # have moved lines or whole files under older staged receipts —
        # realign them exactly once.
        if state.last_tree and state.last_tree != tree:
            staging.apply_renames(state.receipts, renames(repo, state.last_tree, tree))
            staging.apply_offsets(state.receipts, hunk_offsets(repo, state.last_tree, tree))

        if event == "UserPromptSubmit":
            # A still-open receipt means the previous turn never saw Stop
            # (interrupt or crash): close it at this boundary instead.
            _close(repo, state.receipts, payload, tree)
            text = clean_prompt(payload.get("prompt", ""))
            state.receipts.append(
                Receipt(
                    prompt=PromptEvent(
                        id=uuid.uuid4().hex,
                        text=text,
                        model="",
                        timestamp=datetime.now(timezone.utc),
                        session_id=payload.get("session_id", ""),
                        secrets=_scan_secrets(repo, text),
                    ),
                    pre_tree=tree,
                )
            )
        else:  # Stop
            _close(repo, state.receipts, payload, tree)

        state.last_tree = tree
        staging.save(repo, state)


def _scan_secrets(repo: Path, text: str) -> dict[str, str]:
    """Note which secret types the prompt contains, keeping the worst severity
    seen for each. The text is stored verbatim regardless — this is so
    `doctor` can warn before anything is shared, not a reason to mangle the
    author's own record."""
    try:
        cfg = config.load(repo).redaction
    except config.ConfigError:
        cfg = None  # a typo in config must never cost us the receipt
    return redact.summarize(redact.scan(text, cfg))


def _close(repo: Path, receipts: list[Receipt], payload: dict, post_tree: str) -> None:
    receipt = staging.find_open(receipts, payload.get("session_id", ""))
    if receipt is None:
        return
    receipt.post_tree = post_tree
    # Every touched path, not just those with surviving lines: a prompt that
    # only deletes code still changed the codebase and belongs in the record.
    hunks = diff_hunks(repo, receipt.pre_tree, post_tree)
    receipt.files = [
        FileChange(path=path, ranges=hunks.get(path, []))
        for path in sorted(touched_paths(repo, receipt.pre_tree, post_tree))
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


SHARED_SETTINGS = "settings.json"
LOCAL_SETTINGS = "settings.local.json"


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else {}  # raises on corrupt JSON


def _strip_pblame_hooks(settings: dict) -> bool:
    """Drop pblame's hook entries, leaving any others alone."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    removed = False
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if "pblame" not in json.dumps(e)]
        if len(kept) != len(entries):
            removed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return removed


def install(repo: Path) -> Path:
    """Wire the two hooks into .claude/settings.local.json — the personal,
    gitignored variant, because the command embeds an absolute path to this
    machine's pblame binary and must never be committed. Merges with whatever
    is already there; refuses to touch corrupt JSON; idempotent."""
    claude_dir = repo / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # An earlier version installed into the shared settings. Leaving those in
    # place would fire every hook twice and corrupt turn boundaries.
    shared = claude_dir / SHARED_SETTINGS
    if shared.exists():
        data = _read_settings(shared)
        if _strip_pblame_hooks(data):
            if data:
                shared.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            else:
                shared.unlink()  # it held nothing but pblame's hooks
            print(f"pblame: moved hooks out of {shared.name} into {LOCAL_SETTINGS}")

    path = claude_dir / LOCAL_SETTINGS
    settings = _read_settings(path)
    command = f'"{git_hooks.own_binary()}" hook claude'
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if any("pblame" in json.dumps(e) for e in entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": command}]})

    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    git_hooks.ensure_ignored(repo, f".claude/{LOCAL_SETTINGS}")
    git_hooks.ensure_ignored(repo, config.LOCAL_FILENAME)
    return path


def uninstall(repo: Path) -> list[Path]:
    """Remove pblame's hooks from both settings files, keeping everything
    else. A file left holding nothing is deleted."""
    touched = []
    for name in (LOCAL_SETTINGS, SHARED_SETTINGS):
        path = repo / ".claude" / name
        if not path.exists():
            continue
        try:
            data = _read_settings(path)
        except json.JSONDecodeError:
            continue  # not ours to fix; leave it alone
        if not _strip_pblame_hooks(data):
            continue
        if data:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        else:
            path.unlink()
        touched.append(path)
    return touched
