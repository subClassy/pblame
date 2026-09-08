from conftest import run_git

from pblame import blame, notes, staging
from pblame.models import FileChange
from pblame.snapshot import git
from test_staging import make_receipt


def attach(repo, *specs):
    """Stage receipts (text, path, ranges), commit everything, attach."""
    receipts = []
    for text, path, ranges in specs:
        r = make_receipt(text=text)
        r.post_tree = "b" * 40
        r.files = [FileChange(path=path, ranges=ranges)]
        receipts.append(r)
    staging.save(repo, staging.StagingState(receipts=receipts))
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "work")
    notes.attach_staged(repo)
    return git(repo, "rev-parse", "HEAD")


def test_lines_map_to_owning_prompts(repo):
    (repo / "todo.py").write_text("todos = []\n\ndef add(t):\n    todos.append(t)\n")
    attach(repo, ("create the todo list", "todo.py", [(1, 2)]),
                 ("add an add function", "todo.py", [(3, 4)]))

    lines = blame.attribute(repo, "todo.py")
    assert [(l.number, l.receipt.prompt.text) for l in lines] == [
        (1, "create the todo list"),
        (2, "create the todo list"),
        (3, "add an add function"),
        (4, "add an add function"),
    ]


def test_unattributed_lines_have_no_receipt(repo):
    (repo / "a.py").write_text("agent\nhuman\n")
    attach(repo, ("write the first line", "a.py", [(1, 1)]))

    lines = blame.attribute(repo, "a.py")
    assert lines[0].receipt.prompt.text == "write the first line"
    assert lines[1].receipt is None


def test_later_receipt_wins_on_overlap(repo):
    (repo / "a.py").write_text("shared\n")
    attach(repo, ("first prompt", "a.py", [(1, 1)]),
                 ("second prompt rewrote it", "a.py", [(1, 1)]))

    lines = blame.attribute(repo, "a.py")
    assert lines[0].receipt.prompt.text == "second prompt rewrote it"


def test_attribution_survives_a_later_unrelated_commit(repo):
    # The load-bearing claim: git blame follows lines across later commits,
    # so receipts recorded against the first commit still land correctly.
    (repo / "a.py").write_text("first\nsecond\n")
    attach(repo, ("write both lines", "a.py", [(1, 2)]))

    (repo / "a.py").write_text("inserted\nfirst\nsecond\n")
    run_git(repo, "commit", "-q", "-am", "manual insert on top")

    lines = blame.attribute(repo, "a.py")
    assert lines[0].receipt is None  # the human insert
    assert [l.receipt.prompt.text for l in lines[1:]] == ["write both lines"] * 2


def test_commit_without_notes_is_unattributed(repo):
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "no pblame here")

    assert all(l.receipt is None for l in blame.attribute(repo, "a.py"))


def test_render_groups_and_stays_plain_without_color(repo):
    (repo / "a.py").write_text("one\ntwo\nhuman\n")
    attach(repo, ("write two lines of code", "a.py", [(1, 2)]))

    text = blame.render(blame.attribute(repo, "a.py"), "a.py", color=False)
    assert "\033[" not in text
    assert "write two lines of code" in text
    assert text.count("write two lines of code") == 1  # stated once for the group
    assert "(not attributed to a prompt)" in text
    assert "2/3 lines from 1 prompt(s)" in text


def test_render_falls_back_to_ascii_on_cp1252(repo):
    class Cp1252Stream:
        encoding = "cp1252"

    (repo / "a.py").write_text("x\n")
    attach(repo, ("do the thing", "a.py", [(1, 1)]))

    glyphs = blame.glyphs_for(Cp1252Stream())
    assert glyphs == blame.ASCII_GLYPHS
    text = blame.render(blame.attribute(repo, "a.py"), "a.py", color=False, glyphs=glyphs)
    text.encode("cp1252")  # would raise before the fallback


def test_json_output_shape(repo):
    (repo / "a.py").write_text("x\n")
    sha = attach(repo, ("do the thing", "a.py", [(1, 1)]))

    payload = blame.to_json(blame.attribute(repo, "a.py"), "a.py")
    assert payload["file"] == "a.py"
    assert payload["lines"][0]["commit"] == sha
    assert payload["lines"][0]["prompt"]["text"] == "do the thing"
