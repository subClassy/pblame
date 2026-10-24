"""Repairing prompts recorded before clean_prompt and the secret scan existed."""

import uuid
from datetime import datetime, timezone

from conftest import run_git

from pblame import config, notes, repair
from pblame.cli import main
from pblame.models import FileChange, PromptEvent, Receipt
from pblame.snapshot import git

WRAPPED = ('<ide_opened_file>The user opened the file '
           r'c:\Users\alice\Documents\app.py'
           ' in the IDE. This may or may not be '
           'related to the current task.</ide_opened_file>\nmake it look nicer')


def receipt(text):
    return Receipt(
        prompt=PromptEvent(id=uuid.uuid4().hex, text=text, model="claude-opus-5",
                           timestamp=datetime.now(timezone.utc), session_id="s"),
        pre_tree="a" * 40, post_tree="b" * 40,
        files=[FileChange(path="app.py", ranges=[(1, 1)])],
    )


def seed(repo, text=WRAPPED, ref=notes.NOTES_REF):
    (repo / "app.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    sha = git(repo, "rev-parse", "HEAD")
    notes.write(repo, sha, [receipt(text)], ref)
    return sha


def test_preview_changes_nothing(repo):
    sha = seed(repo)
    plans = repair.plan(repo, config.load(repo))

    assert len(plans) == 1
    assert notes.read(repo, sha)[0].prompt.text == WRAPPED  # untouched


def test_apply_strips_the_editor_context(repo):
    sha = seed(repo)
    repair.apply(repo, repair.plan(repo, config.load(repo)))

    assert notes.read(repo, sha)[0].prompt.text == "make it look nicer"


def test_repair_removes_the_secret_that_lived_in_the_wrapper(repo):
    """The home paths that leaked to a remote were inside <ide_opened_file>,
    so cleaning the text deletes them at the source."""
    sha = seed(repo)
    before = repair.plan(repo, config.load(repo))[0].changed[0]
    # The pre-repair scan may be empty (it predates the scan), so assert the outcome.
    assert before[1].prompt.secrets == {}                   # nothing left after cleaning

    repair.apply(repo, repair.plan(repo, config.load(repo)))
    assert "alice" not in notes.read(repo, sha)[0].prompt.text


def test_refreshes_the_secret_scan_on_old_receipts(repo):
    """Receipts predating the scan report nothing; doctor under-reported."""
    sha = seed(repo, text="deploy with AKIAIOSFODNN7EXAMPLE")
    assert notes.read(repo, sha)[0].prompt.secrets == {}

    repair.apply(repo, repair.plan(repo, config.load(repo)))
    assert notes.read(repo, sha)[0].prompt.secrets == {"AWS_KEY": "CRITICAL"}


def test_is_idempotent(repo):
    seed(repo)
    repair.apply(repo, repair.plan(repo, config.load(repo)))
    assert repair.plan(repo, config.load(repo)) == []


def test_a_clean_prompt_is_left_alone(repo):
    sha = seed(repo, text="add a greeting function")
    assert repair.plan(repo, config.load(repo)) == []
    assert notes.read(repo, sha)[0].prompt.text == "add a greeting function"


def test_repairs_the_shared_mirror_too(repo):
    sha = seed(repo, ref=notes.SHARED_REF)
    repair.apply(repo, repair.plan(repo, config.load(repo)))
    assert notes.read(repo, sha, notes.SHARED_REF)[0].prompt.text == "make it look nicer"


def test_other_receipts_in_the_same_note_survive(repo):
    sha = seed(repo)
    notes.merge_into(repo, sha, [receipt("already clean")])
    repair.apply(repo, repair.plan(repo, config.load(repo)))

    texts = {r.prompt.text for r in notes.read(repo, sha)}
    assert texts == {"make it look nicer", "already clean"}


def test_files_and_trees_are_not_touched(repo):
    sha = seed(repo)
    before = notes.read(repo, sha)[0]
    repair.apply(repo, repair.plan(repo, config.load(repo)))
    after = notes.read(repo, sha)[0]

    assert after.pre_tree == before.pre_tree
    assert after.post_tree == before.post_tree
    assert [(f.path, f.ranges) for f in after.files] == [(f.path, f.ranges) for f in before.files]
    assert after.prompt.id == before.prompt.id  # same prompt, repaired


def test_cli_previews_then_writes(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    sha = seed(repo)

    assert main(["repair"]) == 0
    out = capsys.readouterr().out
    assert "Would change" in out and "make it look nicer" in out
    assert notes.read(repo, sha)[0].prompt.text == WRAPPED  # still untouched

    assert main(["repair", "--write"]) == 0
    assert "Repaired 1 prompt" in capsys.readouterr().out
    assert notes.read(repo, sha)[0].prompt.text == "make it look nicer"


def test_cli_says_so_when_there_is_nothing_to_do(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    seed(repo, text="already fine")
    assert main(["repair"]) == 0
    assert "Nothing to repair" in capsys.readouterr().out
