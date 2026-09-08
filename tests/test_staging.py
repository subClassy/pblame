import uuid
from datetime import datetime, timezone

from pblame import staging
from pblame.models import FileChange, PromptEvent, Receipt
from pblame.staging import StagingState


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
    staging.save(repo, StagingState(last_tree="c" * 40, receipts=[r]))

    loaded = staging.load(repo)
    assert loaded.last_tree == "c" * 40
    assert loaded.receipts == [r]


def test_load_missing_or_corrupt(repo):
    assert staging.load(repo) == StagingState()
    path = repo / ".git" / "pblame" / "staging.json"
    path.parent.mkdir()
    path.write_text("not json{")
    assert staging.load(repo) == StagingState()


def test_find_open_matches_session_and_openness(repo):
    open_s1 = make_receipt("s1")
    closed_s1 = make_receipt("s1")
    closed_s1.post_tree = "b" * 40
    open_s2 = make_receipt("s2")
    receipts = [closed_s1, open_s1, open_s2]

    assert staging.find_open(receipts, "s1") is open_s1
    assert staging.find_open(receipts, "s2") is open_s2
    assert staging.find_open(receipts, "s3") is None


def closed_receipt(path, ranges):
    r = make_receipt()
    r.post_tree = "b" * 40
    r.files = [FileChange(path=path, ranges=ranges)]
    return r


def test_apply_offsets_shifts_ranges_below_insertion():
    r = closed_receipt("a.py", [(5, 7)])
    staging.apply_offsets([r], {"a.py": [(3, 2)]})
    assert r.files[0].ranges == [(7, 9)]


def test_apply_offsets_leaves_ranges_above_change():
    r = closed_receipt("a.py", [(5, 7)])
    staging.apply_offsets([r], {"a.py": [(10, 4)]})
    assert r.files[0].ranges == [(5, 7)]


def test_apply_offsets_accumulates_deltas():
    r = closed_receipt("a.py", [(20, 21)])
    staging.apply_offsets([r], {"a.py": [(1, 3), (10, -2)]})
    assert r.files[0].ranges == [(21, 22)]


def test_apply_offsets_splits_range_around_interior_insertion():
    # The real-agent failure: a later prompt inserts inside a range an earlier
    # prompt owns, so the earlier range must split rather than over-claim.
    r = closed_receipt("index.html", [(1, 12)])
    staging.apply_offsets([r], {"index.html": [(9, 8)]})
    assert r.files[0].ranges == [(1, 8), (17, 20)]


def test_apply_offsets_shrinks_range_around_interior_deletion():
    r = closed_receipt("a.py", [(5, 20)])
    staging.apply_offsets([r], {"a.py": [(12, -3)]})
    assert r.files[0].ranges == [(5, 17)]


def test_apply_offsets_survives_successive_insertions():
    # index.html from the dummy_clock session: title inserted at 9, then the
    # duck's 8 lines inserted at 9 again.
    r = closed_receipt("index.html", [(1, 12)])
    staging.apply_offsets([r], {"index.html": [(9, 1)]})
    assert r.files[0].ranges == [(1, 8), (10, 13)]
    staging.apply_offsets([r], {"index.html": [(9, 8)]})
    assert r.files[0].ranges == [(1, 8), (18, 21)]


def test_apply_offsets_skips_open_receipts_and_other_files():
    open_r = make_receipt()
    open_r.files = [FileChange(path="a.py", ranges=[(5, 5)])]
    other = closed_receipt("b.py", [(5, 5)])
    staging.apply_offsets([open_r, other], {"a.py": [(1, 10)]})
    assert open_r.files[0].ranges == [(5, 5)]
    assert other.files[0].ranges == [(5, 5)]
