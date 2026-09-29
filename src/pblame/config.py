"""Configuration, split by who it belongs to.

  .pblame.json        committed, team-wide: redaction rules everyone shares.
  .pblame.local.json  personal, gitignored: whether *you* share.

That split exists because of a real failure. If `share.enabled` could come
from the committed file, one person enabling sharing would silently enable it
for everyone who pulls — their prompts would start leaving their machine
without them ever agreeing. Sharing is a decision each developer makes, so
`enabled` is read from the local file only. Redaction rules are the opposite:
a team wants one consistent filter, so those are shared.

Same reasoning as .claude/settings.json versus settings.local.json.

JSON rather than blameprompt's TOML because `tomllib` is Python 3.11+ and our
floor is 3.10 — not worth raising the floor, or a dependency, for a file we
already have a parser for.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = ".pblame.json"              # committed: team-wide redaction rules
LOCAL_FILENAME = ".pblame.local.json"  # gitignored: personal sharing choice


@dataclass
class ShareConfig:
    enabled: bool = False  # only ever set by the local file
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
    sources: list[Path] = field(default_factory=list)
    # True when the committed file tried to switch sharing on for everyone.
    shared_tried_to_enable: bool = False


class ConfigError(RuntimeError):
    pass


def _read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"cannot read {path}: expected a JSON object")
    return raw


def _apply(cfg: Config, raw: dict, allow_enable: bool) -> None:
    share = raw.get("share") or {}
    if "enabled" in share:
        if allow_enable:
            cfg.share.enabled = bool(share["enabled"])
        else:
            cfg.shared_tried_to_enable = True
    if "remote" in share:
        cfg.share.remote = str(share["remote"])

    red = raw.get("redaction") or {}
    if "mode" in red:
        cfg.redaction.mode = str(red["mode"])
    for key in ("disable_patterns", "enable_patterns", "custom_patterns"):
        if key in red:
            setattr(cfg.redaction, key, list(red[key] or []))


def load(repo: Path) -> Config:
    """Team file first, then the personal one on top. A broken file is
    reported rather than ignored: a config that silently fails to load could
    mean redaction patterns someone relied on are not running."""
    cfg = Config()
    for path, allow_enable in (
        (repo / FILENAME, False),
        (Path.home() / FILENAME, True),   # a user-level default is still yours
        (repo / LOCAL_FILENAME, True),
    ):
        if path.exists():
            _apply(cfg, _read(path), allow_enable)
            cfg.sources.append(path)
    return cfg


def enable_sharing(repo: Path, remote: str | None = None) -> Path:
    """Turn sharing on for this developer, in the personal file."""
    path = repo / LOCAL_FILENAME
    raw = _read(path) if path.exists() else {}
    share = raw.setdefault("share", {})
    share["enabled"] = True
    if remote:
        share["remote"] = remote
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path
