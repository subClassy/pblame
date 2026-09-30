"""The note payload is JSONL so `git notes merge` works natively."""

import json

from conftest import run_git

from pblame import notes
from pblame.models import FileChange
from pblame.snapshot import git
from test_staging import make_receipt


def receipt(text, path, ranges):
    r = make_receipt(text=text)
    r.post_tree = "b" * 40
    r.files = [FileChange(path=path, ranges=ranges)]
    return r


def files_of(r):
    return {f.path: f.ranges for f in r.files}


def seed(repo):
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    return git(repo, "rev-parse", "HEAD")


def test_written_note_is_jsonl_with_a_version_line(repo):
    sha = seed(repo)
    notes.write(repo, sha, [receipt("one", "a.py", [(1, 1)]),
                            receipt("two", "a.py", [(2, 2)])])

    body = git(repo, "notes", "--ref", notes.NOTES_REF, "show", sha, strip=False)
    lines = [l for l in body.splitlines() if l.strip()]
    assert lines[0] == notes.VERSION_LINE
    assert len(lines) == 3
    for line in lines[1:]:
        assert "prompt" in json.loads(line)  # each receipt is one whole line


def test_roundtrip(repo):
    sha = seed(repo)
    written = [receipt("one", "a.py", [(1, 3), (7, 7)]), receipt("two", "b.py", [(4, 4)])]
    notes.write(repo, sha, written)
    assert notes.read(repo, sha) == written


def test_legacy_pretty_json_note_still_reads(repo):
    """History recorded before this change must keep working."""
    sha = seed(repo)
    old = receipt("recorded last week", "a.py", [(1, 2)])
    legacy = json.dumps({"version": 1, "receipts": [old.to_dict()]}, indent=2)
    git(repo, "notes", "--ref", notes.NOTES_REF, "add", "-f", "-F", "-", sha,
        input_text=legacy)

    assert notes.read(repo, sha) == [old]


def test_union_merged_note_reads_as_both_receipts(repo):
    """What git's union strategy produces: the two bodies concatenated."""
    mine = receipt("mine", "a.py", [(1, 1)])
    theirs = receipt("theirs", "b.py", [(2, 2)])
    merged = notes.serialize([mine]) + notes.serialize([theirs])

    parsed = notes.parse(merged)
    assert {r.prompt.text for r in parsed} == {"mine", "theirs"}


def test_union_merge_folds_one_prompt_split_across_developers(repo):
    """Attach splits a receipt by file; two people can hold different halves."""
    mine = receipt("shared prompt", "a.py", [(1, 1)])
    theirs = receipt("shared prompt", "b.py", [(2, 2)])
    theirs.prompt = mine.prompt  # same prompt id

    parsed = notes.parse(notes.serialize([mine]) + notes.serialize([theirs]))
    assert len(parsed) == 1
    assert files_of(parsed[0]) == {"a.py": [(1, 1)], "b.py": [(2, 2)]}


def test_garbage_lines_do_not_lose_the_rest(repo):
    good = receipt("survives", "a.py", [(1, 1)])
    body = notes.serialize([good]).replace(
        notes.VERSION_LINE, notes.VERSION_LINE + "\n<<<<<<< conflict marker")
    assert [r.prompt.text for r in notes.parse(body)] == ["survives"]


def test_empty_and_absent_notes(repo):
    sha = seed(repo)
    assert notes.read(repo, sha) == []      # no note at all
    assert notes.parse("") == []
    assert notes.parse(notes.VERSION_LINE) == []  # marker only


def test_git_notes_union_merge_really_works(repo):
    """The payoff: git itself merges two divergent notes refs without help."""
    sha = seed(repo)
    notes.write(repo, sha, [receipt("from A", "a.py", [(1, 1)])])
    run_git(repo, "update-ref", "refs/notes/pblame-a", "refs/notes/pblame")

    # Truly diverge: B's ref must not descend from A's, or git fast-forwards
    # and the merge is a no-op. Two developers produce exactly this shape.
    run_git(repo, "update-ref", "-d", "refs/notes/pblame")
    notes.write(repo, sha, [receipt("from B", "b.py", [(2, 2)])])

    run_git(repo, "-c", "user.email=t@e.com", "-c", "user.name=T",
            "notes", "--ref", notes.NOTES_REF,
            "merge", "--strategy=union", "refs/notes/pblame-a")

    assert {r.prompt.text for r in notes.read(repo, sha)} == {"from A", "from B"}
