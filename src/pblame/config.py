"""Per-repo configuration: .pblame.json, falling back to ~/.pblame.json.

JSON rather than blameprompt's TOML because `tomllib` is Python 3.11+ and
our floor is 3.10 — not worth raising the floor, or taking a dependency,
for a file we already have a parser for.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = ".pblame.json"


@dataclass
class ShareConfig:
    # Off until someone knowingly turns it on: sharing prompts is a decision,
    # and a question during `init` gets clicked through.
    enabled: bool = False
    remote: str = "origin"


@dataclass
class RedactionConfig:
    mode: str = "replace"  # "replace" | "hash"
    disable_patterns: list[str] = field(default_factory=list)
    enable_patterns: list[str] = field(default_factory=list)  # turn on default-off rules
    custom_patterns: list[dict] = field(default_factory=list)  # {pattern, replacement}


@dataclass
class Config:
    share: ShareConfig = field(default_factory=ShareConfig)
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    source: Path | None = None  # which file this came from, for error messages


def _from_dict(raw: dict, source: Path | None = None) -> Config:
    share = raw.get("share") or {}
    red = raw.get("redaction") or {}
    return Config(
        share=ShareConfig(
            enabled=bool(share.get("enabled", False)),
            remote=str(share.get("remote", "origin")),
        ),
        redaction=RedactionConfig(
            mode=str(red.get("mode", "replace")),
            disable_patterns=list(red.get("disable_patterns") or []),
            enable_patterns=list(red.get("enable_patterns") or []),
            custom_patterns=list(red.get("custom_patterns") or []),
        ),
        source=source,
    )


def load(repo: Path) -> Config:
    """Repo config wins over the user's; a broken file is reported, not
    silently ignored — a config that does not load could mean redaction
    patterns someone relied on are not running."""
    for path in (repo / FILENAME, Path.home() / FILENAME):
        if not path.exists():
            continue
        try:
            return _from_dict(json.loads(path.read_text(encoding="utf-8")), path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            raise ConfigError(f"cannot read {path}: {e}") from e
    return Config()


class ConfigError(RuntimeError):
    pass
