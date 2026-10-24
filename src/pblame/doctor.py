"""Preflight check: is this repo actually being recorded, right now?

Built from failures we have actually had. The worst of them was silent — a
git call started raising, the hook swallowed it to protect the agent's turn,
and 26 minutes of work went unrecorded with nothing to show for it. Every
check here either proves a link in that chain or surfaces its wreckage.
"""

import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config, git_hooks, notes, staging, ui
from .ui import plural
from .adapters import claude_code
from .snapshot import GitError, git, snapshot_tree, unreachable

PASS, WARN, FAIL = "pass", "warn", "fail"

_QUOTED = re.compile(r'^"([^"]+)"')


@dataclass
class Check:
    status: str
    label: str
    detail: str = ""


def _binary_from(command: str) -> str | None:
    m = _QUOTED.match(command.strip())
    if m:
        return m.group(1)
    parts = command.split()
    return parts[0] if parts else None


def _binary_exists(path: str) -> bool:
    # Hook commands record the console-script path without its Windows
    # extension; sh and Claude Code resolve it, so accept either form.
    if Path(path).exists():
        return True
    if any(Path(path + ext).exists() for ext in (".exe", ".cmd", ".bat")):
        return True
    return shutil.which(path) is not None


def _check_agent_hooks(repo: Path) -> list[Check]:
    path = repo / ".claude" / claude_code.LOCAL_SETTINGS
    if not path.exists():
        return [Check(FAIL, "Claude Code hooks", f"{path.name} missing - run `pblame init`")]
    try:
        settings = json.loads(path.read_text(encoding=config.USER_TEXT))
    except (OSError, json.JSONDecodeError) as e:
        return [Check(FAIL, "Claude Code hooks", f"cannot read {path.name}: {e}")]

    hooks = settings.get("hooks", {})
    out, commands = [], []
    for event in claude_code.HOOK_EVENTS:
        found = [h.get("command", "") for entry in hooks.get(event, [])
                 for h in entry.get("hooks", []) if "pblame" in h.get("command", "")]
        if found:
            commands += found
            out.append(Check(PASS, f"{event} hook", "registered"))
        else:
            out.append(Check(FAIL, f"{event} hook", "not registered - run `pblame init`"))
        if len(found) > 1:
            out.append(Check(FAIL, f"{event} hook", f"registered {len(found)}x - turns "
                                                    "will be recorded twice"))

    for command in set(commands):
        binary = _binary_from(command)
        if binary and not _binary_exists(binary):
            out.append(Check(FAIL, "hook binary", f"{binary} does not exist - hooks fire "
                                                  "into nothing"))
    return out


def _check_git_hooks(repo: Path) -> list[Check]:
    try:
        sharing = config.load(repo).share.enabled
    except config.ConfigError:
        sharing = False
    out = []
    override = git_hooks.hooks_path_override(repo)
    if override:
        # The hook files are there, but git is looking elsewhere. Saying
        # "installed" here is how a husky repo went unattributed while this
        # check passed. Each hook's job now happens some other way; say how.
        instead = {
            "post-commit": "commits are attributed at the next prompt or pblame command",
            "post-rewrite": "amends and rebases are followed at the next prompt",
            "pre-push": "git push will not share prompts; run `pblame push`",
            "post-merge": "git pull will not fetch prompts; run `pblame pull`",
        }
        for name in git_hooks.HOOKS:
            if name in git_hooks.SHARING_HOOKS and not sharing:
                continue
            out.append(Check(WARN, f"{name} hook",
                             f"not run by git (core.hooksPath is {override}); {instead[name]}"))
        return out
    for name in git_hooks.HOOKS:
        path = repo / ".git" / "hooks" / name
        if not path.exists() or git_hooks.MARK_START not in path.read_text(encoding=config.USER_TEXT):
            # pre-push and post-merge only matter once sharing is on.
            optional = name in git_hooks.SHARING_HOOKS and not sharing
            out.append(Check(WARN if optional else FAIL, f"{name} hook",
                             "not installed - run `pblame init`"))
            continue
        out.append(Check(PASS, f"{name} hook", "installed"))
        for line in path.read_text(encoding=config.USER_TEXT).splitlines():
            if "pblame" in line and line.strip().startswith('"'):
                binary = _binary_from(line)
                if binary and not _binary_exists(binary):
                    out.append(Check(FAIL, f"{name} binary", f"{binary} does not exist"))
    return out


