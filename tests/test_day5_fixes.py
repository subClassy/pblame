"""Regressions for everything the day-5a stress test found."""

import json
import subprocess
import threading

from conftest import run_git

from pblame import git_hooks, notes, staging
from pblame.adapters import claude_code
from pblame.models import FileChange
from pblame.snapshot import commit_paths, diff_hunks, git, renames, snapshot_tree
from test_staging import make_receipt


def submit(repo, prompt, session="s1"):
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": session, "prompt": prompt})


def stop(repo, session="s1"):
    claude_code.handle({"hook_event_name": "Stop", "cwd": str(repo),
                        "session_id": session, "transcript_path": None})


def files_of(receipt):
    return {f.path: f.ranges for f in receipt.files}


def commit(repo, message="work"):
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


# --- 1. encoding: a non-cp1252 byte must not kill the recorder ------------

def test_emoji_in_tracked_file_does_not_break_recording(repo):
    (repo / "a.py").write_text('title = "\U0001f550 clock"\n', encoding="utf-8")
    submit(repo, "add a second line")
    (repo / "a.py").write_text('title = "\U0001f550 clock"\nx = 1\n', encoding="utf-8")
    stop(repo)

    receipts = staging.load(repo).receipts
    assert len(receipts) == 1 and not receipts[0].is_open
    assert files_of(receipts[0]) == {"a.py": [(2, 2)]}


# --- 2. rename must not steal the file ------------------------------------

def test_rename_is_detected_not_treated_as_rewrite(repo):
    (repo / "old.css").write_text("a\nb\nc\n")
    t1 = snapshot_tree(repo)
    (repo / "old.css").rename(repo / "new.css")
    t2 = snapshot_tree(repo)

    assert renames(repo, t1, t2) == {"old.css": "new.css"}
    assert diff_hunks(repo, t1, t2) == {}  # a pure rename changes no lines


def test_earlier_receipt_follows_a_rename(repo):
    submit(repo, "write the styles")
    (repo / "old.css").write_text("a\nb\nc\n")
    stop(repo)

    submit(repo, "rename it")
    (repo / "old.css").rename(repo / "new.css")
    stop(repo)

    by_prompt = {r.prompt.text: files_of(r) for r in staging.load(repo).receipts}
    # The original prompt keeps its lines under the new name...
    assert by_prompt["write the styles"] == {"new.css": [(1, 3)]}
    # ...and the renaming prompt does not claim any of them.
    assert by_prompt["rename it"].get("new.css", []) == []


# --- 3. deletion-only prompts stay in the record --------------------------

def test_deletion_only_prompt_is_recorded_and_attaches(repo):
    (repo / "a.py").write_text("keep\ndrop\n")
    commit(repo, "seed")

    submit(repo, "remove the second line")
    (repo / "a.py").write_text("keep\n")
    stop(repo)

    receipt = staging.load(repo).receipts[0]
    assert files_of(receipt) == {"a.py": []}  # touched, nothing survives

    sha = commit(repo, "drop a line")
    attached = notes.attach_staged(repo, sha)
    assert [r.prompt.text for r in attached] == ["remove the second line"]


def test_prompt_touching_nothing_is_still_dropped(repo):
    (repo / "a.py").write_text("x\n")
    submit(repo, "just a question")
    stop(repo)
    commit(repo, "unrelated")

    assert notes.attach_staged(repo) == []
    assert staging.load(repo).receipts == []


# --- 4. prompt text is the product, keep it clean -------------------------

def test_editor_context_is_stripped_from_prompts():
    raw = ('<ide_opened_file>The user opened the file c:\\x\\y.py in the IDE. This may '
           'or may not be related.</ide_opened_file>\nmake it look nicer')
    assert claude_code.clean_prompt(raw) == "make it look nicer"

    multi = ("<ide_selection>lines 18 to 18 from foo\nbar</ide_selection>\n"
             "Extract the date logic\n<system-reminder>noise</system-reminder>")
    assert claude_code.clean_prompt(multi) == "Extract the date logic"


def test_ordinary_prompt_survives_cleaning():
    text = "Use a <div id=\"date\"> and compare a < b"
    assert claude_code.clean_prompt(text) == text


# --- 5. orphans from a dead session must still attach ---------------------

