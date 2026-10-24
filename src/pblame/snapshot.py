"""Working-tree snapshots via git plumbing.

A snapshot is a plain git tree object, built with a throwaway index:
`git add -A` + `git write-tree` under GIT_INDEX_FILE. Gitignore handling,
content dedup and diffing all come from git itself — no store of our own.
Cost: loose objects accumulate in the watched repo until `git gc`.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Rename detection. Without it a rename reads as delete+add and the renaming
# prompt claims every line of the new path.
RENAMES = "-M"


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
        env=full_env,
        # Bytes, not text mode: text-mode stdin turns every "\n" into "\r\n"
        # on Windows, so `check-ignore --stdin` was asked about "a.pyc\r".
        input=input_text.encode("utf-8") if input_text is not None else None,
    )
    stdout, stderr = _decode(proc.stdout), _decode(proc.stderr)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {stderr.strip()}")
    return stdout.strip() if strip else stdout


def _decode(raw: bytes) -> str:
    """What text mode produced, minus its stdin translation: UTF-8, since repo
    content is (decoding as cp1252 once let a single emoji kill every git
    call), with universal newlines."""
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def git_bytes(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    """Raw output, for commands whose framing is byte-counted — `cat-file
    --batch` gives a size in bytes, so decoding before parsing loses the
    offsets."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, input=input_bytes,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def repo_root(path: Path) -> Path:
    """Resolve the repo's top-level directory, or raise GitError."""
    return Path(git(path, "rev-parse", "--show-toplevel"))


def unreachable(repo: Path, shas: list[str]) -> set[str]:
    """Which of these commits are here but reachable from no ref — the ones
    git would drop at the next gc.

    A commit whose object we do not have is deliberately *not* in the answer.
    Never having fetched it is the normal state for a note a teammate shared,
    so "we cannot see it" proves nothing about whether it is alive.
    """
    if not shas:
        return set()
    listed = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                 input_text="\n".join(shas) + "\n", strip=False)
    present = [p[0] for p in (l.split() for l in listed.splitlines())
               if len(p) == 2 and p[1] == "commit"]
    if not present:
        return set()
    # Everything reachable from these and from no ref. A sha that survives is
    # one nothing points at any more.
    walked = git(repo, "rev-list", *present, "--not", "--all")
    return set(walked.split()) & set(present)


def snapshot_tree(repo: Path) -> str:
    """Snapshot the working tree as it stands; returns the tree SHA.

    The temp index is seeded from the repo's real one. That matters twice:

    * **Speed.** A fresh index has no stat cache, so git re-hashes every file
      in the working tree. Measured on a 20,000-file repo that is 1.9s per
      snapshot against 0.09s seeded — and there are two snapshots per prompt,
      so it is the difference between 4s and 0.2s of pause per turn.
    * **Correctness.** gitignore only applies to files git does not already
      track. A fresh index treats everything as untracked, so a tracked file
      matching an ignore rule silently vanished from the snapshot.

    Seeding is a copy; the repo's own index is never written.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "index")
        real = repo / ".git" / "index"
        try:
            if real.is_file():  # a worktree's .git is a file, so skip those
                shutil.copyfile(real, tmp)
        except OSError:
            pass  # mid-write by another git; a fresh index is still correct

        env = {"GIT_INDEX_FILE": tmp}
        try:
            git(repo, "add", "-A", env=env)
        except GitError:
            # A torn copy can be an unreadable index. Start clean rather than
            # failing the turn.
            Path(tmp).unlink(missing_ok=True)
            git(repo, "add", "-A", env=env)
        return git(repo, "write-tree", env=env)


def _diff(repo: Path, old: str, new: str) -> str:
    return git(repo, "diff-tree", "-r", RENAMES, "--unified=0", old, new)


def _hunk_headers(repo: Path, old_tree: str, new_tree: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """Per-file (old_start, old_count, new_start, new_count) hunk headers
    from a zero-context diff of the two trees."""
    if old_tree == new_tree:
        return {}
    files: dict[str, list[tuple[int, int, int, int]]] = {}
    current: str | None = None
    prev = ""
    for line in _diff(repo, old_tree, new_tree).splitlines():
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


def touched_paths(repo: Path, old_tree: str, new_tree: str) -> set[str]:
    """Every path the diff touches, including ones left with no surviving
    lines. A prompt that only deletes code still changed the codebase."""
    if old_tree == new_tree:
        return set()
    out = git(repo, "diff-tree", "-r", RENAMES, "--name-only", "--no-commit-id",
              old_tree, new_tree)
    return {p for p in out.splitlines() if p}


def renames(repo: Path, old_tree: str, new_tree: str) -> dict[str, str]:
    """{old path: new path} for files git detected as renamed, so staged
    receipts can follow the file instead of losing it."""
    if old_tree == new_tree:
        return {}
    out = git(repo, "diff-tree", "-r", RENAMES, "--name-status", "--no-commit-id",
              old_tree, new_tree)
    moved = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            moved[parts[1]] = parts[2]
    return moved


def file_kinds(repo: Path, old_tree: str, new_tree: str) -> dict[str, tuple[str, str | None]]:
    """{path: (kind, renamed_from)} for changes that leave no line ranges
    to point at: a deletion, a rename, or a binary file."""
    if old_tree == new_tree:
        return {}
    kinds: dict[str, tuple[str, str | None]] = {}
    status = git(repo, "diff-tree", "-r", RENAMES, "--name-status", "--no-commit-id",
                 old_tree, new_tree)
    for line in status.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            kinds[parts[2]] = ("renamed", parts[1])
        elif len(parts) == 2 and parts[0] == "D":
            kinds[parts[1]] = ("deleted", None)
    # Without -M, so each path is plain; numstat writes "-" for a binary.
    numstat = git(repo, "diff-tree", "-r", "--numstat", "--no-commit-id", old_tree, new_tree)
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == "-" and parts[1] == "-":
            kinds.setdefault(parts[2], ("binary", None))
    return kinds


def commit_paths(repo: Path, sha: str) -> set[str]:
    """Paths a commit changed. A merge diffs against its first parent —
    without that, diff-tree reports nothing at all for merge commits."""
    out = git(repo, "diff-tree", "-r", RENAMES, "--name-only", "--no-commit-id",
              "--root", "--diff-merges=first-parent", sha)
    return {p for p in out.splitlines() if p}


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
