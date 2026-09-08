"""Marker-fenced git hook installation, coexisting with any hooks the user
already has (pattern from blameprompt, MIT)."""

import sys
from pathlib import Path

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
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
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


def _post_commit_section() -> str:
    # Hooks run under git's sh even on Windows; forward slashes work there.
    exe = own_binary().replace("\\", "/")
    return (
        f"{MARK_START}\n"
        f'"{exe}" attach 2>>.git/pblame/hook.log || true\n'
        f"{MARK_END}\n"
    )


def install_post_commit(repo: Path) -> Path:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    path = hooks_dir / "post-commit"
    section = _post_commit_section()

    if path.exists():
        existing = path.read_text(encoding="utf-8")
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
