"""Searching recorded history — the prompt-library half of the product."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import run_git

from pblame import index, notes, searchview
from pblame.cli import main
from pblame.models import FileChange, PromptEvent, Receipt
from pblame.snapshot import git


def receipt(text, path="app.py", ranges=((1, 1),), model="claude-opus-5", age_days=0):
    return Receipt(
        prompt=PromptEvent(
            id=uuid.uuid4().hex, text=text, model=model,
            timestamp=datetime.now(timezone.utc) - timedelta(days=age_days),
            session_id="s",
        ),
        pre_tree="a" * 40, post_tree="b" * 40,
        files=[FileChange(path=path, ranges=[tuple(r) for r in ranges])],
    )


@pytest.fixture
def history(repo):
    """A repo with three commits, each carrying one recorded prompt."""
    shas = []
    for n, (text, path, model, age) in enumerate([
        ("Add a login endpoint that checks the password hash", "auth.py", "claude-opus-5", 30),
        ("make it safer", "auth.py", "claude-opus-5", 20),
        ("Add a --json flag to the report", "report.py", "claude-sonnet-5", 2),
    ]):
        (repo / path).write_text(f"line {n}\n")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", f"commit {n}")
        sha = git(repo, "rev-parse", "HEAD")
        notes.write(repo, sha, [receipt(text, path, model=model, age_days=age)])
        shas.append(sha)
    return shas


def find(repo, **kw):
    entries = index.load(repo)
    hits, _ = index.search(entries, index.Query(**kw))
    return [h.prompt.text for h in hits]


# --- loading ------------------------------------------------------------

def test_loads_every_recorded_prompt_newest_first(repo, history):
    texts = [e.prompt.text for e in index.load(repo)]
    assert texts[0] == "Add a --json flag to the report"   # 2 days old
    assert texts[-1].startswith("Add a login endpoint")    # 30 days old
    assert len(texts) == 3


def test_reads_the_whole_history_in_a_constant_number_of_git_calls(repo, history, monkeypatch):
    """The reason this module exists: `git notes show` per commit costs 46ms,
    so a repo with 500 recorded commits took 23 seconds."""
    calls = []
    real_git, real_bytes = index.git, index.git_bytes
    monkeypatch.setattr(index, "git", lambda *a, **k: (calls.append(a[1]), real_git(*a, **k))[1])
    monkeypatch.setattr(index, "git_bytes",
                        lambda *a, **k: (calls.append(a[1]), real_bytes(*a, **k))[1])

    index.load(repo)
    # ls-tree per ref (2), cat-file per ref (2), one log for commit metadata.
    assert len(calls) <= 5, calls
    assert "cat-file" in calls


def test_a_teammates_shared_prompt_is_marked_and_ours_wins(repo, history):
    sha = history[0]
    mine = notes.read(repo, sha)[0]
    notes.write(repo, sha, [receipt("someone else's prompt", "auth.py")], notes.SHARED_REF)
    # The same prompt, redacted, in the mirror as well as ours.
    redacted = receipt("REDACTED copy", "auth.py")
    redacted.prompt = type(redacted.prompt)(
        id=mine.prompt.id, text="redacted copy", model=mine.prompt.model,
        timestamp=mine.prompt.timestamp, session_id="s")
    notes.merge_into(repo, sha, [redacted], notes.SHARED_REF)

    by_text = {e.prompt.text: e for e in index.load(repo)}
    assert "someone else's prompt" in by_text
    assert by_text["someone else's prompt"].shared is True
    # Ours is kept verbatim and not replaced by the mirror's copy.
    assert mine.prompt.text in by_text
    assert by_text[mine.prompt.text].shared is False
    assert "redacted copy" not in by_text


# --- filters ------------------------------------------------------------

def test_text_search_is_case_insensitive_substring(repo, history):
    assert find(repo, text="SAFER") == ["make it safer"]
    assert find(repo, text="add a") == ["Add a --json flag to the report",
                                        "Add a login endpoint that checks the password hash"]


def test_regex_search(repo, history):
    assert find(repo, text=r"^make\b", regex=True) == ["make it safer"]


def test_path_filter_by_name_and_glob(repo, history):
    assert len(find(repo, path="auth.py")) == 2
    assert len(find(repo, path="*.py")) == 3
    assert find(repo, path="report") == ["Add a --json flag to the report"]


def test_date_filters(repo, history):
    assert find(repo, since=index.parse_when("7d")) == ["Add a --json flag to the report"]
    assert len(find(repo, until=index.parse_when("10d"))) == 2


def test_model_and_author_filters(repo, history):
    assert find(repo, model="sonnet") == ["Add a --json flag to the report"]
    assert len(find(repo, author="Test")) == 3       # conftest sets user.name=Test
    assert find(repo, author="nobody") == []


def test_mine_excludes_prompts_only_in_the_mirror(repo, history):
    notes.write(repo, history[0], [receipt("theirs", "auth.py")], notes.SHARED_REF)
    assert "theirs" in find(repo)
    assert "theirs" not in find(repo, mine=True)


def test_filters_combine(repo, history):
    assert find(repo, text="add", path="auth.py") == [
        "Add a login endpoint that checks the password hash"]


# --- dates --------------------------------------------------------------

@pytest.mark.parametrize("value, days", [("7d", 7), ("2w", 14), ("3m", 90), ("1y", 365)])
def test_relative_ages(value, days):
    delta = datetime.now(timezone.utc) - index.parse_when(value)
    assert abs(delta.days - days) <= 1


def test_iso_dates_are_accepted_and_assumed_utc():
    assert index.parse_when("2026-09-01").tzinfo is not None
    assert index.parse_when("2026-09-01").month == 9


def test_a_date_we_cannot_read_is_an_error():
    with pytest.raises(ValueError):
        index.parse_when("last tuesday")


# --- output -------------------------------------------------------------

def test_render_is_plain_without_color_and_names_the_totals(repo, history):
    entries = index.load(repo)
    hits, matcher = index.search(entries, index.Query(text="safer"))
    text = searchview.render(hits, matcher, total=len(entries), color=False)

    assert "\033[" not in text
    assert "make it safer" in text
    assert "1 of 3 recorded prompts" in text


def test_render_says_so_when_nothing_matched(repo, history):
    assert "No prompts matched" in searchview.render([], None, total=3, color=False)


def test_cli_json_output(repo, history, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert main(["search", "safer", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["prompts"][0]["prompt"]["text"] == "make it safer"
    assert payload["prompts"][0]["files"][0]["path"] == "auth.py"


def test_cli_exit_code_signals_no_match(repo, history, monkeypatch, capsys):
    """Non-zero on no results, so it composes in a shell the way grep does."""
    monkeypatch.chdir(repo)
    assert main(["search", "safer"]) == 0
    assert main(["search", "nothing-like-this"]) == 1
    capsys.readouterr()


def test_cli_limit(repo, history, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    main(["search", "--limit", "1", "--json"])
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_cli_reports_an_unreadable_date(repo, history, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert main(["search", "--since", "yesterday"]) == 1
    assert "date" in capsys.readouterr().err.lower()


# --- findings 1 and 2: shipped without tests, covered now ----------------

@pytest.mark.parametrize("pattern", [
    "auth.py", "./auth.py", r".\auth.py", "AUTH.PY", "*.py",
])
def test_path_filter_accepts_what_a_shell_hands_over(repo, history, pattern):
    r"""PowerShell tab-completion produces .\auth.py, which matched nothing."""
    assert "make it safer" in find(repo, path=pattern)


def test_path_normalisation_is_explicit():
    assert index.normalise_path(r".\src\a.py") == "src/a.py"
    assert index.normalise_path("./src/a.py") == "src/a.py"
    assert index.normalise_path("src/a.py") == "src/a.py"


def test_redirected_output_is_utf8_not_the_locale_codepage(repo, history):
    """An em dash was leaving as cp1252 0x97 and arriving as mojibake."""
    import subprocess, sys
    notes.write(repo, history[-1], [receipt("use a real \u2014 em dash \u2014 here")])

    out = subprocess.run(
        [sys.executable, "-m", "pblame.cli", "search", "em dash"],
        cwd=repo, capture_output=True,
    )
    assert b"\xe2\x80\x94" in out.stdout, out.stdout[:200]   # UTF-8
    assert b"\x97" not in out.stdout                          # not cp1252
    out.stdout.decode("utf-8")                                # and decodes cleanly
