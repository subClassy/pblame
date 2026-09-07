from pblame.snapshot import diff_hunks, snapshot_tree


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
