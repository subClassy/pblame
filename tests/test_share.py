"""Two developers, one remote, nobody loses work."""

import json
import subprocess

import pytest
from conftest import run_git

from pblame import config, notes, share
from pblame.adapters import claude_code
from pblame.snapshot import git


def enable_sharing(repo, **extra):
    (repo / config.FILENAME).write_text(json.dumps({"share": {"enabled": True, **extra}}))


def cfg_of(repo):
    return config.load(repo)


def clone(origin, dest, name):
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True)
    run_git(dest, "config", "user.email", f"{name}@e.com")
    run_git(dest, "config", "user.name", name)
    enable_sharing(dest)
    return dest


@pytest.fixture
def origin(tmp_path, repo):
    """A bare remote with one commit, plus `repo` wired to push to it."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    (repo / "app.py").write_text("base\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    run_git(repo, "remote", "add", "origin", str(bare))
    run_git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    enable_sharing(repo)
    return bare


def push_code(repo):
    """Share the commits too: notes are keyed by sha, so without this a clone
    would hold notes for commits it does not have — a test that passes for
    the wrong reason."""
    run_git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")


def record(repo, prompt, path="app.py", body=None, session="s"):
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": session, "prompt": prompt})
    if body is not None:
        (repo / path).write_text(body)
    claude_code.handle({"hook_event_name": "Stop", "cwd": str(repo),
                        "session_id": session, "transcript_path": None})
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", prompt[:40])
    notes.attach_staged(repo)
    return git(repo, "rev-parse", "HEAD")


# --- consent ------------------------------------------------------------

def test_push_refuses_when_sharing_is_off(repo, origin):
    (repo / config.FILENAME).write_text(json.dumps({"share": {"enabled": False}}))
    record(repo, "add a helper", body="base\nhelper\n")

    with pytest.raises(share.ShareDisabled):
        share.push(repo, cfg_of(repo))
    # and nothing reached the remote
    assert notes.NOTES_REF not in git(origin, "for-each-ref")


def test_dry_run_sends_nothing_and_shows_the_redacted_text(repo, origin):
    record(repo, "deploy with AKIAIOSFODNN7EXAMPLE", body="base\nx\n")

    planned = share.plan(repo, cfg_of(repo))
    text = share.describe(planned)
    assert "[REDACTED_AWS_KEY]" in text
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "redacted: AWS_KEY" in text
    assert notes.NOTES_REF not in git(origin, "for-each-ref")


# --- the local record is never touched ----------------------------------

def test_local_record_stays_verbatim_after_push(repo, origin):
    sha = record(repo, "key is AKIAIOSFODNN7EXAMPLE", body="base\nx\n")
    share.push(repo, cfg_of(repo))

    assert "AKIAIOSFODNN7EXAMPLE" in notes.read(repo, sha)[0].prompt.text
    shared = notes.read(repo, sha, notes.SHARED_REF)
    assert "[REDACTED_AWS_KEY]" in shared[0].prompt.text
    assert shared[0].prompt.secrets == {"AWS_KEY": "CRITICAL"}  # says what was removed


# --- two developers -----------------------------------------------------

def test_second_developer_sees_the_first_developers_prompts(tmp_path, repo, origin):
    sha = record(repo, "write the base helper", body="base\nhelper\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    bob = clone(origin, tmp_path / "bob", "bob")
    share.pull(bob, cfg_of(bob))

    assert git(bob, "cat-file", "-t", sha) == "commit"  # bob really has the code
    assert [r.prompt.text for r in notes.read_merged(bob, sha)] == ["write the base helper"]


def test_concurrent_push_loses_nobodys_work(tmp_path, repo, origin):
    """The case blameprompt's force refspec destroys."""
    alice_sha = record(repo, "alice's prompt", body="base\nalice\n")
    share.push(repo, cfg_of(repo))

    bob = clone(origin, tmp_path / "bob", "bob")
    share.pull(bob, cfg_of(bob))
    bob_sha = record(bob, "bob's prompt", body="base\nalice\nbob\n")
    share.push(bob, cfg_of(bob))

    # Alice pushes again without having seen bob's commit: her push is
    # rejected, she merges, and both survive.
    record(repo, "alice's second prompt", body="base\nalice\nsecond\n")
    share.push(repo, cfg_of(repo))
    share.pull(repo, cfg_of(repo))

    everything = set()
    for sha in notes.commits_with_notes(repo, notes.SHARED_REF):
        everything |= {r.prompt.text for r in notes.read(repo, sha, notes.SHARED_REF)}
    assert {"alice's prompt", "bob's prompt", "alice's second prompt"} <= everything
    assert "bob's prompt" in {r.prompt.text for r in notes.read(repo, bob_sha, notes.SHARED_REF)}
    assert alice_sha  # referenced for clarity


def test_blame_shows_a_teammates_shared_prompt(tmp_path, repo, origin):
    from pblame import blame

    record(repo, "write the helper line", body="base\nhelper\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    bob = clone(origin, tmp_path / "bob", "bob")
    share.pull(bob, cfg_of(bob))

    owners = {l.receipt.prompt.text for l in blame.attribute(bob, "app.py") if l.receipt}
    assert owners == {"write the helper line"}


def test_pull_does_not_overwrite_local_verbatim_prompts(tmp_path, repo, origin):
    sha = record(repo, "secret AKIAIOSFODNN7EXAMPLE stays local", body="base\nx\n")
    share.push(repo, cfg_of(repo))
    # Pulling our own redacted copy back must not clobber the local record.
    share.pull(repo, cfg_of(repo))

    assert "AKIAIOSFODNN7EXAMPLE" in notes.read(repo, sha)[0].prompt.text
    # blame prefers the verbatim local copy over the redacted shared one
    merged = notes.read_merged(repo, sha)
    assert len(merged) == 1
    assert "AKIAIOSFODNN7EXAMPLE" in merged[0].prompt.text


def test_pull_with_no_remote_notes_is_harmless(tmp_path, repo, origin):
    assert share.pull(repo, cfg_of(repo)) == 0


def test_push_with_nothing_recorded_does_nothing(repo, origin):
    assert share.push(repo, cfg_of(repo)) == []
