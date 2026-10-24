"""Attach staged receipts to commits as git notes under refs/notes/pblame.

Notes travel with the repo, need no backend, and never modify commit
objects. Payload: {"version": 1, "receipts": [...]}.
"""

import copy
import dataclasses
import json
from pathlib import Path

from . import staging
from .models import FileChange, Receipt
from .snapshot import (
    GitError,
    commit_paths,
    diff_hunks,
    file_kinds,
    git,
    hunk_offsets,
    renames,
    snapshot_tree,
    touched_paths,
)

NOTES_REF = "refs/notes/pblame"              # local, verbatim, never pushed
SHARED_REF = "refs/notes/pblame-shared"      # redacted mirror; this is what travels
FETCH_REF = "refs/notes/pblame-remote"       # scratch landing spot for a fetch


VERSION_LINE = '{"pblame":1}'


def parse(text: str) -> list[Receipt]:
    """Receipts from a note body, in either format.

    Current format is JSONL: a version line, then one compact receipt per
    line. That makes `git notes merge --strategy=union` a correct merge, since
    git's merge strategies are line-based — a line-wise union of two
    pretty-printed JSON documents would not be valid JSON.
    """
    text = text.strip()
    if not text:
        return []

    # Legacy: a single pretty-printed {"version": 1, "receipts": [...]}.
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, dict) and "receipts" in whole:
        return fold(_receipts_from(whole["receipts"]))

    objects = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # a conflicted or foreign line must not lose the rest
        if isinstance(obj, dict) and "prompt" in obj:
            objects.append(obj)
    return fold(_receipts_from(objects))


def _receipts_from(objects: list) -> list[Receipt]:
    out = []
    for obj in objects:
        try:
            out.append(Receipt.from_dict(obj))
        except (KeyError, TypeError, ValueError):
            continue  # skip what we cannot read rather than losing the note
    return out


def fold(receipts: list[Receipt]) -> list[Receipt]:
    """Collapse copies of one prompt, unioning ranges per path.

    A union-merged note legitimately holds the same prompt twice: attach
    splits a receipt across commits by file, and two developers can each
    hold a different half.
    """
    out: list[Receipt] = []
    by_id: dict[str, Receipt] = {}
    for r in receipts:
        if r.prompt.id in by_id:
            _absorb(by_id[r.prompt.id], r)
        else:
            out.append(r)
            by_id[r.prompt.id] = r
    return out


def all_refs(repo: Path) -> list[str]:
    """Every pblame notes ref that exists.

    Enumerated rather than listed by name: `uninstall --purge` once deleted
    only the ref the code knew about first and left the redacted mirror behind,
    still holding every prompt. A ref added later must not be missable the same
    way. Other tools' notes refs are left alone.
    """
    try:
        out = git(repo, "for-each-ref", "--format=%(refname)", "refs/notes/")
    except GitError:
        return []
    return [r for r in out.splitlines()
            if r == NOTES_REF or r.startswith(NOTES_REF + "-")]


def read(repo: Path, sha: str, ref: str = NOTES_REF) -> list[Receipt]:
    try:
        return parse(git(repo, "notes", "--ref", ref, "show", sha, strip=False))
    except GitError:
        return []  # no note on this commit


def read_merged(repo: Path, sha: str) -> list[Receipt]:
    """Everything known about a commit: our verbatim record plus whatever
    teammates shared. Local comes first, so where both hold the same prompt
    the unredacted text wins."""
    return fold(read(repo, sha, NOTES_REF) + read(repo, sha, SHARED_REF))


def commits_with_notes(repo: Path, ref: str = NOTES_REF) -> list[str]:
    try:
        listed = git(repo, "notes", "--ref", ref, "list")
    except GitError:
        return []
    return [p[1] for p in (l.split() for l in listed.splitlines()) if len(p) > 1]


def serialize(receipts: list[Receipt]) -> str:
    # sort_keys makes each line byte-stable, so cat_sort_uniq can dedup them.
    lines = [VERSION_LINE] + [
        json.dumps(r.to_dict(), separators=(",", ":"), sort_keys=True)
        for r in receipts
    ]
    return "\n".join(lines) + "\n"


def signature(receipts: list[Receipt]) -> tuple:
    """Order-independent identity of a note's contents, for deciding whether
    a write would change anything."""
    return tuple(sorted(
        json.dumps(r.to_dict(), separators=(",", ":"), sort_keys=True)
        for r in receipts))


def write(repo: Path, sha: str, receipts: list[Receipt], ref: str = NOTES_REF) -> None:
    git(repo, "notes", "--ref", ref, "add", "-f", "-F", "-", sha,
        input_text=serialize(receipts))


