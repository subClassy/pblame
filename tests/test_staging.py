import uuid
from datetime import datetime, timezone

from pblame import staging
from pblame.models import FileChange, PromptEvent, Receipt


def make_receipt(session_id="s1", text="do a thing"):
    return Receipt(
        prompt=PromptEvent(
            id=uuid.uuid4().hex,
            text=text,
            model="",
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
        ),
        pre_tree="a" * 40,
    )


def test_roundtrip(repo):
    r = make_receipt()
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 3), (7, 7)])]
    staging.save(repo, [r])

    loaded = staging.load(repo)
    assert len(loaded) == 1
    assert loaded[0] == r


def test_load_missing_or_corrupt(repo):
    assert staging.load(repo) == []
    path = repo / ".git" / "pblame" / "staging.json"
    path.parent.mkdir()
    path.write_text("not json{")
    assert staging.load(repo) == []


def test_find_open_matches_session_and_openness(repo):
    open_s1 = make_receipt("s1")
    closed_s1 = make_receipt("s1")
    closed_s1.post_tree = "b" * 40
    open_s2 = make_receipt("s2")
    receipts = [closed_s1, open_s1, open_s2]

    assert staging.find_open(receipts, "s1") is open_s1
    assert staging.find_open(receipts, "s2") is open_s2
    assert staging.find_open(receipts, "s3") is None
