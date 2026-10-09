"""Two developers, one remote, nobody loses work."""

import json
import subprocess

import pytest
from conftest import run_git

from pblame import config, git_hooks, notes, share
from pblame.adapters import claude_code
from pblame.models import FileChange
from test_staging import make_receipt
from pblame.snapshot import git


def enable_sharing(repo, **extra):
    (repo / config.LOCAL_FILENAME).write_text(json.dumps({"share": {"enabled": True, **extra}}))
    # `pblame share` does this too: without it `git add -A` commits a personal
    # file and the next teammate's pull hits an untracked-file conflict.
    git_hooks.ensure_ignored(repo, config.LOCAL_FILENAME)


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
    (repo / config.LOCAL_FILENAME).write_text(json.dumps({"share": {"enabled": False}}))
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


def test_show_includes_a_teammates_shared_prompts(tmp_path, repo, origin, capsys):
    from pblame.cli import main

    sha = record(repo, "alice wrote this", body="base\nhelper\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    bob = clone(origin, tmp_path / "bob", "bob")
    share.pull(bob, cfg_of(bob))

    import os
    cwd = os.getcwd()
    try:
        os.chdir(bob)
        assert main(["show", sha]) == 0
    finally:
        os.chdir(cwd)
    assert "alice wrote this" in capsys.readouterr().out


def test_editor_context_paths_do_not_leak_a_username(repo, origin):
    """Found on real data: the shared copy carried the Windows home path."""
    sha = record(repo, r"look at c:\Users\subCl\Documents\app.py", body="base\nx\n")
    share.push(repo, cfg_of(repo))

    shared = notes.read(repo, sha, notes.SHARED_REF)[0].prompt.text
    assert "subCl" not in shared
    assert "subCl" in notes.read(repo, sha)[0].prompt.text  # local keeps it


# --- the hooks do the sharing, so nobody has to remember ----------------

def test_git_push_shares_prompts_via_the_pre_push_hook(tmp_path, repo, origin):
    from pblame import git_hooks

    git_hooks.install_hooks(repo)
    sha = record(repo, "shared by the hook", body="base\nhooked\n")
    run_git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")  # fires pre-push

    # The notes ref reached the remote without anyone running `pblame push`.
    assert notes.NOTES_REF in git(origin, "for-each-ref")
    bob = clone(origin, tmp_path / "bob", "bob")
    share.pull(bob, cfg_of(bob))
    assert [r.prompt.text for r in notes.read_merged(bob, sha)] == ["shared by the hook"]


def test_pre_push_hook_is_silent_while_sharing_is_off(repo, origin):
    from pblame import git_hooks

    (repo / config.LOCAL_FILENAME).write_text(json.dumps({"share": {"enabled": False}}))
    git_hooks.install_hooks(repo)
    record(repo, "stays home", body="base\nx\n")
    run_git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")

    assert notes.NOTES_REF not in git(origin, "for-each-ref")
    log = repo / ".git" / "pblame" / "hook.log"
    assert not log.exists() or log.read_text().strip() == ""


def test_inner_notes_push_does_not_re_enter_the_hook(repo, origin):
    """--no-verify on the inner push is what stops infinite recursion."""
    from pblame import git_hooks

    git_hooks.install_hooks(repo)
    record(repo, "one prompt", body="base\nx\n")
    run_git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")

    log = repo / ".git" / "pblame" / "hook.log"
    assert not log.exists() or "recursion" not in log.read_text().lower()
    assert notes.NOTES_REF in git(origin, "for-each-ref")


def test_git_pull_fetches_teammates_prompts_via_post_merge(tmp_path, repo, origin):
    from pblame import git_hooks

    bob = clone(origin, tmp_path / "bob", "bob")
    git_hooks.install_hooks(bob)

    # Alice works *after* bob cloned, so his pull is a real merge. post-merge
    # does not fire on an already-up-to-date pull.
    sha = record(repo, "alice's later work", body="base\nalice\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    # A plain `git pull` should bring the prompts along with the code.
    run_git(bob, "pull", "-q", "--no-rebase", "origin", "main")

    assert [r.prompt.text for r in notes.read_merged(bob, sha)] == ["alice's later work"]


def test_doctor_only_demands_sharing_hooks_once_sharing_is_on(repo):
    from pblame import doctor

    claude_code.install(repo)
    git_hooks.install_post_commit(repo)  # the old two-hook world
    (repo / config.LOCAL_FILENAME).write_text(json.dumps({"share": {"enabled": False}}))
    by_label = {c.label: c for c in doctor.run(repo)}
    assert by_label["pre-push hook"].status == doctor.WARN

    enable_sharing(repo)
    by_label = {c.label: c for c in doctor.run(repo)}
    assert by_label["pre-push hook"].status == doctor.FAIL


# --- a push must not redo the whole history ------------------------------

def test_an_unchanged_push_writes_nothing(repo, origin):
    """Every push used to re-redact and rewrite every note, growing the
    mirror by one commit per recorded commit: 9s for a no-op at 60 commits."""
    for n in range(3):
        record(repo, f"prompt {n}", body="base\n" + "x\n" * (n + 1))
    share.push(repo, cfg_of(repo))
    after_first = git(repo, "rev-parse", notes.SHARED_REF)

    share.push(repo, cfg_of(repo))

    assert git(repo, "rev-parse", notes.SHARED_REF) == after_first
    assert [p.is_new for p in share.plan(repo, cfg_of(repo))] == [False] * 3


def test_only_the_new_commit_is_written(repo, origin):
    record(repo, "first prompt", body="base\none\n")
    share.push(repo, cfg_of(repo))
    record(repo, "second prompt", body="base\none\ntwo\n")

    planned = share.plan(repo, cfg_of(repo))
    fresh = [p for p in planned if p.is_new]
    assert len(planned) == 2 and len(fresh) == 1
    assert [r.prompt.text for r in fresh[0].receipts] == ["second prompt"]


def test_a_changed_redaction_pattern_is_applied_retroactively(repo, origin):
    """Skipping unchanged notes must not mean the mirror can never improve."""
    sha = record(repo, "ticket CUST-123456 came in", body="base\nx\n")
    share.push(repo, cfg_of(repo))
    assert "CUST-123456" in notes.read(repo, sha, notes.SHARED_REF)[0].prompt.text

    (repo / config.FILENAME).write_text(json.dumps({"redaction": {"custom_patterns": [
        {"pattern": r"CUST-\d{6,}", "replacement": "[REDACTED_CUSTOMER_ID]"}]}}))

    assert [p.is_new for p in share.plan(repo, cfg_of(repo))] == [True]
    share.push(repo, cfg_of(repo))
    assert "CUST-123456" not in notes.read(repo, sha, notes.SHARED_REF)[0].prompt.text


def test_plan_reads_the_history_in_a_constant_number_of_git_calls(repo, origin, monkeypatch):
    for n in range(4):
        record(repo, f"prompt {n}", body="base\n" + "y\n" * (n + 1))

    calls = []
    real_git, real_bytes = share.index.git, share.index.git_bytes
    monkeypatch.setattr(share.index, "git",
                        lambda *a, **k: (calls.append(a[1]), real_git(*a, **k))[1])
    monkeypatch.setattr(share.index, "git_bytes",
                        lambda *a, **k: (calls.append(a[1]), real_bytes(*a, **k))[1])

    share.plan(repo, cfg_of(repo))
    # ls-tree + cat-file per ref, and nothing per commit.
    assert len(calls) <= 4, calls


# --- a rewrite must not leave the mirror stale --------------------------

def test_a_rewrite_remaps_the_mirror_too(repo, origin):
    """remap took a ref and the hook never passed one, so an amend moved the
    local note and left the mirror pointing at a commit that no longer
    exists."""
    old = record(repo, "the only prompt", body="base\none\n")
    share.push(repo, cfg_of(repo))
    assert notes.read(repo, old, notes.SHARED_REF)

    (repo / "app.py").write_text("base\none\ntwo\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "--amend", "--no-edit")
    new = git(repo, "rev-parse", "HEAD")

    assert notes.remap_all(repo, old, new) == 1
    for ref in (notes.NOTES_REF, notes.SHARED_REF):
        assert notes.read(repo, old, ref) == [], f"{ref} still holds the orphan"
        assert [r.prompt.text for r in notes.read(repo, new, ref)] == ["the only prompt"]


def test_the_post_rewrite_hook_remaps_both_refs(repo, origin):
    """End to end through the real hook, not the function."""
    from pblame import git_hooks

    git_hooks.install_hooks(repo)
    old = record(repo, "shared then amended", body="base\none\n")
    share.push(repo, cfg_of(repo))

    (repo / "app.py").write_text("base\nchanged\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "--amend", "--no-edit")   # fires post-rewrite
    new = git(repo, "rev-parse", "HEAD")

    assert notes.read(repo, old, notes.SHARED_REF) == []
    assert [r.prompt.text for r in notes.read(repo, new, notes.SHARED_REF)] == \
        ["shared then amended"]


def test_remap_counts_only_the_developers_own_prompts(repo, origin):
    """Both refs move, but the message should not double-count."""
    old = record(repo, "one prompt", body="base\none\n")
    share.push(repo, cfg_of(repo))
    (repo / "app.py").write_text("base\ntwo\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "--amend", "--no-edit")

    assert notes.remap_all(repo, old, git(repo, "rev-parse", "HEAD")) == 1


def test_a_rejected_push_does_not_clobber_what_the_pull_brought_in(repo, origin):
    """stage used to merge against the live note; it now writes a list computed
    in advance. On the reject-pull-retry path that list predates the pull, so a
    teammate's entry for the same commit could be overwritten."""
    sha = record(repo, "alice's prompt", body="base\nalice\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    # A teammate adds a receipt to the *same* commit and pushes first, which is
    # what makes our push get rejected.
    theirs = make_receipt(text="teammate's prompt on the same commit")
    theirs.post_tree = "b" * 40
    theirs.files = [FileChange(path="app.py", ranges=[(2, 2)])]
    bare = origin
    run_git(repo, "fetch", str(bare), f"+{notes.NOTES_REF}:{notes.FETCH_REF}")
    run_git(repo, "update-ref", "refs/notes/tmp-theirs", notes.FETCH_REF)
    notes.merge_into(repo, sha, [theirs], "refs/notes/tmp-theirs")
    run_git(repo, "push", str(bare), f"refs/notes/tmp-theirs:{notes.NOTES_REF}")

    # Now we record more and push: rejected, pulled, retried.
    record(repo, "alice's second prompt", body="base\nalice\nmore\n")
    share.push(repo, cfg_of(repo))
    share.pull(repo, cfg_of(repo))

    shared = {r.prompt.text for r in notes.read(repo, sha, notes.SHARED_REF)}
    assert "alice's prompt" in shared
    assert "teammate's prompt on the same commit" in shared, \
        "the retry overwrote what the pull brought in"


def test_retry_keeps_a_teammates_entry_on_a_commit_we_also_changed(repo, origin):
    """The sharp version of the above: our note for that commit changed too, so
    stage does not skip it, and the list it writes predates the pull."""
    sha = record(repo, "alice's first", body="base\nalice\n")
    push_code(repo)
    share.push(repo, cfg_of(repo))

    # Teammate adds a receipt to the same commit and pushes first.
    theirs = make_receipt(text="teammate's prompt")
    theirs.post_tree = "b" * 40
    theirs.files = [FileChange(path="app.py", ranges=[(2, 2)])]
    run_git(repo, "fetch", str(origin), f"+{notes.NOTES_REF}:{notes.FETCH_REF}")
    run_git(repo, "update-ref", "refs/notes/tmp-theirs", notes.FETCH_REF)
    notes.merge_into(repo, sha, [theirs], "refs/notes/tmp-theirs")
    run_git(repo, "push", str(origin), f"refs/notes/tmp-theirs:{notes.NOTES_REF}")

    # And *our* note for that same commit also gains a receipt, so the mirror
    # is out of date for it and stage will not skip it.
    mine = make_receipt(text="alice's second on the same commit")
    mine.post_tree = "b" * 40
    mine.files = [FileChange(path="app.py", ranges=[(1, 1)])]
    notes.merge_into(repo, sha, [mine])

    share.push(repo, cfg_of(repo))      # rejected, pulled, retried
    share.pull(repo, cfg_of(repo))

    shared = {r.prompt.text for r in notes.read(repo, sha, notes.SHARED_REF)}
    assert "alice's first" in shared
    assert "alice's second on the same commit" in shared
    assert "teammate's prompt" in shared, "the retry overwrote the pulled entry"