def _union_ranges(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(a + b):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _absorb(target: Receipt, source: Receipt) -> None:
    """Fold source's files into target's, unioning ranges per path."""
    by_path = {f.path: f for f in target.files}
    for f in source.files:
        if f.path in by_path:
            by_path[f.path].ranges = _union_ranges(by_path[f.path].ranges, f.ranges)
        else:
            target.files.append(f)
            by_path[f.path] = f


def merge_into(repo: Path, sha: str, receipts: list[Receipt],
               ref: str = NOTES_REF) -> None:
    """Add receipts to a commit's note.

    The same prompt can legitimately reach one commit twice: attach splits a
    receipt across commits by file, and a later squash reunites those
    commits. Dropping the second copy would lose its files, so copies of one
    prompt are merged, not deduplicated.
    """
    existing = read(repo, sha, ref)
    by_id = {r.prompt.id: r for r in existing}
    for r in receipts:
        if r.prompt.id in by_id:
            _absorb(by_id[r.prompt.id], r)
        else:
            existing.append(r)
            by_id[r.prompt.id] = r
    if existing:
        write(repo, sha, existing, ref)


def remove(repo: Path, sha: str, ref: str = NOTES_REF) -> None:
    try:
        git(repo, "notes", "--ref", ref, "remove", sha)
    except GitError:
        pass  # nothing there to remove


def file_changes(repo: Path, pre: str, post: str) -> list[FileChange]:
    """Every path a turn touched, with its line ranges, and for a path left
    with none, which of the reasons it was. Shared by both places a receipt
    gets closed, so they cannot drift apart."""
    hunks = diff_hunks(repo, pre, post)
    kinds = file_kinds(repo, pre, post)
    changes = []
    for path in sorted(touched_paths(repo, pre, post)):
        ranges = hunks.get(path, [])
        kind, source = kinds.get(path, (None, None))
        if kind is None and not ranges:
            kind = "lines_removed"  # still there, only shorter
        changes.append(FileChange(path=path, ranges=ranges, kind=kind, renamed_from=source))
    return changes


def _drop_ignored(repo: Path, receipts: list[Receipt]) -> None:
    """Parts for paths git now ignores can never be committed, so they would
    wait in staging forever. Tracked files are never reported as ignored, so
    this only ever drops output that was never going to be committed."""
    paths = sorted({f.path for r in receipts if not r.is_open for f in r.files})
    if not paths:
        return
    try:
        out = git(repo, "check-ignore", "--stdin", input_text="\n".join(paths) + "\n")
    except GitError:
        return  # exit 1 means nothing is ignored
    ignored = set(out.splitlines())
    for r in receipts:
        if not r.is_open:
            r.files = [f for f in r.files if f.path not in ignored]
    receipts[:] = [r for r in receipts if r.is_open or r.files]


def _close_orphans(repo: Path, state: staging.StagingState) -> None:
    """Close receipts a dead session left open.

    `find_open` matches on session_id, so a receipt orphaned by an interrupt
    plus a session change would otherwise stay open forever and never attach.

    An orphan's work ends where the *next* prompt began — not at the commit.
    Closing it against the commit tree would swallow every later prompt's
    work as its own. Ranges computed at that boundary are then realigned to
    the current tree, which the closed receipts were already tracking.
    """
    now = None
    receipts = state.receipts
    for i, r in enumerate(receipts):
        if not r.is_open:
            continue
        if now is None:
            now = snapshot_tree(repo)
        end = receipts[i + 1].pre_tree if i + 1 < len(receipts) else now

        r.post_tree = end
        r.files = file_changes(repo, r.pre_tree, end)
        if end != now:
            staging.apply_renames([r], renames(repo, end, now))
            staging.apply_offsets([r], hunk_offsets(repo, end, now))
        if not r.prompt.model:
            # The turn never reached Stop, so no transcript was ever read.
            r.prompt = dataclasses.replace(r.prompt, model="unknown")


def _split(receipt: Receipt, paths: set[str]) -> tuple[Receipt | None, Receipt | None]:
    """Divide a receipt into (part inside this commit, part still pending).

    One prompt often edits files the developer commits separately; attaching
    it whole would drag ranges for files this commit never touched.
    """
    inside = [f for f in receipt.files if f.path in paths]
    outside = [f for f in receipt.files if f.path not in paths]
    if not inside:
        return None, receipt
    if not outside:
        return receipt, None
    here, pending = copy.deepcopy(receipt), copy.deepcopy(receipt)
    here.files, pending.files = inside, outside
    return here, pending


def attach_staged(repo: Path, sha: str = "HEAD") -> list[Receipt]:
    """Attach the parts of staged receipts that touch files this commit
    changed; returns what was attached. Anything else stays staged for a
    later commit. Receipts touching no file at all are dropped."""
    with staging.lock(repo):
        state = staging.load(repo)
        if not state.receipts:
            return []
        _close_orphans(repo, state)

        paths = commit_paths(repo, sha)
        attached, pending = [], []
        for r in state.receipts:
            here, rest = _split(r, paths)
            if here:
                attached.append(here)
            if rest and rest.files:
                pending.append(rest)

        full = git(repo, "rev-parse", sha)
        if attached:
            merge_into(repo, full, attached)

        state.receipts = pending
        # Whatever is still waiting has now been checked against this commit.
        for r in pending:
            state.checked_to[r.prompt.id] = full
        staging.save(repo, state)
        return attached


def head(repo: Path) -> str | None:
    """HEAD's commit, or None before the first commit."""
    try:
        return git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    except GitError:
        return None


def _is_ancestor(repo: Path, a: str, b: str) -> bool:
    try:
        git(repo, "merge-base", "--is-ancestor", a, b)
        return True
    except GitError:
        return False


def _commits_after(repo: Path, since: str | None, head_sha: str, receipt: Receipt) -> list[str]:
    """First-parent commits on HEAD made after `since`, oldest first.

    `since` is where this receipt was last checked — at first, HEAD when its
    prompt was submitted. If history was rewritten under it (an amend of
    that very commit, say), the merge base is the last point both agree on.
    """
    if since == head_sha:
        return []
    base = None
    if since:
        if _is_ancestor(repo, since, head_sha):
            base = since
        else:
            try:
                base = git(repo, "merge-base", since, head_sha)
            except GitError:
                base = None
    if base:
        return git(repo, "rev-list", "--first-parent", "--reverse", head_sha,
                   "--not", base).split()
    # No anchor: a receipt staged by an older pblame, or a prompt submitted
    # before the repo's first commit. Commit time is the best bound left.
    after = int(receipt.prompt.timestamp.timestamp())
    log = git(repo, "log", "--first-parent", "--format=%H %ct", "-n", "200", head_sha)
    picked = [sha for sha, ct in (line.split() for line in log.splitlines()) if int(ct) >= after]
    return list(reversed(picked))


def reconcile(repo: Path, state: staging.StagingState, coords: str | None) -> dict[str, list[Receipt]]:
    """Attach staged receipts to commits the post-commit hook never saw.

    `post-commit` is the fast path, not the only one: with `core.hooksPath`
    set — husky does it — git never runs it, and receipts waited forever
    while `doctor` called recording healthy. So every agent event, and every
    pblame command that reads the record, runs this too.

    Each closed receipt is checked against the first-parent commits made
    after its prompt began and not checked before; each file's part goes to
    the oldest such commit that changed it — what post-commit would have
    done at the time. Ranges are realigned from `coords`, the tree the
    staged ranges are expressed in, to the commit's own tree.

    Open receipts are left alone: another session may be mid-turn, and
    closing its receipt here would cut that turn short.
    """
    head_sha = head(repo)
    if head_sha is None:
        return {}
    if state.last_head and state.last_head != head_sha:
        _follow_rewrites(repo, state.last_head, head_sha)
    state.last_head = head_sha
    changed: dict[str, set[str]] = {}
    attached: dict[str, list[Receipt]] = {}
    kept: list[Receipt] = []
    for receipt in state.receipts:
        if receipt.is_open:
            kept.append(receipt)
            continue
        rest: Receipt | None = receipt
        since = state.checked_to.get(receipt.prompt.id)
        for sha in _commits_after(repo, since, head_sha, receipt):
            if sha not in changed:
                changed[sha] = commit_paths(repo, sha)
            here, rest = _split(rest, changed[sha])
            if here:
                if coords:
                    staging.apply_offsets([here], hunk_offsets(repo, coords, sha))
                attached.setdefault(sha, []).append(here)
            if rest is None or not rest.files:
                break
        if rest is not None and rest.files:
            kept.append(rest)
            state.checked_to[rest.prompt.id] = head_sha
    _drop_ignored(repo, kept)
    for sha, receipts in attached.items():
        merge_into(repo, sha, receipts)
    state.receipts = kept
    return attached


_FIXUP_PREFIXES = ("fixup! ", "squash! ", "amend! ")


def _subject_key(subject: str) -> str:
    while subject.startswith(_FIXUP_PREFIXES):
        subject = subject.split(" ", 1)[1]
    return subject


def _patch_ids(repo: Path, shas: list[str]) -> dict[str, str]:
    """commit -> stable patch id. Merges have no patch and are absent."""
    if not shas:
        return {}
    patches = git(repo, "log", "--no-walk", "--no-color", "-p", *shas, strip=False)
    out = git(repo, "patch-id", "--stable", input_text=patches)
    return {sha: pid for pid, sha in (line.split() for line in out.splitlines())}


def _subjects(repo: Path, shas: list[str]) -> dict[str, str]:
    if not shas:
        return {}
    out = git(repo, "log", "--no-walk", "--format=%H%x09%s", *shas)
    return dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)


