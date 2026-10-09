import json

from conftest import run_git

from pblame import doctor, git_hooks, notes, staging
from pblame.adapters import claude_code
from pblame.cli import main
from pblame.models import FileChange
from pblame.snapshot import git
from test_staging import make_receipt


def test_uninstall_removes_hooks_and_keeps_history(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    main(["init"])
    r = make_receipt(text="kept")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    notes.write(repo, "HEAD", [r])
    staging.save(repo, staging.StagingState(receipts=[]))

    assert main(["uninstall"]) == 0

    assert not (repo / ".claude" / "settings.local.json").exists()
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    assert not (repo / ".git" / "hooks" / "post-rewrite").exists()
    # doctor now reports nothing is installed...
    assert any(c.status == doctor.FAIL for c in doctor.run(repo))
    # ...but the recorded history is untouched
    assert [x.prompt.text for x in notes.read(repo, "HEAD")] == ["kept"]
    assert (repo / ".git" / "pblame").exists()


def test_uninstall_purge_deletes_history(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    main(["init"])
    r = make_receipt(text="gone")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    notes.write(repo, "HEAD", [r])

    assert main(["uninstall", "--purge"]) == 0

    assert notes.read(repo, "HEAD") == []
    assert not (repo / ".git" / "pblame").exists()
    assert git(repo, "for-each-ref", "refs/notes/") == ""


def test_uninstall_preserves_other_hooks_and_settings(repo):
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    (hooks_dir / "post-commit").write_text("#!/bin/sh\necho user-hook\n")
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]},
    }))
    claude_code.install(repo)
    git_hooks.install_hooks(repo)

    claude_code.uninstall(repo)
    git_hooks.uninstall_hooks(repo)

    remaining = json.loads(settings.read_text())
    assert remaining["model"] == "opus"
    commands = [h["command"] for e in remaining["hooks"]["Stop"] for h in e["hooks"]]
    assert commands == ["echo mine"]
    hook = (hooks_dir / "post-commit").read_text()
    assert "echo user-hook" in hook and "pblame" not in hook
    assert not (hooks_dir / "post-rewrite").exists()  # was ours alone


def test_uninstall_is_safe_to_run_twice(repo, monkeypatch):
    monkeypatch.chdir(repo)
    main(["init"])
    assert main(["uninstall"]) == 0
    assert main(["uninstall"]) == 0


def pblame_note_refs(repo):
    """Enumerated, not named — the point of the fix."""
    out = git(repo, "for-each-ref", "--format=%(refname)", "refs/notes/")
    return [r for r in out.splitlines() if "pblame" in r]


def test_purge_deletes_every_pblame_ref_including_the_mirror(repo, monkeypatch):
    """--purge once reported that every prompt was gone while the redacted
    mirror kept a full copy of the text."""
    monkeypatch.chdir(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    main(["init"])

    r = make_receipt(text="a prompt nobody should find afterwards")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    for ref in (notes.NOTES_REF, notes.SHARED_REF, notes.FETCH_REF):
        notes.write(repo, "HEAD", [r], ref)
    assert len(pblame_note_refs(repo)) == 3

    assert main(["uninstall", "--purge"]) == 0

    assert pblame_note_refs(repo) == []
    # And nothing readable is left anywhere in the notes namespace.
    for ref in (notes.NOTES_REF, notes.SHARED_REF, notes.FETCH_REF):
        assert notes.read(repo, "HEAD", ref) == []


def test_purge_leaves_another_tools_notes_alone(repo, monkeypatch):
    monkeypatch.chdir(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    main(["init"])
    run_git(repo, "notes", "--ref", "refs/notes/commits", "add", "-m", "someone else's note")

    main(["uninstall", "--purge"])

    assert "refs/notes/commits" in git(repo, "for-each-ref", "--format=%(refname)",
                                      "refs/notes/")


def test_all_refs_reports_what_exists(repo):
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    assert notes.all_refs(repo) == []

    r = make_receipt(text="one")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    notes.write(repo, "HEAD", [r])
    assert notes.all_refs(repo) == [notes.NOTES_REF]

    notes.write(repo, "HEAD", [r], notes.SHARED_REF)
    assert set(notes.all_refs(repo)) == {notes.NOTES_REF, notes.SHARED_REF}
