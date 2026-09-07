from conftest import run_git

from pblame import notes, staging
from pblame.models import FileChange
from pblame.snapshot import git
from test_staging import make_receipt


def commit_all(repo, message="commit"):
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def stage(repo, *receipts):
    staging.save(repo, staging.StagingState(receipts=list(receipts)))


def test_attach_and_read_roundtrip(repo):
    r = make_receipt(text="add greeting")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 2)])]
    stage(repo, r)

    (repo / "a.py").write_text("def greet():\n    return 'hi'\n")
    sha = commit_all(repo)

    attached = notes.attach_staged(repo)
    assert [a.prompt.text for a in attached] == ["add greeting"]
    assert notes.read(repo, sha) == [r]
    assert staging.load(repo).receipts == []


def test_attach_only_receipts_touching_commit_files(repo):
    committed = make_receipt(text="committed work")
    committed.post_tree = "b" * 40
    committed.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    pending = make_receipt(text="uncommitted work")
    pending.post_tree = "b" * 40
    pending.files = [FileChange(path="other.py", ranges=[(1, 1)])]
    stage(repo, committed, pending)

    (repo / "a.py").write_text("x\n")
    sha = commit_all(repo)

    attached = notes.attach_staged(repo)
    assert [a.prompt.text for a in attached] == ["committed work"]
    assert [a.prompt.text for a in notes.read(repo, sha)] == ["committed work"]
    # The receipt for the uncommitted file stays staged
    assert [r.prompt.text for r in staging.load(repo).receipts] == ["uncommitted work"]


def test_attach_drops_closed_receipts_with_no_files(repo):
    empty = make_receipt(text="just a question")
    empty.post_tree = "b" * 40
    stage(repo, empty)

    (repo / "a.py").write_text("x\n")
    commit_all(repo)

    assert notes.attach_staged(repo) == []
    assert staging.load(repo).receipts == []


def test_attach_merges_with_existing_note_dedup(repo):
    (repo / "a.py").write_text("x\n")
    sha = commit_all(repo)

    first = make_receipt(text="first")
    first.post_tree = "b" * 40
    first.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    stage(repo, first)
    notes.attach_staged(repo)

    # Same receipt staged again (e.g. hook re-run) plus a new one
    second = make_receipt(text="second")
    second.post_tree = "b" * 40
    second.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    stage(repo, first, second)
    notes.attach_staged(repo)

    assert [r.prompt.text for r in notes.read(repo, sha)] == ["first", "second"]
