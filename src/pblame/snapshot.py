"""Working-tree snapshots via git plumbing.

A snapshot is a plain git tree object, built with a throwaway index:
`git add -A` + `git write-tree` under GIT_INDEX_FILE. Gitignore handling,
content dedup and diffing all come from git itself — no store of our own.
Cost: loose objects accumulate in the watched repo until `git gc`.
"""

import os
import subprocess
import tempfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path:
    """Resolve the repo's top-level directory, or raise GitError."""
    return Path(git(path, "rev-parse", "--show-toplevel"))


def snapshot_tree(repo: Path) -> str:
    """Snapshot the working tree as it stands; returns the tree SHA."""
    with tempfile.TemporaryDirectory() as td:
        # A fresh index means every file is "untracked", so `add -A` builds
        # the tree exactly as gitignore sees it. (Tracked-but-ignored files
        # are missed — acceptable for week 1.)
        env = {"GIT_INDEX_FILE": os.path.join(td, "index")}
        git(repo, "add", "-A", env=env)
        return git(repo, "write-tree", env=env)


def diff_hunks(repo: Path, old_tree: str, new_tree: str) -> dict[str, list[tuple[int, int]]]:
    """Per-file line ranges (1-based, inclusive) in new_tree that differ from
    old_tree. Deletions contribute no ranges — there is no line left to blame."""
    if old_tree == new_tree:
        return {}
    out = git(repo, "diff-tree", "-r", "--unified=0", old_tree, new_tree)
    hunks: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            # "+++ /dev/null" marks a deleted file
            current = target[2:] if target.startswith("b/") else None
        elif line.startswith("@@ ") and current:
            # "@@ -a,b +c,d @@ ..." — we want the +c,d side
            new_part = line.split(" +", 1)[1].split(" ", 1)[0]
            start, _, count = new_part.partition(",")
            n = int(count) if count else 1
            if n > 0:
                s = int(start)
                hunks.setdefault(current, []).append((s, s + n - 1))
    return hunks
