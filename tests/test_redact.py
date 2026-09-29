import json

import pytest

from pblame import config, redact
from pblame.config import RedactionConfig


def r(text, **kw):
    return redact.redact(text, RedactionConfig(**kw))


# --- the things we must catch -------------------------------------------

@pytest.mark.parametrize("text, expect, secret", [
    ("my key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz", "API_KEY", "sk-ant"),
    ("aws key: AKIAIOSFODNN7EXAMPLE", "AWS_KEY", "AKIA"),
    ("use ghp_" + "a" * 36, "GITHUB_TOKEN", "ghp_"),
    ("slack xoxb-123456789012-abcdef", "SLACK_TOKEN", "xoxb-"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xx", "BEARER_TOKEN", "eyJhbGci"),
    ('password = "hunter2"', "PASSWORD", "hunter2"),
    ("email me at alice@example.com", "EMAIL", "alice@example.com"),
    ("look in /Users/himank/code", "HOME_PATH", "himank"),
    ("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", "PRIVATE_KEY", "abc"),
])
def test_secrets_are_caught_and_removed(text, expect, secret):
    out = r(text)
    assert expect in out.counts, f"{expect} not detected in {out.text!r}"
    assert secret not in out.text


def test_keeps_the_key_and_redacts_only_the_value():
    """Knowing a prompt set a password is useful; the value is not."""
    out = r('set password = "hunter2" in the config')
    assert out.text == 'set password = "[REDACTED_PASSWORD]" in the config'


def test_high_entropy_catches_an_unanticipated_secret():
    out = r("the value is aB3cD4eF5gH6iJ7kL8mN9oP0qRsTuVwXyZ12")
    assert out.detections
    assert "aB3cD4eF" not in out.text


# --- the things we must NOT touch ---------------------------------------

@pytest.mark.parametrize("text", [
    "upgrade lodash@4.17.21 please",          # blameprompt mangles this
    "use node@20",                            # and this
    "pin typescript@beta",                    # and this
    "npm i @types/node",
    "This is a normal prompt about writing a function",
    "Refactor getUserAuthenticationToken to accept a timeout",
    "fix commit a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # hex sha: entropy <= 4
    "rename the CSS class .panel-shadow-large to .panel-shadow",
])
def test_ordinary_developer_prompts_are_untouched(text):
    out = r(text)
    assert out.text == text, f"false positive: {out.counts}"
    assert out.detections == []


def test_shell_host_rule_is_opt_in():
    text = "metaquity@Abhisheks-MacBook-Pro-2 blameprompt % pblame pull"
    assert r(text).text == text  # off by default
    on = r(text, enable_patterns=["SHELL_HOST"])
    assert "SHELL_HOST" in on.counts
    assert "metaquity@" not in on.text
    assert "pblame pull" in on.text  # the command survives


# --- modes and config ---------------------------------------------------

def test_hash_mode_is_stable_and_correlatable():
    a = r("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz", mode="hash")
    b = r("again sk-ant-api03-abcdefghijklmnopqrstuvwxyz", mode="hash")
    token = [w for w in a.text.split() if w.startswith("[SHA256:")][0]
    assert token in b.text          # same secret -> same placeholder
    assert "sk-ant" not in a.text


def test_disable_and_custom_patterns():
    assert "EMAIL" not in r("a@b.com", disable_patterns=["EMAIL"]).counts

    out = r("Customer CUST-123456 complained", custom_patterns=[
        {"pattern": r"CUST-\d{6,}", "replacement": "[REDACTED_CUSTOMER_ID]"}])
    assert out.text == "Customer [REDACTED_CUSTOMER_ID] complained"
    assert "CUSTOM" in out.counts


def test_a_broken_custom_pattern_does_not_stop_the_builtins():
    out = r("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
            custom_patterns=[{"pattern": "([unclosed"}])
    assert "API_KEY" in out.counts


def test_worst_severity_and_scan():
    out = r("AKIAIOSFODNN7EXAMPLE and alice@example.com")
    assert out.worst() == "CRITICAL"
    assert redact.scan("nothing to see here") == []


def test_empty_input():
    assert r("").text == ""
    assert redact.shannon_entropy("") == 0.0


# --- config loading -----------------------------------------------------

def test_config_defaults_to_not_sharing(repo):
    cfg = config.load(repo)
    assert cfg.share.enabled is False
    assert cfg.redaction.mode == "replace"


def test_repo_config_is_read(repo):
    (repo / config.FILENAME).write_text(json.dumps({
        "share": {"enabled": True, "remote": "upstream"},
        "redaction": {"mode": "hash", "disable_patterns": ["HOME_PATH"]},
    }))
    cfg = config.load(repo)
    assert cfg.share.enabled and cfg.share.remote == "upstream"
    assert cfg.redaction.mode == "hash"
    assert cfg.redaction.disable_patterns == ["HOME_PATH"]


def test_broken_config_raises_rather_than_silently_ignoring(repo):
    (repo / config.FILENAME).write_text("{not json")
    with pytest.raises(config.ConfigError):
        config.load(repo)


# --- capture records detections, doctor surfaces them -------------------

def test_capture_stores_detections_but_not_a_redacted_prompt(repo):
    from pblame import staging
    from pblame.adapters import claude_code

    secret = "AKIAIOSFODNN7EXAMPLE"
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": "s", "prompt": f"deploy with {secret}"})
    prompt = staging.load(repo).receipts[0].prompt

    assert secret in prompt.text, "capture must never mangle the author's record"
    assert prompt.secrets == {"AWS_KEY": "CRITICAL"}


def test_doctor_warns_about_recorded_secrets(repo):
    from pblame import doctor
    from pblame.adapters import claude_code

    claude_code.install(repo)
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": "s", "prompt": "key AKIAIOSFODNN7EXAMPLE"})

    checks = {c.label: c for c in doctor.run(repo)}
    assert "AWS_KEY" in checks["secrets in prompts"].detail
    # Not shared yet, so it is a warning rather than a failure.
    assert checks["secrets in prompts"].status == doctor.WARN
    assert "off" in checks["sharing"].detail


def test_doctor_fails_when_a_high_severity_secret_is_shareable(repo):
    import json as _json
    from pblame import config, doctor
    from pblame.adapters import claude_code

    (repo / config.FILENAME).write_text(_json.dumps({"share": {"enabled": True}}))
    claude_code.install(repo)
    claude_code.handle({"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                        "session_id": "s", "prompt": "key AKIAIOSFODNN7EXAMPLE"})

    checks = {c.label: c for c in doctor.run(repo)}
    assert checks["secrets in prompts"].status == doctor.FAIL
    assert "enabled" in checks["sharing"].detail


def test_redact_command_prints_clean_text_and_a_summary(repo, capsys, monkeypatch):
    from pblame.cli import main

    monkeypatch.chdir(repo)
    (repo / "prompt.txt").write_text("deploy with AKIAIOSFODNN7EXAMPLE to prod\n")
    assert main(["redact", "prompt.txt"]) == 0

    out, err = capsys.readouterr()
    assert out == "deploy with [REDACTED_AWS_KEY] to prod\n"   # stdout is pipeable
    assert "AWS_KEY" in err and "CRITICAL" in err              # summary on stderr


def test_redact_command_honours_repo_config(repo, capsys, monkeypatch):
    import json as _json
    from pblame import config
    from pblame.cli import main

    monkeypatch.chdir(repo)
    (repo / config.FILENAME).write_text(_json.dumps(
        {"redaction": {"custom_patterns": [
            {"pattern": "CUST-[0-9]+", "replacement": "[REDACTED_CUSTOMER_ID]"}]}}))
    (repo / "p.txt").write_text("ticket from CUST-99021\n")
    main(["redact", "p.txt"])
    assert "[REDACTED_CUSTOMER_ID]" in capsys.readouterr().out


@pytest.mark.parametrize("path", [
    r"c:\Users\subCl\Documents\x.py",   # lowercase drive: leaked a real username
    r"C:\Users\subCl\Documents\x.py",
    "C:/Users/subCl/Documents/x.py",
    "/Users/subCl/x",
    "/home/subCl/x",
])
def test_home_paths_redact_the_username_on_every_platform_spelling(path):
    out = r(path)
    assert "subCl" not in out.text, f"username leaked from {path!r}"
    assert "HOME_PATH" in out.counts