def test_orphan_from_another_session_is_closed_at_commit(repo):
    submit(repo, "interrupted work", session="dead-session")
    (repo / "a.py").write_text("partial\n")
    # No Stop, and the session never returns.
    assert staging.load(repo).receipts[0].is_open

    sha = commit(repo, "commit anyway")
    attached = notes.attach_staged(repo, sha)
    assert [r.prompt.text for r in attached] == ["interrupted work"]
    assert files_of(attached[0]) == {"a.py": [(1, 1)]}


# --- 6. partial commits attach only the part that was committed -----------

def test_receipt_splits_across_partial_commits(repo):
    submit(repo, "touch both files")
    (repo / "a.py").write_text("aaa\n")
    (repo / "b.py").write_text("bbb\n")
    stop(repo)

    run_git(repo, "add", "a.py")
    run_git(repo, "commit", "-q", "-m", "only a")
    first = git(repo, "rev-parse", "HEAD")
    attached = notes.attach_staged(repo, first)

    assert files_of(attached[0]) == {"a.py": [(1, 1)]}  # b.py not dragged along
    pending = staging.load(repo).receipts
    assert files_of(pending[0]) == {"b.py": [(1, 1)]}

    second = commit(repo, "now b")
    notes.attach_staged(repo, second)
    assert files_of(notes.read(repo, second)[0]) == {"b.py": [(1, 1)]}
    assert staging.load(repo).receipts == []


# --- 7. rewriting history must carry notes forward ------------------------

def test_remap_carries_note_onto_an_amended_commit(repo):
    (repo / "a.py").write_text("one\ntwo\n")
    old = commit(repo, "first")
    r = make_receipt(text="wrote both lines")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 2)])]
    notes.write(repo, old, [r])

    # Amend, inserting a line above the recorded range.
    (repo / "a.py").write_text("zero\none\ntwo\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "--amend", "--no-edit")
    new = git(repo, "rev-parse", "HEAD")

    assert notes.remap(repo, old, new) == 1
    carried = notes.read(repo, new)
    assert [x.prompt.text for x in carried] == ["wrote both lines"]
    assert files_of(carried[0]) == {"a.py": [(2, 3)]}  # followed the insertion
    assert notes.read(repo, old) == []


def test_init_installs_the_post_rewrite_hook(repo):
    names = {p.name for p in git_hooks.install_hooks(repo)}
    assert names == {"post-commit", "post-rewrite"}
    assert "rewrite" in (repo / ".git" / "hooks" / "post-rewrite").read_text()


# --- 8. merge commits and concurrency -------------------------------------

def test_merge_commit_reports_its_changed_paths(repo):
    (repo / "base.py").write_text("base\n")
    commit(repo, "base")
    run_git(repo, "switch", "-qc", "feature")
    (repo / "feature.py").write_text("feature\n")
    commit(repo, "on branch")
    run_git(repo, "switch", "-q", "main")
    (repo / "main.py").write_text("main\n")
    commit(repo, "on main")
    run_git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge")

    # Without --diff-merges=first-parent this returns nothing at all.
    assert "feature.py" in commit_paths(repo, git(repo, "rev-parse", "HEAD"))


def test_receipt_attaches_to_a_merge_commit(repo):
    (repo / "base.py").write_text("base\n")
    commit(repo, "base")
    run_git(repo, "switch", "-qc", "feature")
    (repo / "feature.py").write_text("feature\n")
    commit(repo, "on branch")
    run_git(repo, "switch", "-q", "main")
    (repo / "main.py").write_text("main\n")
    commit(repo, "on main")

    r = make_receipt(text="branch work")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="feature.py", ranges=[(1, 1)])]
    staging.save(repo, staging.StagingState(receipts=[r]))

    run_git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge")
    sha = git(repo, "rev-parse", "HEAD")
    assert [x.prompt.text for x in notes.attach_staged(repo, sha)] == ["branch work"]


def test_concurrent_writers_do_not_lose_receipts(repo):
    (repo / "a.py").write_text("x\n")

    def record(n):
        with staging.lock(repo):
            state = staging.load(repo)
            state.receipts.append(make_receipt(text=f"prompt {n}"))
            staging.save(repo, state)

    threads = [threading.Thread(target=record, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(staging.load(repo).receipts) == 8


def test_lock_is_released_even_when_the_body_raises(repo):
    try:
        with staging.lock(repo):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert not (repo / ".git" / "pblame" / "staging.lock").exists()
    with staging.lock(repo):  # would hang or fail if still held
        pass
