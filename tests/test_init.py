import json
import subprocess

from pblame import git_hooks
from pblame.adapters import claude_code


def local_settings(repo):
    return json.loads((repo / ".claude" / "settings.local.json").read_text())


def is_ignored(repo, rel_path):
    return subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", rel_path]
    ).returncode == 0


def test_install_writes_local_settings_and_ignores_them(repo):
    path = claude_code.install(repo)
    assert path.name == "settings.local.json"

    for event in ("UserPromptSubmit", "Stop"):
        entries = local_settings(repo)["hooks"][event]
        assert len(entries) == 1
        assert "hook claude" in entries[0]["hooks"][0]["command"]

    # Ignored, so the machine-specific path can never be committed
    assert is_ignored(repo, ".claude/settings.local.json")
    assert not (repo / ".claude" / "settings.json").exists()


def test_install_is_idempotent(repo):
    claude_code.install(repo)
    claude_code.install(repo)

    for event in ("UserPromptSubmit", "Stop"):
        assert len(local_settings(repo)["hooks"][event]) == 1
    assert is_ignored(repo, ".claude/settings.local.json")


def test_ensure_ignored_appends_once(repo):
    # A path no global rule covers, so the .git/info/exclude branch is taken.
    target = "pblame-test-artifact.tmp"
    git_hooks.ensure_ignored(repo, target)
    git_hooks.ensure_ignored(repo, target)

    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert exclude.count(target) == 1
    assert is_ignored(repo, target)


def test_install_preserves_other_local_hooks(repo):
    path = repo / ".claude" / "settings.local.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo done"}]}]},
    }))

    claude_code.install(repo)

    settings = local_settings(repo)
    assert settings["model"] == "opus"
    commands = [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]]
    assert "echo done" in commands
    assert any("hook claude" in c for c in commands)


def test_install_migrates_hooks_out_of_shared_settings(repo):
    shared = repo / ".claude" / "settings.json"
    shared.parent.mkdir()
    shared.write_text(json.dumps({
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "C:/venv/pblame hook claude"}]},
                {"hooks": [{"type": "command", "command": "echo mine"}]},
            ]
        }
    }))

    claude_code.install(repo)

    # pblame's entry is gone from the shared file, the user's survives
    remaining = [h["command"] for e in json.loads(shared.read_text())["hooks"]["Stop"]
                 for h in e["hooks"]]
    assert remaining == ["echo mine"]
    # and it now lives in the local file exactly once
    assert len(local_settings(repo)["hooks"]["Stop"]) == 1


def test_install_deletes_shared_settings_it_fully_owned(repo):
    shared = repo / ".claude" / "settings.json"
    shared.parent.mkdir()
    shared.write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "pblame hook claude"}]}]}
    }))

    claude_code.install(repo)

    assert not shared.exists()


def test_ensure_ignored_respects_existing_gitignore(repo):
    (repo / ".gitignore").write_text(".claude/settings.local.json\n")
    git_hooks.ensure_ignored(repo, ".claude/settings.local.json")

    exclude = repo / ".git" / "info" / "exclude"
    assert not exclude.exists() or ".claude" not in exclude.read_text()


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