def _check_recording_works(repo: Path) -> Check:
    """Actually exercise the recorder against this repo's real content, and
    report how long it took.

    This is the check that would have caught the encoding failure: it only
    breaks once a file holds a byte the recorder cannot handle. The timing is
    the honest answer to "how will this behave on my repo" — a prompt costs
    two of these, and nobody should have to guess.
    """
    try:
        start = time.perf_counter()
        snapshot_tree(repo)
        elapsed = time.perf_counter() - start
    except Exception as e:
        return Check(FAIL, "live snapshot", f"{type(e).__name__}: {e}")

    per_prompt = elapsed * 2
    detail = f"{elapsed * 1000:.0f}ms, so ~{per_prompt * 1000:.0f}ms per prompt"
    if per_prompt < 1.0:
        return Check(PASS, "live snapshot", detail)
    # Big working tree. git's own file-system monitor skips the stat sweep.
    return Check(WARN, "live snapshot",
                 f"{detail} - try `git config core.fsmonitor true`"
                 " and `git config core.untrackedCache true`")


def _check_hook_log(repo: Path) -> Check:
    path = repo / ".git" / "pblame" / "hook.log"
    try:
        lines = [l for l in path.read_text(encoding=config.USER_TEXT).splitlines() if l.strip()]
    except OSError:
        return Check(PASS, "hook log", "empty - no hook has failed")
    if not lines:
        return Check(PASS, "hook log", "empty - no hook has failed")
    return Check(FAIL, "hook log", f"{len(lines)} error(s), latest: {lines[-1]}")


def _check_staging(repo: Path) -> list[Check]:
    path = repo / ".git" / "pblame" / "staging.json"
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return [Check(FAIL, "staging", f"unreadable: {e}")]

    state = staging.load(repo)
    closed = [r for r in state.receipts if not r.is_open]
    out = [Check(PASS, "staging",
                 f"{len(closed)} prompt{plural(len(closed))} awaiting a commit")]

    for r in state.receipts:
        if not r.is_open:
            continue
        age = datetime.now(timezone.utc) - r.prompt.timestamp
        note = f'"{r.prompt.text[:40]}" open for {int(age.total_seconds() // 60)} min'
        # A turn still running is normal; one open for ages is a dead session
        # whose pre-turn snapshot no longer reflects reality.
        out.append(Check(WARN if age.total_seconds() < 1800 else FAIL, "open receipt", note))
    return out


def _check_history(repo: Path) -> list[Check]:
    out = []
    shas = notes.commits_with_notes(repo, notes.NOTES_REF)
    count = len(shas)
    detail = f"{count} commit{plural(count)} carry recorded prompts"
    # The same rot the mirror check reports, in the verbatim record, where it
    # matters more: this is the only copy of those prompts. A rewrite that
    # bypassed post-rewrite is how one gets here.
    try:
        dead = unreachable(repo, shas)
    except GitError:
        dead = set()
    if dead:
        shown = ", ".join(sorted(s[:7] for s in dead)[:3])
        out.append(Check(WARN, "recorded history",
                         f"{detail}, {len(dead)} of them no longer in history ({shown})"))
    else:
        out.append(Check(PASS if count else WARN, "recorded history", detail))

    try:
        head = notes.read(repo, "HEAD")
        if head:
            latest = max(r.prompt.timestamp for r in head)
            out.append(Check(PASS, "HEAD", f"{len(head)} prompt{plural(len(head))},"
                                           f" latest {latest:%Y-%m-%d %H:%M}"))
        else:
            out.append(Check(WARN, "HEAD", "no receipts on the current commit"))
    except GitError:
        pass
    return out


