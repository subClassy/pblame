"""The read side: every recorded prompt, loaded at once and searchable.

`git notes show` costs a subprocess per commit — 46ms on Windows, so a repo
with 500 recorded commits takes 23 seconds. Reading the notes tree with one
`ls-tree` and one `cat-file --batch` makes that two subprocesses regardless
of size.

This is also the seam the roadmap asks for: everything above searches
`Entry` objects, so the source can later become a service without the
callers noticing.
"""

import fnmatch
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import notes
from .models import Receipt
from .snapshot import GitError, git, git_bytes

_RELATIVE = re.compile(r"^(\d+)\s*([dwmy])$", re.I)
_UNITS = {"d": 1, "w": 7, "m": 30, "y": 365}


@dataclass
class Entry:
    """One recorded prompt, with where it landed."""
    sha: str
    receipt: Receipt
    shared: bool = False  # only in the mirror, so somebody else's (redacted)
    author: str = ""
    subject: str = ""

    @property
    def prompt(self):
        return self.receipt.prompt

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.receipt.files]


def _note_blobs(repo: Path, ref: str) -> dict[str, str]:
    """{commit sha: note blob sha} for a whole notes ref, in one call."""
    try:
        listing = git(repo, "ls-tree", "-r", ref)
    except GitError:
        return {}  # ref does not exist
    blobs = {}
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            # Notes fan out as ab/cdef...; stripping the separators rebuilds
            # the commit sha the note belongs to.
            blobs[path.replace("/", "")] = parts[2]
    return blobs


def _read_blobs(repo: Path, shas: list[str]) -> dict[str, str]:
    """Contents of many blobs in one `cat-file --batch`."""
    if not shas:
        return {}
    raw = git_bytes(repo, "cat-file", "--batch",
                    input_bytes=("\n".join(shas) + "\n").encode())
    out, pos = {}, 0
    for sha in shas:
        newline = raw.find(b"\n", pos)
        if newline < 0:
            break
        header = raw[pos:newline].decode("utf-8", "replace").split()
        pos = newline + 1
        if len(header) < 3:
            continue  # "<sha> missing" carries no body to skip past
        size = int(header[2])
        out[sha] = raw[pos:pos + size].decode("utf-8", "replace")
        pos += size + 1  # git writes a newline after the body
    return out


def _commit_meta(repo: Path) -> dict[str, tuple[str, str]]:
    """{sha: (author, subject)} for reachable commits, in one call. A commit
    orphaned by a rewrite simply has no metadata, which is honest."""
    try:
        out = git(repo, "log", "--all", "--format=%H%x1f%an%x1f%s")
    except GitError:
        return {}
    meta = {}
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            meta[parts[0]] = (parts[1], parts[2])
    return meta


def _entries_for(repo: Path, ref: str, shared: bool) -> list[Entry]:
    blobs = _note_blobs(repo, ref)
    bodies = _read_blobs(repo, list(blobs.values()))
    entries = []
    for commit_sha, blob_sha in blobs.items():
        for receipt in notes.parse(bodies.get(blob_sha, "")):
            entries.append(Entry(commit_sha, receipt, shared=shared))
    return entries


def load(repo: Path) -> list[Entry]:
    """Every recorded prompt, newest first.

    Our own record wins over the mirror for the same prompt, so the author
    sees what they typed rather than the redacted copy they published.
    """
    entries = _entries_for(repo, notes.NOTES_REF, shared=False)
    seen = {e.prompt.id for e in entries}
    entries += [e for e in _entries_for(repo, notes.SHARED_REF, shared=True)
                if e.prompt.id not in seen]

    meta = _commit_meta(repo)
    for e in entries:
        e.author, e.subject = meta.get(e.sha, ("", ""))
    entries.sort(key=lambda e: e.prompt.timestamp, reverse=True)
    return entries


def parse_when(value: str) -> datetime:
    """An ISO date, or a relative age like `7d`, `2w`, `3m`."""
    relative = _RELATIVE.match(value.strip())
    if relative:
        days = int(relative.group(1)) * _UNITS[relative.group(2).lower()]
        return datetime.now(timezone.utc) - timedelta(days=days)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class Query:
    text: str | None = None
    regex: bool = False
    path: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    model: str | None = None
    author: str | None = None
    mine: bool = False  # exclude prompts that only came from the mirror


def _matches_path(entry: Entry, pattern: str) -> bool:
    for path in entry.paths:
        if fnmatch.fnmatch(path, pattern) or pattern.lower() in path.lower():
            return True
    return False


def search(entries: list[Entry], query: Query) -> list[Entry]:
    matcher = None
    if query.text:
        matcher = (re.compile(query.text, re.I) if query.regex
                   else re.compile(re.escape(query.text), re.I))

    hits = []
    for e in entries:
        if matcher and not matcher.search(e.prompt.text):
            continue
        if query.path and not _matches_path(e, query.path):
            continue
        if query.since and e.prompt.timestamp < query.since:
            continue
        if query.until and e.prompt.timestamp > query.until:
            continue
        if query.model and query.model.lower() not in e.prompt.model.lower():
            continue
        if query.author and query.author.lower() not in e.author.lower():
            continue
        if query.mine and e.shared:
            continue
        hits.append(e)
    return hits, matcher


def to_json(hits: list[Entry]) -> dict:
    return {
        "count": len(hits),
        "prompts": [
            {
                "commit": e.sha,
                "author": e.author,
                "subject": e.subject,
                "shared": e.shared,
                "prompt": e.prompt.to_dict(),
                "files": [
                    {"path": f.path, "ranges": [list(r) for r in f.ranges]}
                    for f in e.receipt.files
                ],
            }
            for e in hits
        ],
    }