def _follow_rewrites(repo: Path, old_head: str, head_sha: str) -> int:
    """Move notes off commits an amend, rebase or squash replaced, when the
    post-rewrite hook that normally does it never ran.

    A commit counts as rewritten once no local branch and not HEAD reaches
    it. That is what separates a rewrite from a branch switch (the old tip
    is still on its branch) and a cherry-pick (the original is still live),
    and it still catches amending a pushed commit, which only the remote
    branch reaches.

    Each such commit with a note moves to its replacement among the new
    commits: identical changes first (patch-id: a clean rebase, a reworded
    message), then the same subject once fixup!/squash! is dropped (an
    amend that changed content, a squash). Ambiguity moves nothing — a note
    on the wrong commit is worse than an orphan, which doctor reports.
    """
    if _is_ancestor(repo, old_head, head_sha):
        return 0  # history only moved forward
    dropped = git(repo, "rev-list", old_head, "--not", "--branches", "HEAD").split()
    if not dropped:
        return 0
    noted = set()
    for ref in (NOTES_REF, SHARED_REF):
        noted.update(commits_with_notes(repo, ref))
    orphans = [sha for sha in dropped if sha in noted]
    if not orphans:
        return 0
    fresh = git(repo, "rev-list", "-n", "500", head_sha, "--not", old_head).split()
    if not fresh:
        return 0

    by_patch: dict[str, list[str]] = {}
    for sha, pid in _patch_ids(repo, fresh).items():
        by_patch.setdefault(pid, []).append(sha)
    by_subject: dict[str, list[str]] = {}
    for sha, subject in _subjects(repo, fresh).items():
        by_subject.setdefault(_subject_key(subject), []).append(sha)
    old_patch = _patch_ids(repo, orphans)
    old_subject = _subjects(repo, orphans)

    moved = 0
    for sha in orphans:
        same = by_patch.get(old_patch.get(sha, ""), [])
        if len(same) != 1:
            same = by_subject.get(_subject_key(old_subject.get(sha, "")), [])
        if len(same) == 1:
            moved += remap_all(repo, sha, same[0])
    return moved


