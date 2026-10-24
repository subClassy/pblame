"""Marker-fenced git hook installation, coexisting with any hooks the user
already has (pattern from blameprompt, MIT)."""

import sys
from pathlib import Path

from . import config
from .snapshot import GitError, git

MARK_START = "# pblame"
MARK_END = "# /pblame"


def ensure_ignored(repo: Path, rel_path: str) -> None:
    """Ignore rel_path via .git/info/exclude, unless git already ignores it.
    Repo-local on purpose: no tracked file is modified, so `pblame init`
    never dirties the working tree or lands in a commit."""
    try:
        git(repo, "check-ignore", "-q", rel_path)
        return  # some ignore source already covers it
    except GitError:
        pass

    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding=config.USER_TEXT) if exclude.exists() else ""
    if rel_path in existing.split():
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with exclude.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"{prefix}{rel_path}\n")


def own_binary() -> str:
    """Absolute path to the running pblame entry point, for use in hooks."""
    exe = Path(sys.argv[0])
    if exe.stem.lower() == "pblame":
        return str(exe.resolve())
    return "pblame"  # fall back to PATH


def _section(subcommand: str) -> str:
    """One marker-fenced hook body running `pblame <subcommand>`.

    Hooks run under git's sh even on Windows, so forward slashes are fine. The
    log directory is created here rather than assumed: a fresh clone has no
    `.git/pblame`, and a redirect into a missing directory made git print an
    error on every pull. GIT_DIR is set by git for hooks, which also keeps this
    working where `.git` is a file rather than a directory.
    """
    exe = own_binary().replace("\\", "/")
    return (
        f"{MARK_START}\n"
        'PBLAME_DIR="${GIT_DIR:-.git}/pblame"\n'
        'mkdir -p "$PBLAME_DIR" 2>/dev/null || true\n'
        f'"{exe}" {subcommand} 2>>"$PBLAME_DIR/hook.log" || true\n'
        f"{MARK_END}\n"
    )


# post-commit  attach staged receipts to the commit just made.
# post-rewrite amend/rebase feed "<old> <new>" pairs on stdin; without this a
#              note is stranded on a commit no longer reachable.
# pre-push     share on push, so nobody has to remember `pblame push`. No
#              recursion guard is needed: the inner notes push passes
#              --no-verify. Run in the foreground, unlike blameprompt — one
#              extra round trip for a tiny ref beats a backgrounded failure
#              nobody sees, a lesson this project has already paid for.
# post-merge   when you pull code, pull the prompts that came with it.
#              post-checkout looks like the place for a fresh clone, but git
#              never clones .git/hooks, so a new teammate runs `pblame init`
#              regardless — and hooking every branch switch would mean a
#              network fetch each time.
HOOKS = {
    "post-commit": lambda: _section("attach"),
    "post-rewrite": lambda: _section("rewrite"),
    "pre-push": lambda: _section("push --if-enabled"),
    "post-merge": lambda: _section("pull --if-enabled"),
}

# These only matter once sharing is on, so doctor treats them as optional
# until then.
SHARING_HOOKS = frozenset({"pre-push", "post-merge"})


def hooks_path_override(repo: Path) -> str | None:
    """core.hooksPath, when it sends git somewhere other than .git/hooks.

    husky sets it. git then never runs anything in .git/hooks, so the hooks
    installed there are inert — and for a long time nothing said so.
    """
    try:
        active = Path(git(repo, "rev-parse", "--git-path", "hooks"))
    except GitError:
        return None
    if not active.is_absolute():
        active = repo / active
    if active.resolve() == (repo / ".git" / "hooks").resolve():
        return None
    try:
        return git(repo, "config", "--get", "core.hooksPath")
    except GitError:
        return str(active)


def install_hooks(repo: Path) -> list[Path]:
    """Install every pblame git hook, preserving any hooks already there."""
    return [_install(repo, name, section()) for name, section in HOOKS.items()]


def install_post_commit(repo: Path) -> Path:
    return _install(repo, "post-commit", HOOKS["post-commit"]())


def _install(repo: Path, name: str, section: str) -> Path:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    path = hooks_dir / name

    if path.exists():
        existing = path.read_text(encoding=config.USER_TEXT)
        if MARK_START in existing:
            content = _remove_section(existing).rstrip("\n") + "\n\n" + section
        else:
            content = existing.rstrip("\n") + "\n\n" + section
    else:
        content = "#!/bin/sh\n\n" + section

    path.write_text(content, encoding="utf-8", newline="\n")
    if sys.platform != "win32":
        path.chmod(0o755)
    return path


def uninstall_hooks(repo: Path) -> list[Path]:
    """Remove pblame's sections from the git hooks, leaving any other hook
    content untouched; a hook file that held nothing else is deleted."""
    removed = []
    for name in HOOKS:
        path = repo / ".git" / "hooks" / name
        if not path.exists():
            continue
        content = path.read_text(encoding=config.USER_TEXT)
        if MARK_START not in content:
            continue
        rest = _remove_section(content)
        if rest.strip() in ("", "#!/bin/sh"):
            path.unlink()
        else:
            path.write_text(rest, encoding="utf-8", newline="\n")
        removed.append(path)
    return removed


def _remove_section(content: str) -> str:
    kept = []
    skipping = False
    for line in content.splitlines():
        if line.strip() == MARK_START:
            skipping = True
            continue
        if line.strip() == MARK_END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)
    return "\n".join(kept) + "\n"
