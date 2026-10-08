import json
from datetime import datetime, timedelta, timezone

from conftest import run_git

from pblame import doctor, git_hooks, notes, staging
from pblame.adapters import claude_code
from pblame.cli import main
from pblame.models import FileChange
from test_staging import make_receipt


def statuses(repo):
    return {(c.label, c.status) for c in doctor.run(repo)}


def failures(repo):
    return [c for c in doctor.run(repo) if c.status == doctor.FAIL]


def init(repo):
    claude_code.install(repo)
    git_hooks.install_hooks(repo)


def test_healthy_repo_passes(repo):
    init(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    r = make_receipt(text="write it")
    r.post_tree = "b" * 40
    r.files = [FileChange(path="a.py", ranges=[(1, 1)])]
    notes.write(repo, "HEAD", [r])

    assert failures(repo) == []


def test_uninitialised_repo_fails(repo):
    assert ("Claude Code hooks", doctor.FAIL) in statuses(repo)
    assert ("post-commit hook", doctor.FAIL) in statuses(repo)
    assert ("post-rewrite hook", doctor.FAIL) in statuses(repo)


def test_hooks_removed_from_settings_fail_per_event(repo):
    init(repo)
    path = repo / ".claude" / claude_code.LOCAL_SETTINGS
    path.write_text(json.dumps({"hooks": {}}))

    assert ("UserPromptSubmit hook", doctor.FAIL) in statuses(repo)
    assert ("Stop hook", doctor.FAIL) in statuses(repo)


def test_stale_binary_path_is_caught(repo):
    """The venv moved or was rebuilt: hooks fire into nothing."""
    init(repo)
    path = repo / ".claude" / claude_code.LOCAL_SETTINGS
    settings = json.loads(path.read_text())
    for event in claude_code.HOOK_EVENTS:
        settings["hooks"][event] = [
            {"hooks": [{"type": "command", "command": '"C:/gone/pblame" hook claude'}]}
        ]
    path.write_text(json.dumps(settings))

    assert any("does not exist" in c.detail for c in failures(repo))


def test_duplicate_hook_registration_is_caught(repo):
    """Hooks in both settings files fire twice and corrupt turn boundaries."""
    init(repo)
    path = repo / ".claude" / claude_code.LOCAL_SETTINGS
    settings = json.loads(path.read_text())
    settings["hooks"]["Stop"] *= 2
    path.write_text(json.dumps(settings))

    assert any("recorded twice" in c.detail for c in failures(repo))


def test_hook_log_with_errors_fails_loudly(repo):
    init(repo)
    log = repo / ".git" / "pblame" / "hook.log"
    log.parent.mkdir(exist_ok=True)
    log.write_text("2026-09-13 10:00:00 hook: GitError: boom\n")

    failing = [c for c in failures(repo) if c.label == "hook log"]
    assert failing and "boom" in failing[0].detail


def test_live_snapshot_check_reports_a_broken_recorder(repo, monkeypatch):
    init(repo)
    monkeypatch.setattr(doctor, "snapshot_tree",
                        lambda _: (_ for _ in ()).throw(RuntimeError("cp1252 boom")))
    failing = [c for c in failures(repo) if c.label == "live snapshot"]
    assert failing and "cp1252 boom" in failing[0].detail


def test_recent_open_receipt_warns_but_stale_one_fails(repo):
    init(repo)
    fresh = make_receipt(text="still running")
    staging.save(repo, staging.StagingState(receipts=[fresh]))
    assert any(c.label == "open receipt" and c.status == doctor.WARN for c in doctor.run(repo))

    stale = make_receipt(text="dead session")
    stale.prompt = type(stale.prompt)(
        id=stale.prompt.id, text=stale.prompt.text, model="", session_id="s",
        timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    staging.save(repo, staging.StagingState(receipts=[stale]))
    assert any(c.label == "open receipt" and c.status == doctor.FAIL for c in doctor.run(repo))


def test_corrupt_staging_is_caught(repo):
    init(repo)
    path = repo / ".git" / "pblame" / "staging.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("{not json")
    assert any(c.label == "staging" for c in failures(repo))


def test_exit_code_and_render(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert main(["doctor"]) == 1  # nothing installed yet
    assert "Not recording reliably" in capsys.readouterr().out

    init(repo)
    (repo / "a.py").write_text("x\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "seed")
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Recording is live" in out
    assert "\033[" not in out  # not a tty under capsys


def test_live_snapshot_reports_its_cost(repo):
    """A prompt costs two snapshots, so the number belongs in front of the
    user rather than in a benchmark nobody runs."""
    init(repo)
    (repo / "a.py").write_text("x\n")
    check = next(c for c in doctor.run(repo) if c.label == "live snapshot")
    assert "per prompt" in check.detail
    assert check.status == doctor.PASS   # a small repo is fast


def test_a_slow_snapshot_points_at_git_fsmonitor(repo, monkeypatch):
    init(repo)
    import time as _time
    real = _time.perf_counter
    calls = iter([0.0, 2.0])  # pretend the snapshot took two seconds
    monkeypatch.setattr(doctor.time, "perf_counter", lambda: next(calls, real()))

    check = next(c for c in doctor.run(repo) if c.label == "live snapshot")
    assert check.status == doctor.WARN
    assert "fsmonitor" in check.detail