def _check_mirror(repo: Path) -> list[Check]:
    """Mirror entries pointing at commits nothing references any more.

    A rewrite used to leave one behind on every push, and because the mirror
    travels, every clone inherits them and the repos then disagree on how many
    prompts exist. Reported rather than removed: a note is not recoverable
    once deleted, and this is the number that says whether removing them is
    worth the risk yet.
    """
    shas = notes.commits_with_notes(repo, notes.SHARED_REF)
    if not shas:
        return []
    try:
        dead = unreachable(repo, shas)
    except GitError:
        return []
    if not dead:
        return [Check(PASS, "shared mirror",
                      f"{len(shas)} commit{plural(len(shas))}, all still in history")]
    shown = ", ".join(sorted(s[:7] for s in dead)[:3])
    return [Check(WARN, "shared mirror",
                  f"{len(dead)} of {len(shas)} notes point at commits a rewrite"
                  f" left behind ({shown})")]


def _check_secrets(repo: Path) -> list[Check]:
    """Report secrets sitting in recorded prompts.

    They are not a failure — the record is as private as the code beside it,
    and redaction happens when a receipt leaves the machine. But nobody should
    be surprised by what is in there, least of all on the day they turn
    sharing on.
    """
    try:
        cfg = config.load(repo)
    except config.ConfigError as e:
        return [Check(FAIL, "config", str(e))]

    found: dict[str, str] = {}
    prompts = 0
    receipts = list(staging.load(repo).receipts)
    try:
        for line in git(repo, "notes", "--ref", notes.NOTES_REF, "list").splitlines():
            parts = line.split()
            if len(parts) > 1:
                receipts += notes.read(repo, parts[1])
    except GitError:
        pass

    for r in receipts:
        if r.prompt.secrets:
            prompts += 1
            for name, severity in r.prompt.secrets.items():
                found.setdefault(name, severity)

    out = [Check(PASS, "sharing", f"enabled, remote {cfg.share.remote}"
                 if cfg.share.enabled else "off - prompts stay on this machine")]
    if cfg.shared_tried_to_enable and not cfg.share.enabled:
        out.append(Check(WARN, "sharing",
                         f"{config.FILENAME} asks for sharing but that is yours to "
                         f"choose - run `pblame share` to opt in"))
    if not found:
        out.append(Check(PASS, "secrets in prompts", "none detected"))
        return out

    worst = next((s for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
                  if s in found.values()), "LOW")
    detail = f"{prompts} prompt{plural(prompts)} contain {', '.join(sorted(found))}"
    # Only a problem if it is about to be published.
    status = FAIL if (cfg.share.enabled and worst in ("CRITICAL", "HIGH")) else WARN
    out.append(Check(status, "secrets in prompts", detail + f" (worst {worst})"))
    if cfg.share.enabled:
        out.append(Check(PASS, "", "these are redacted on push; `pblame push --dry-run`"
                                   " shows exactly what would be sent"))
    return out


def run(repo: Path) -> list[Check]:
    checks = _check_agent_hooks(repo) + _check_git_hooks(repo)
    checks.append(_check_recording_works(repo))
    checks.append(_check_hook_log(repo))
    checks += (_check_staging(repo) + _check_history(repo)
               + _check_mirror(repo) + _check_secrets(repo))
    return checks


def render(checks: list[Check], color: bool = True) -> str:
    codes = {PASS: ui.GREEN, WARN: ui.YELLOW, FAIL: ui.RED}
    marks = {PASS: "ok", WARN: "warn", FAIL: "bad"}
    sym = ui.out.sym
    width = max((len(c.label) for c in checks), default=0)

    def paint(text: str, *c: str) -> str:
        return f"{''.join(c)}{text}{ui.RESET}" if color else text

    out = []
    for c in checks:
        mark = paint(sym[marks[c.status]], codes[c.status], ui.BOLD)
        out.append(f"  {mark} {paint(c.label.ljust(width), ui.DIM)}  {c.detail}".rstrip())

    failed = sum(1 for c in checks if c.status == FAIL)
    warned = sum(1 for c in checks if c.status == WARN)
    out.append("")
    if failed:
        out.append("  " + paint(f"Not recording reliably - {failed} check"
                                f"{'' if failed == 1 else 's'} failing", ui.RED, ui.BOLD))
    elif warned:
        out.append("  " + paint("Recording is live", ui.GREEN, ui.BOLD)
                   + paint(f", {warned} warning{'' if warned == 1 else 's'}", ui.DIM))
    else:
        out.append("  " + paint("Recording is live and healthy", ui.GREEN, ui.BOLD))
    return "\n".join(out)
