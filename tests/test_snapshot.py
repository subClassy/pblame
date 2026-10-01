from pathlib import Path

from conftest import run_git

from pblame.snapshot import diff_hunks, git, snapshot_tree


def test_new_and_modified_files(repo):
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    t1 = snapshot_tree(repo)
    (repo / "a.py").write_text("one\nTWO\nthree\n")
    (repo / "b.py").write_text("x\ny\n")
    t2 = snapshot_tree(repo)

    hunks = diff_hunks(repo, t1, t2)
    assert hunks == {"a.py": [(2, 2)], "b.py": [(1, 2)]}


def test_identical_trees(repo):
    (repo / "a.py").write_text("one\n")
    t1 = snapshot_tree(repo)
    assert diff_hunks(repo, t1, t1) == {}


def test_deletions_contribute_no_ranges(repo):
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    (repo / "b.py").write_text("x\n")
    t1 = snapshot_tree(repo)
    (repo / "a.py").write_text("one\nthree\n")  # pure line deletion
    (repo / "b.py").unlink()  # file deletion
    t2 = snapshot_tree(repo)

    assert diff_hunks(repo, t1, t2) == {}


def test_gitignored_files_excluded(repo):
    (repo / ".gitignore").write_text("junk.txt\n")
    t1 = snapshot_tree(repo)
    (repo / "junk.txt").write_text("ignored\n")
    t2 = snapshot_tree(repo)

    assert diff_hunks(repo, t1, t2) == {}


def test_tracked_file_matching_an_ignore_rule_is_still_snapshotted(repo):
    """gitignore only applies to untracked files. A fresh temp index treated
    everything as untracked and silently dropped this one."""
    (repo / "generated.txt").write_text("v1\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "track it")
    (repo / ".gitignore").write_text("generated.txt\n")

    tree = snapshot_tree(repo)
    listed = git(repo, "ls-tree", "-r", "--name-only", tree).splitlines()
    assert "generated.txt" in listed

    # ...and a later change to it is still attributable
    (repo / "generated.txt").write_text("v1\nv2\n")
    assert diff_hunks(repo, tree, snapshot_tree(repo)) == {"generated.txt": [(2, 2)]}


def test_untracked_ignored_files_stay_out(repo):
    (repo / ".gitignore").write_text("junk.txt\n")
    before = snapshot_tree(repo)
    (repo / "junk.txt").write_text("noise\n")
    assert diff_hunks(repo, before, snapshot_tree(repo)) == {}


def test_staged_changes_do_not_distort_the_snapshot(repo):
    """The temp index is seeded from the real one, which may hold staged
    content; the snapshot must still describe the working tree."""
    (repo / "a.py").write_text("staged\n")
    run_git(repo, "add", "a.py")
    (repo / "a.py").write_text("staged\nthen edited\n")

    tree = snapshot_tree(repo)
    assert git(repo, "cat-file", "-p", f"{tree}:a.py") == "staged\nthen edited"


def test_a_corrupt_index_copy_falls_back_instead_of_failing(repo, monkeypatch):
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")

    import shutil as _shutil
    def torn(src, dst):
        Path(dst).write_bytes(b"DIRC\x00garbage")
    monkeypatch.setattr(_shutil, "copyfile", torn)

    assert len(snapshot_tree(repo)) == 40  # still produced a tree
