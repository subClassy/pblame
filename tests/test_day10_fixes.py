"""Regressions for what building the site found (findings 20-28)."""

import time

import pytest
from conftest import run_git

from pblame import doctor, git_hooks, notes, staging
from pblame.adapters import claude_code
from pblame.cli import main
from pblame.snapshot import git


def submit(repo, prompt, session="s1"):
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": session, "prompt": prompt})


def stop(repo, session="s1"):
    claude_code.handle({"hook_event_name": "Stop", "cwd": str(repo),
                        "session_id": session, "transcript_path": None})


def turn(repo, prompt, path, body, session="s1"):
    submit(repo, prompt, session)
    (repo / path).write_text(body)
    stop(repo, session)


def commit(repo, message="work", *extra):
    run_git(repo, "add", "-A")
    run_git(repo, *extra, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def texts_on(repo, sha):
    return sorted(r.prompt.text for r in notes.read(repo, sha))


@pytest.fixture
def husky(repo):
    """A repo where git ignores .git/hooks, as husky arranges with
    core.hooksPath. Our hooks are installed but never run."""
    (repo / "base.txt").write_text("base\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    claude_code.install(repo)
    git_hooks.install_hooks(repo)
    (repo / ".husky").mkdir()
    run_git(repo, "config", "core.hooksPath", ".husky")
    return repo


# --- 20. core.hooksPath must not switch attribution off -------------------

def test_the_post_commit_hook_really_does_not_fire_under_hookspath(husky):
    """Pins the premise: without this, every test below passes for nothing."""
    turn(husky, "add a line", "a.py", "one\n")
    sha = commit(husky)
    assert notes.read(husky, sha) == []
    assert staging.load(husky).receipts, "the receipt should still be waiting"


def test_a_commit_made_without_hooks_is_attributed_at_the_next_prompt(husky):
    turn(husky, "add a line", "a.py", "one\n")
    sha = commit(husky)
    submit(husky, "next thing")
    assert texts_on(husky, sha) == ["add a line"]


def test_each_receipt_lands_on_its_own_commit_when_both_happen_unseen(husky):
    """Two commits between agent events, the same file both times: each
    prompt belongs to the commit made after it, not the first one that
    happens to touch the path."""
    turn(husky, "first prompt", "a.py", "one\n")
    first = commit(husky, "first")
    turn(husky, "second prompt", "a.py", "one\ntwo\n")
    second = commit(husky, "second")
    submit(husky, "and then")

    assert texts_on(husky, first) == ["first prompt"]
    assert texts_on(husky, second) == ["second prompt"]


def test_a_commit_the_agent_makes_mid_turn_is_attributed_at_stop(husky):
    """Agents commit too. The commit lands while the turn is open, so the
    receipt can only be attached once Stop has closed it."""
    submit(husky, "write it and commit it")
    (husky / "a.py").write_text("one\n")
    sha = commit(husky, "agent commit")
    stop(husky)
    assert texts_on(husky, sha) == ["write it and commit it"]


def test_blame_attributes_commits_the_hooks_missed(husky, monkeypatch, capsys):
    turn(husky, "add a line", "a.py", "one\n")
    commit(husky)
    monkeypatch.chdir(husky)
    assert main(["blame", "a.py", "--no-color"]) == 0
    assert "add a line" in capsys.readouterr().out


def test_another_sessions_open_turn_is_left_alone(husky):
    """Attaching runs on every agent event now. Closing someone else's
    open receipt there would cut their turn short."""
    submit(husky, "long running", session="other")
    turn(husky, "quick one", "a.py", "one\n", session="mine")
    commit(husky)
    submit(husky, "next", session="mine")

    open_ = [r for r in staging.load(husky).receipts if r.is_open]
    assert [r.prompt.text for r in open_] == ["long running", "next"]


def test_a_part_never_committed_is_not_rechecked_against_old_commits(husky, monkeypatch):
    """Each receipt remembers how far it has been checked, so a file that is
    never committed does not cost one diff per commit on every agent event."""
    submit(husky, "touch two files")
    (husky / "a.py").write_text("one\n")
    (husky / "never.py").write_text("x\n")
    stop(husky)
    run_git(husky, "add", "a.py")
    run_git(husky, "commit", "-q", "-m", "only a.py")
    for n in range(3):
        (husky / f"other{n}.txt").write_text(f"{n}\n")
        run_git(husky, "add", f"other{n}.txt")      # never.py stays uncommitted
        run_git(husky, "commit", "-q", "-m", f"c{n}")
    submit(husky, "look once")
    assert any(f.path == "never.py" for r in staging.load(husky).receipts for f in r.files), \
        "premise: never.py's part must still be waiting"

    seen = []
    real = notes.commit_paths
    monkeypatch.setattr(notes, "commit_paths", lambda r, s: (seen.append(s), real(r, s))[1])
    submit(husky, "look again")
    assert seen == [], f"re-checked {len(seen)} commits already checked"


def test_doctor_says_git_hooks_are_inactive_and_what_happens_instead(husky):
    checks = doctor.run(husky)
    hooks = [c for c in checks if "post-commit" in c.label]
    assert hooks and all(c.status == doctor.WARN for c in hooks), hooks
    assert any("core.hooksPath" in c.detail for c in hooks)
    assert not [c for c in hooks if c.status == doctor.PASS]


def test_normal_repos_still_attach_at_commit_time(repo):
    (repo / "base.txt").write_text("base\n")
    commit(repo, "base")
    claude_code.install(repo)
    git_hooks.install_hooks(repo)
    turn(repo, "add a line", "a.py", "one\n")
    sha = commit(repo)
    assert texts_on(repo, sha) == ["add a line"]


# --- 20, continued: rewrites the post-rewrite hook never saw ---------------

def test_an_amend_without_hooks_moves_the_note_at_the_next_prompt(husky):
    turn(husky, "add a line", "a.py", "one\n")
    old = commit(husky, "add a")
    submit(husky, "look")                         # attaches to `old`
    stop(husky)
    assert texts_on(husky, old) == ["add a line"]

    (husky / "a.py").write_text("one\nand more\n")
    run_git(husky, "commit", "-qa", "--amend", "-m", "add a")
    new = git(husky, "rev-parse", "HEAD")
    submit(husky, "after the amend")

    assert texts_on(husky, new) == ["add a line"]
    assert texts_on(husky, old) == []


def test_an_autosquash_without_hooks_lands_both_prompts_on_one_commit(husky, monkeypatch):
    turn(husky, "add a json flag", "a.py", "one\n")
    commit(husky, "envdiff: --json output")
    turn(husky, "make the json prettier", "a.py", "one\ntwo\n")
    run_git(husky, "add", "-A")
    run_git(husky, "commit", "-q", "--fixup", "HEAD")
    submit(husky, "look")
    stop(husky)

    monkeypatch.setenv("GIT_SEQUENCE_EDITOR", "true")
    run_git(husky, "rebase", "-q", "-i", "--autosquash", "HEAD~2")
    squashed = git(husky, "rev-parse", "HEAD")
    submit(husky, "after the squash")

    assert texts_on(husky, squashed) == ["add a json flag", "make the json prettier"]


def test_switching_branches_moves_nothing(husky):
    turn(husky, "on main", "a.py", "one\n")
    on_main = commit(husky, "main work")
    run_git(husky, "checkout", "-q", "-b", "feature")
    turn(husky, "on feature", "b.py", "two\n")
    on_feature = commit(husky, "feature work")
    submit(husky, "look")
    stop(husky)
    run_git(husky, "checkout", "-q", "main")
    submit(husky, "back on main")

    assert texts_on(husky, on_main) == ["on main"]
    assert texts_on(husky, on_feature) == ["on feature"]


def test_a_cherry_pick_leaves_the_original_its_note(husky):
    """Same patch-id on two live commits is a copy, not a rewrite."""
    run_git(husky, "checkout", "-q", "-b", "feature")
    turn(husky, "the fix", "fix.py", "fixed\n")
    original = commit(husky, "the fix")
    submit(husky, "look")
    stop(husky)
    run_git(husky, "checkout", "-q", "main")
    run_git(husky, "cherry-pick", original)
    submit(husky, "after the pick")

    assert texts_on(husky, original) == ["the fix"]


def test_an_ambiguous_match_is_left_alone(husky):
    """Two new commits with the dropped commit's subject: moving the note to
    either would be a guess. The orphan stays, and doctor reports it."""
    turn(husky, "first try", "a.py", "one\n")
    old = commit(husky, "wip")
    submit(husky, "look")
    stop(husky)
    run_git(husky, "reset", "-q", "--hard", "HEAD~1")
    (husky / "x.txt").write_text("x\n")
    commit(husky, "wip")
    (husky / "y.txt").write_text("y\n")
    commit(husky, "wip")
    submit(husky, "after")

    assert texts_on(husky, old) == ["first try"]


def test_init_says_git_hooks_will_not_run(repo, capsys):
    run_git(repo, "config", "core.hooksPath", ".husky")
    assert main(["init", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "core.hooksPath" in out and "next prompt" in out
