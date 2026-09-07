import json

from pblame import staging
from pblame.adapters import claude_code


def submit(repo, prompt, session="s1"):
    claude_code.handle(
        {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(repo),
            "session_id": session,
            "prompt": prompt,
        }
    )


def stop(repo, transcript=None, session="s1"):
    claude_code.handle(
        {
            "hook_event_name": "Stop",
            "cwd": str(repo),
            "session_id": session,
            "transcript_path": str(transcript) if transcript else None,
        }
    )


def receipts_in(repo):
    return staging.load(repo).receipts


def test_turn_lifecycle(repo, tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": "claude-opus-5"}}) + "\n"
    )

    submit(repo, "add a greeting function")
    (repo / "a.py").write_text("def greet():\n    return 'hi'\n")
    stop(repo, transcript)

    receipts = receipts_in(repo)
    assert len(receipts) == 1
    r = receipts[0]
    assert not r.is_open
    assert r.prompt.text == "add a greeting function"
    assert r.prompt.model == "claude-opus-5"
    assert [(f.path, f.ranges) for f in r.files] == [("a.py", [(1, 2)])]


def test_manual_edits_between_turns_not_attributed(repo):
    submit(repo, "first prompt")
    (repo / "a.py").write_text("agent line\n")
    stop(repo)

    # Human edits another file between turns
    (repo / "human.py").write_text("human line\n")

    submit(repo, "second prompt")
    (repo / "a.py").write_text("agent line\nsecond agent line\n")
    stop(repo)

    receipts = receipts_in(repo)
    assert len(receipts) == 2
    files_by_prompt = {r.prompt.text: [(f.path, f.ranges) for f in r.files] for r in receipts}
    assert files_by_prompt["first prompt"] == [("a.py", [(1, 1)])]
    # human.py appears in neither receipt
    assert files_by_prompt["second prompt"] == [("a.py", [(2, 2)])]


def test_human_insertion_shifts_earlier_receipt_ranges(repo):
    submit(repo, "write two lines")
    (repo / "a.py").write_text("agent1\nagent2\n")
    stop(repo)

    # Human prepends two lines between turns
    (repo / "a.py").write_text("human1\nhuman2\nagent1\nagent2\n")

    submit(repo, "append a line")
    (repo / "a.py").write_text("human1\nhuman2\nagent1\nagent2\nagent3\n")
    stop(repo)

    receipts = receipts_in(repo)
    files_by_prompt = {r.prompt.text: [(f.path, f.ranges) for f in r.files] for r in receipts}
    # First receipt's lines followed the human insertion down the file
    assert files_by_prompt["write two lines"] == [("a.py", [(3, 4)])]
    assert files_by_prompt["append a line"] == [("a.py", [(5, 5)])]


def test_later_turn_shifts_earlier_receipt_ranges(repo):
    (repo / "a.py").write_text("existing\n")

    submit(repo, "add helper at bottom")
    (repo / "a.py").write_text("existing\nhelper\n")
    stop(repo)

    submit(repo, "add imports at top")
    (repo / "a.py").write_text("import os\nimport sys\nexisting\nhelper\n")
    stop(repo)

    receipts = receipts_in(repo)
    files_by_prompt = {r.prompt.text: [(f.path, f.ranges) for f in r.files] for r in receipts}
    assert files_by_prompt["add helper at bottom"] == [("a.py", [(4, 4)])]
    assert files_by_prompt["add imports at top"] == [("a.py", [(1, 2)])]


def test_interrupted_turn_closed_by_next_prompt(repo):
    submit(repo, "interrupted prompt")
    (repo / "a.py").write_text("partial work\n")
    # No Stop: user interrupted. Next prompt closes the orphan.
    submit(repo, "next prompt")

    receipts = receipts_in(repo)
    assert len(receipts) == 2
    interrupted, current = receipts
    assert not interrupted.is_open
    assert [(f.path, f.ranges) for f in interrupted.files] == [("a.py", [(1, 1)])]
    assert current.is_open


def test_stop_without_open_receipt_is_noop(repo):
    stop(repo)
    assert receipts_in(repo) == []


def test_prompt_with_no_changes(repo):
    submit(repo, "just a question")
    stop(repo)

    receipts = receipts_in(repo)
    assert len(receipts) == 1
    assert not receipts[0].is_open
    assert receipts[0].files == []
