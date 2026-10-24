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
