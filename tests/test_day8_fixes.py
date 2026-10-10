"""Regressions for what the day-8 verification run found."""

import json

from pblame import config, doctor, git_hooks
from pblame.adapters import claude_code

BOM = "﻿"


def write_bom(path, text):
    """What PowerShell 5.1's `Out-File -Encoding utf8` and Notepad produce."""
    path.write_text(BOM + text, encoding="utf-8")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


# --- 9. a UTF-8 BOM must not make a hand-edited file unreadable -----------

def test_config_with_a_bom_loads(repo):
    write_bom(repo / config.FILENAME,
              json.dumps({"redaction": {"mode": "hash"}}))
    assert config.load(repo).redaction.mode == "hash"


def test_local_config_with_a_bom_enables_sharing(repo):
    write_bom(repo / config.LOCAL_FILENAME,
              json.dumps({"share": {"enabled": True, "remote": "upstream"}}))
    cfg = config.load(repo)
    assert cfg.share.enabled is True
    assert cfg.share.remote == "upstream"


def test_claude_settings_with_a_bom_are_read(repo):
    path = repo / ".claude"
    path.mkdir()
    write_bom(path / claude_code.LOCAL_SETTINGS, json.dumps({"hooks": {}}))
    claude_code.install(repo)
    settings = json.loads((path / claude_code.LOCAL_SETTINGS).read_text(encoding="utf-8"))
    assert "UserPromptSubmit" in settings["hooks"]


def test_installing_over_a_hook_with_a_bom_leaves_the_shebang_first(repo):
    """sh does not honour a shebang hidden behind a BOM, so a hook we rewrite
    has to come out without one."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    write_bom(hooks / "post-commit", "#!/bin/sh\necho mine\n")
    git_hooks.install_hooks(repo)
    git_hooks.install_hooks(repo)  # idempotent: one section, not two

    raw = (hooks / "post-commit").read_bytes()
    assert raw.startswith(b"#!/bin/sh"), raw[:20]
    content = raw.decode("utf-8")
    assert content.count(git_hooks.MARK_START) == 1
    assert "echo mine" in content


def test_doctor_does_not_report_a_bom_as_a_failure(repo):
    git_hooks.install_hooks(repo)
    claude_code.install(repo)
    write_bom(repo / config.FILENAME, json.dumps({"redaction": {"mode": "replace"}}))
    failures = [c for c in doctor.run(repo) if c.status == doctor.FAIL]
    assert not [c for c in failures if "BOM" in c.detail], failures


def test_a_file_without_a_bom_still_loads(repo):
    (repo / config.FILENAME).write_text(
        json.dumps({"redaction": {"mode": "hash"}}), encoding="utf-8")
    assert config.load(repo).redaction.mode == "hash"
