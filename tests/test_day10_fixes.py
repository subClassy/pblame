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


# --- 22. doctor must not blame recording for a sharing problem -------------

def _secret_repo(repo, disable=False):
    import json as _json
    from pblame import config
    (repo / "base.txt").write_text("base\n")
    commit(repo, "base")
    claude_code.install(repo)
    git_hooks.install_hooks(repo)
    (repo / config.LOCAL_FILENAME).write_text(_json.dumps({"share": {"enabled": True}}))
    if disable:
        (repo / config.FILENAME).write_text(_json.dumps(
            {"redaction": {"disable_patterns": ["AWS_KEY"]}}))
    turn(repo, "deploy with AKIAIOSFODNN7EXAMPLE please", "a.py", "one\n")


def test_a_sharing_failure_does_not_say_recording_is_unreliable(repo):
    """AWS_KEY is switched off before the prompt is even captured, so the
    capture-time scan never saw the key. doctor has to look again."""
    _secret_repo(repo, disable=True)
    checks = doctor.run(repo)
    secrets = {c.label: c for c in checks}["secrets in prompts"]
    assert secrets.status == doctor.FAIL, secrets
    assert "AWS_KEY" in secrets.detail

    text = doctor.render(checks, color=False)
    assert "Not recording reliably" not in text
    assert "Recording is live" in text and "1 sharing check failing" in text


def test_a_recording_failure_still_says_so(repo):
    _secret_repo(repo)
    (repo / ".git" / "pblame" / "hook.log").write_text("2026-10-24 boom\n")
    assert "Not recording reliably" in doctor.render(doctor.run(repo), color=False)


def test_one_prompt_contains_not_contain(repo):
    _secret_repo(repo)
    detail = {c.label: c.detail for c in doctor.run(repo)}["secrets in prompts"]
    assert detail.startswith("1 prompt contains "), detail


# --- 24, 25: what a file with no line ranges actually was ------------------

@pytest.fixture
def recorded(repo):
    """An ordinary repo: hooks installed and running."""
    (repo / "envfile.py").write_text("def load():\n    pass\n")
    (repo / "keep.py").write_text("a\nb\nc\n")
    commit(repo, "base")
    claude_code.install(repo)
    git_hooks.install_hooks(repo)
    return repo


def files_on(repo, sha):
    return {f.path: f for r in notes.read(repo, sha) for f in r.files}


def test_a_pure_rename_is_labelled_a_rename_not_a_removal(recorded, monkeypatch, capsys):
    submit(recorded, "rename envfile.py to loader.py")
    (recorded / "envfile.py").rename(recorded / "loader.py")
    stop(recorded)
    sha = commit(recorded, "rename")

    f = files_on(recorded, sha)["loader.py"]
    assert (f.kind, f.renamed_from) == ("renamed", "envfile.py")
    monkeypatch.chdir(recorded)
    main(["search", "rename", "--no-color"])
    out = capsys.readouterr().out
    assert "loader.py (renamed from envfile.py)" in out
    assert "(removed)" not in out


def test_a_deleted_file_is_labelled_deleted(recorded):
    submit(recorded, "delete it")
    (recorded / "envfile.py").unlink()
    stop(recorded)
    sha = commit(recorded, "delete")
    assert files_on(recorded, sha)["envfile.py"].label() == "(deleted)"


def test_lines_only_removed_is_not_called_a_removed_file(recorded, monkeypatch, capsys):
    submit(recorded, "drop the middle line")
    (recorded / "keep.py").write_text("a\nc\n")
    stop(recorded)
    sha = commit(recorded, "trim")
    assert files_on(recorded, sha)["keep.py"].label() == "(lines removed)"
    monkeypatch.chdir(recorded)
    main(["show", "HEAD"])
    assert "keep.py  (lines removed)" in capsys.readouterr().out


