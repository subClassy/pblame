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


def test_a_blank_line_does_not_get_its_own_prompt_header(repo):
    """Four single blank lines in one real file became four prompt headers."""
    (repo / "a.py").write_text("one\n\ntwo\n")
    attach(repo, ("wrote line one", "a.py", [(1, 1)]),
                 ("wrote the blank", "a.py", [(2, 2)]),
                 ("wrote line two", "a.py", [(3, 3)]))

    text = blame.render(blame.attribute(repo, "a.py"), "a.py", color=False)
    assert "wrote the blank" not in text      # no header for whitespace
    assert "wrote line one" in text and "wrote line two" in text


def test_json_still_reports_the_blank_lines_real_owner(repo):
    """Grouping is a rendering choice; the data must stay truthful."""
    (repo / "a.py").write_text("one\n\n")
    attach(repo, ("owns both lines", "a.py", [(1, 2)]))

    payload = blame.to_json(blame.attribute(repo, "a.py"), "a.py")
    assert payload["lines"][1]["text"] == ""
    assert payload["lines"][1]["prompt"]["text"] == "owns both lines"


def test_a_leading_blank_line_still_starts_a_group(repo):
    (repo / "a.py").write_text("\ncode\n")
    attach(repo, ("wrote it", "a.py", [(1, 2)]))
    text = blame.render(blame.attribute(repo, "a.py"), "a.py", color=False)
    assert "wrote it" in text


# --- -L, so a demo or a review can look at one region ---------------------

def test_line_range_selects_a_slice_keeping_the_files_own_numbering(repo):
    (repo / "a.py").write_text("".join(f"line {n}\n" for n in range(1, 11)))
    attach(repo, ("first half", "a.py", [(1, 5)]), ("second half", "a.py", [(6, 10)]))
    lines = blame.attribute(repo, "a.py")

    picked = blame.select(lines, "4,7")
    assert [l.number for l in picked] == [4, 5, 6, 7]
    assert [l.receipt.prompt.text for l in picked] == [
        "first half", "first half", "second half", "second half"]


def test_a_single_line_is_a_valid_range(repo):
    (repo / "a.py").write_text("one\ntwo\nthree\n")
    attach(repo, ("all of it", "a.py", [(1, 3)]))
    picked = blame.select(blame.attribute(repo, "a.py"), "2")
    assert [l.number for l in picked] == [2]


def test_no_range_is_the_whole_file(repo):
    (repo / "a.py").write_text("one\ntwo\n")
    attach(repo, ("all of it", "a.py", [(1, 2)]))
    lines = blame.attribute(repo, "a.py")
    assert blame.select(lines, None) == lines


def test_a_range_past_the_end_is_empty_not_an_error(repo):
    (repo / "a.py").write_text("one\n")
    attach(repo, ("it", "a.py", [(1, 1)]))
    assert blame.select(blame.attribute(repo, "a.py"), "50,60") == []


def test_a_nonsense_range_is_rejected():
    import pytest
    for spec in ("9,2", "0,5", "abc", "-3", "5,x"):
        with pytest.raises(ValueError):
            blame.select([], spec)


def test_the_header_counts_the_slice_and_numbers_stay_wide_enough(repo):
    """A slice of lines 95-100 is six lines but still needs three columns."""
    (repo / "a.py").write_text("".join(f"line {n}\n" for n in range(1, 101)))
    attach(repo, ("the lot", "a.py", [(1, 100)]))
    picked = blame.select(blame.attribute(repo, "a.py"), "95,100")

    text = blame.render(picked, "a.py:95,100", color=False)
    assert "6/6 lines from 1 prompt(s)" in text
    assert " 95 " in text and " 100 " in text


def test_cli_rejects_a_bad_range_without_a_traceback(repo, monkeypatch, capsys):
    from pblame.cli import main
    (repo / "a.py").write_text("one\n")
    attach(repo, ("it", "a.py", [(1, 1)]))
    monkeypatch.chdir(repo)

    assert main(["blame", "a.py", "-L", "9,2"]) == 1
    assert "line range" in capsys.readouterr().err


# --- --color, for piping into less -R or capturing for a document ---------

def test_color_is_off_when_redirected_and_forced_by_the_flag(repo, monkeypatch, capsys):
    from pblame.cli import main
    (repo / "a.py").write_text("one\n")
    attach(repo, ("it", "a.py", [(1, 1)]))
    monkeypatch.chdir(repo)

    main(["blame", "a.py"])
    assert "\033[" not in capsys.readouterr().out, "pytest's stdout is not a tty"

    main(["blame", "a.py", "--color"])
    assert "\033[" in capsys.readouterr().out

    main(["blame", "a.py", "--no-color"])
    assert "\033[" not in capsys.readouterr().out


def test_forcing_color_beats_NO_COLOR(repo, monkeypatch, capsys):
    """An explicit flag wins over the environment: the user just asked."""
    from pblame.cli import main
    (repo / "a.py").write_text("one\n")
    attach(repo, ("it", "a.py", [(1, 1)]))
    monkeypatch.chdir(repo)
    monkeypatch.setenv("NO_COLOR", "1")

    main(["blame", "a.py"])
    assert "\033[" not in capsys.readouterr().out
    main(["blame", "a.py", "--color"])
    assert "\033[" in capsys.readouterr().out


def test_search_and_doctor_take_the_same_flags(repo, monkeypatch, capsys):
    from pblame.cli import main
    (repo / "a.py").write_text("one\n")
    attach(repo, ("find me", "a.py", [(1, 1)]))
    monkeypatch.chdir(repo)

    main(["search", "find", "--color"])
    assert "\033[" in capsys.readouterr().out
    main(["doctor", "--color"])
    assert "\033[" in capsys.readouterr().out
