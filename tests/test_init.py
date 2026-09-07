import json

from pblame import git_hooks
from pblame.adapters import claude_code


def test_claude_settings_install_is_idempotent(repo):
    path = claude_code.install(repo)
    claude_code.install(repo)

    settings = json.loads(path.read_text())
    for event in ("UserPromptSubmit", "Stop"):
        entries = settings["hooks"][event]
        assert len(entries) == 1
        assert "hook claude" in entries[0]["hooks"][0]["command"]


def test_claude_settings_install_preserves_existing_hooks(repo):
    path = repo / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]},
    }))

    claude_code.install(repo)

    settings = json.loads(path.read_text())
    assert settings["model"] == "opus"
    stop_commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert "echo done" in stop_commands
    assert any("hook claude" in c for c in stop_commands)


def test_post_commit_hook_install_and_reinstall(repo):
    path = git_hooks.install_post_commit(repo)
    content = path.read_text()
    assert content.startswith("#!/bin/sh")
    assert content.count(git_hooks.MARK_START) == 1
    assert "attach" in content

    git_hooks.install_post_commit(repo)
    assert path.read_text().count(git_hooks.MARK_START) == 1


def test_post_commit_hook_preserves_existing_hook(repo):
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    existing = hooks_dir / "post-commit"
    existing.write_text("#!/bin/sh\necho user-hook\n")

    path = git_hooks.install_post_commit(repo)
    content = path.read_text()
    assert "echo user-hook" in content
    assert git_hooks.MARK_START in content