def test_a_binary_file_is_labelled_binary(recorded):
    submit(recorded, "make a logo")
    (recorded / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00binary")
    stop(recorded)
    sha = commit(recorded, "logo")
    assert files_on(recorded, sha)["logo.png"].label() == "(binary)"


def test_a_receipt_from_before_kinds_existed_reads_neutrally():
    from pblame.models import FileChange
    old = FileChange.from_dict({"path": "x.py", "ranges": []})
    assert old.kind is None and old.label() == "(no added lines)"


def test_notes_without_a_kind_stay_byte_identical():
    """Older pblame versions read these notes; nothing new unless needed."""
    from pblame.models import FileChange
    assert FileChange("x.py", [(1, 2)]).to_dict() == {"path": "x.py", "ranges": [[1, 2]]}


def test_a_waiting_part_for_a_path_now_ignored_is_dropped(recorded):
    """Finding 25: build output recorded before it was ignored waited in
    staging forever, and doctor kept counting it as awaiting a commit."""
    submit(recorded, "run it")
    (recorded / "a.py").write_text("one\n")
    (recorded / "a.pyc").write_bytes(b"\x00\x01bytecode")
    stop(recorded)
    run_git(recorded, "add", "a.py")
    run_git(recorded, "commit", "-q", "-m", "only a.py")
    (recorded / ".gitignore").write_text("*.pyc\n")
    submit(recorded, "next")

    waiting = [f.path for r in staging.load(recorded).receipts for f in r.files]
    assert "a.pyc" not in waiting


# --- 29. text sent to git on stdin arrived with \r\n on Windows ------------

def test_stdin_reaches_git_without_carriage_returns(repo):
    """Text-mode stdin turned "\n" into "\r\n" on Windows: check-ignore
    was asked about "a.pyc\r" and matched nothing."""
    (repo / ".gitignore").write_text("*.pyc\n")
    (repo / "a.pyc").write_bytes(b"\x00")
    assert git(repo, "check-ignore", "--stdin", input_text="a.pyc\n") == "a.pyc"


def test_notes_are_stored_with_plain_newlines(repo):
    """The same receipt written on Windows and on Linux should be the same
    bytes, or every note differs between teammates for no reason."""
    from pblame.snapshot import git_bytes
    from test_staging import make_receipt
    (repo / "a.txt").write_text("a\n")
    sha = commit(repo, "a")
    notes.write(repo, sha, [make_receipt(), make_receipt()])
    blob = git(repo, "notes", "--ref", notes.NOTES_REF, "list", sha)
    assert b"\r\n" not in git_bytes(repo, "cat-file", "blob", blob)


# --- 23. search --path follows renames, like blame does ---------------------

def test_search_by_a_files_current_name_finds_prompts_from_its_old_name(recorded, monkeypatch, capsys):
    turn(recorded, "write the loader", "envfile.py", "def load():\n    return {}\n")
    commit(recorded, "loader")
    run_git(recorded, "mv", "envfile.py", "loader.py")
    run_git(recorded, "commit", "-q", "-m", "rename by hand")

    monkeypatch.chdir(recorded)
    assert main(["search", "--path", "loader.py", "--no-color"]) == 0
    assert "write the loader" in capsys.readouterr().out


def test_a_new_file_reusing_an_old_name_does_not_inherit_its_prompts(recorded, monkeypatch, capsys):
    """Matched on (commit, name at the time), not the name alone."""
    turn(recorded, "write the loader", "envfile.py", "def load():\n    return {}\n")
    commit(recorded, "loader")
    run_git(recorded, "mv", "envfile.py", "loader.py")
    run_git(recorded, "commit", "-q", "-m", "rename by hand")
    turn(recorded, "a different envfile", "other.py", "x = 1\n")
    commit(recorded, "other")

    monkeypatch.chdir(recorded)
    main(["search", "--path", "other.py", "--no-color"])
    out = capsys.readouterr().out
    assert "a different envfile" in out
    assert "write the loader" not in out


# --- 21. the footer counts what matched, not what fitted --------------------

def test_a_limited_search_says_how_many_matched(recorded, monkeypatch, capsys):
    for n in range(4):
        turn(recorded, f"make change {n}", f"f{n}.py", f"{n}\n")
        commit(recorded, f"c{n}")
    monkeypatch.chdir(recorded)

    main(["search", "make", "--limit", "2", "--no-color"])
    out = capsys.readouterr().out
    assert "2 of 4 matches" in out, out[-200:]

    main(["search", "make", "--limit", "2", "--json"])
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert (payload["count"], payload["matched"]) == (2, 4)


# --- 28. one rewrite, one message -------------------------------------------

def test_an_autosquash_reports_once_with_the_true_total(recorded, monkeypatch):
    """git runs post-rewrite as 'amend' for the fixup it applies, then as
    'rebase' with a list that repeats that mapping: two 'carried 1' lines
    for two prompts moved."""
    import subprocess
    turn(recorded, "add a json flag", "a.py", "one\n")
    commit(recorded, "json")
    turn(recorded, "make the json prettier", "a.py", "one\ntwo\n")
    run_git(recorded, "add", "-A")
    run_git(recorded, "commit", "-q", "--fixup", "HEAD")

    monkeypatch.setenv("GIT_SEQUENCE_EDITOR", "true")
    out = subprocess.run(["git", "-C", str(recorded), "rebase", "-q", "-i", "--autosquash", "HEAD~2"],
                         capture_output=True, text=True, encoding="utf-8")
    said = [l for l in (out.stdout + out.stderr).splitlines() if "carried" in l]
    assert len(said) == 1, said
    assert "2 prompts" in said[0]
    assert texts_on(recorded, git(recorded, "rev-parse", "HEAD")) == [
        "add a json flag", "make the json prettier"]