def reconcile_now(repo: Path) -> None:
    """`reconcile` for a pblame command about to read the record. Does nothing
    in a repo pblame has never recorded in, rather than creating state there."""
    if not (repo / ".git" / "pblame" / "staging.json").exists():
        return
    with staging.lock(repo):
        state = staging.load(repo)
        reconcile(repo, state, state.last_tree)
        staging.save(repo, state)


def remap(repo: Path, old_sha: str, new_sha: str, ref: str = NOTES_REF) -> int:
    """Move a note from a rewritten commit onto its replacement, shifting
    ranges by whatever the rewrite changed. Returns receipts carried over.

    Without this, amend/rebase/squash strands every note on a commit no
    longer reachable, silently losing the attribution.
    """
    receipts = read(repo, old_sha, ref)
    if not receipts:
        return 0
    staging.apply_offsets(receipts, hunk_offsets(repo, old_sha, new_sha))
    merge_into(repo, new_sha, receipts, ref)
    remove(repo, old_sha, ref)
    return len(receipts)


def remap_all(repo: Path, old_sha: str, new_sha: str) -> int:
    """Remap every ref that has a note for the rewritten commit.

    `remap` took a ref and the hook never passed one, so an amend moved the
    local note and left the mirror holding a note on a commit that no longer
    exists — unreachable entries nobody would ever collect, and a shared
    record that disagreed with the local one after any rewrite.

    Counts only the local record, so the number reported to the developer is
    the number of their prompts that moved, not double.
    """
    moved = 0
    for ref in all_refs(repo):
        if ref == FETCH_REF:
            continue  # scratch space; the next fetch replaces it wholesale
        carried = remap(repo, old_sha, new_sha, ref)
        if ref == NOTES_REF:
            moved = carried
    return moved
