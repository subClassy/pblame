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


def git(repo: Path, *args: str, env: dict[str, str] | None = None,
        input_text: str | None = None, strip: bool = True) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        # Repo content is UTF-8. Without this, Windows decodes git's output as
        # cp1252 and a single emoji in a tracked file kills every git call.
        encoding="utf-8",
        errors="replace",
        env=full_env,
        input=input_text,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip() if strip else proc.stdout


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


def _hunk_headers(repo: Path, old_tree: str, new_tree: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """Per-file (old_start, old_count, new_start, new_count) hunk headers
    from a zero-context diff of the two trees."""
    if old_tree == new_tree:
        return {}
    out = git(repo, "diff-tree", "-r", "--unified=0", old_tree, new_tree)
    files: dict[str, list[tuple[int, int, int, int]]] = {}
    current: str | None = None
    prev = ""
    for line in out.splitlines():
        # A real "+++" header always follows the "---" line; added content
        # lines starting with "++" must not be mistaken for one.
        if line.startswith("+++ ") and prev.startswith("--- "):
            target = line[4:]
            # "+++ /dev/null" marks a deleted file
            current = target[2:] if target.startswith("b/") else None
        elif line.startswith("@@ ") and current:
            # "@@ -a[,b] +c[,d] @@ ..." — counts default to 1 when omitted
            tokens = line.split(" ")
            old_start, _, old_count = tokens[1][1:].partition(",")
            new_start, _, new_count = tokens[2][1:].partition(",")
            files.setdefault(current, []).append((
                int(old_start), int(old_count) if old_count else 1,
                int(new_start), int(new_count) if new_count else 1,
            ))
        prev = line
    return files


def diff_hunks(repo: Path, old_tree: str, new_tree: str) -> dict[str, list[tuple[int, int]]]:
    """Per-file line ranges (1-based, inclusive) in new_tree that differ from
    old_tree. Deletions contribute no ranges — there is no line left to blame."""
    hunks: dict[str, list[tuple[int, int]]] = {}
    for path, headers in _hunk_headers(repo, old_tree, new_tree).items():
        for _, _, new_start, new_count in headers:
            if new_count > 0:
                hunks.setdefault(path, []).append((new_start, new_start + new_count - 1))
    return hunks


def hunk_offsets(repo: Path, old_tree: str, new_tree: str) -> dict[str, list[tuple[int, int]]]:
    """Per-file (apply_at_line, delta) pairs: line numbers in old_tree
    coordinates at or after apply_at_line shift by delta in new_tree.
    After blameprompt's rebase_notes offset table (MIT), but with apply_at
    in old coordinates — theirs uses new, which misses top-of-file inserts."""
    offsets: dict[str, list[tuple[int, int]]] = {}
    for path, headers in _hunk_headers(repo, old_tree, new_tree).items():
        for old_start, old_count, _, new_count in headers:
            delta = new_count - old_count
            if delta != 0:
                # "-a,0" means an insertion AFTER old line a: shift starts at a+1
                apply_at = old_start + old_count if old_count else old_start + 1
                offsets.setdefault(path, []).append((apply_at, delta))
    return offsets
