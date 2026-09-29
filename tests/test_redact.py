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
