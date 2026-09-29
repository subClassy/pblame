"""Secret redaction for prompt text.

Ported from blameprompt's `src/core/redact.rs` (MIT, see NOTICE): the pattern
table, Shannon-entropy detection, and the replace/hash modes.

Three deliberate differences:

* **Never at capture.** Prompts are stored verbatim in `.git`, as private as
  the code beside them, and filtered only when crossing the machine boundary.
  A false positive then costs fidelity in the shared copy, not in the
  author's own record — which matters because that record is meant to be a
  usable prompt library.
* **Keep the key, redact the value.** `password = "hunter2"` becomes
  `password = "[REDACTED_PASSWORD]"` rather than losing the whole assignment.
  Knowing a prompt set a password is useful; the value is not.
* **Their host pattern is off by default.** `[^@]+@[^@]+` mangles
  `lodash@4.17.21` and `node@20`, which are ordinary dependency prompts. A
  precise EMAIL rule stays on; the shell-prompt rule is opt-in.
"""

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from .config import RedactionConfig

ENTROPY_THRESHOLD = 4.5
ENTROPY_MIN_LENGTH = 20
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{%d,}" % ENTROPY_MIN_LENGTH)


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW
    pattern: re.Pattern
    secret_group: int | None = None  # redact only this group, keep the rest
    default_on: bool = True

    @property
    def placeholder(self) -> str:
        return f"[REDACTED_{self.name}]"


# Ordered: precise rules first, so a match is claimed by the most specific
# rule that describes it.
RULES: tuple[Rule, ...] = (
    Rule("PRIVATE_KEY", "CRITICAL",
         re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----")),
    Rule("AWS_KEY", "CRITICAL", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    Rule("GITHUB_TOKEN", "CRITICAL", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    Rule("SLACK_TOKEN", "HIGH", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    Rule("API_KEY", "HIGH", re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{20,}\b")),
    Rule("JWT", "HIGH", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    Rule("BEARER_TOKEN", "HIGH",
         re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9_.~+/=-]{10,})"), secret_group=2),
    # Keeps the key name and quoting, replaces only the value.
    Rule("PASSWORD", "HIGH",
         re.compile(r"""(?i)\b(password|passwd|pwd|secret)(\s*[:=]\s*)(["']?)([^\s"',;]{3,})(\3)"""),
         secret_group=4),
    Rule("TOKEN", "MEDIUM",
         re.compile(r"""(?i)\b(token|auth|api[_-]?key|access[_-]?key)(\s*[:=]\s*)(["']?)([^\s"',;]{16,})(\3)"""),
         secret_group=4),
    Rule("EMAIL", "MEDIUM",
         re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # The drive letter must be case-insensitive: Claude Code writes `c:\Users\…`
    # in its editor-context paths, and requiring `C:` let a real username
    # through to a remote. Forward slashes too — git and shells both emit them.
    Rule("HOME_PATH", "LOW",
         re.compile(r"(?i)(?:/Users/|/home/|[A-Z]:[\\/]Users[\\/])([A-Za-z0-9_.-]+)"),
         secret_group=1),
    # blameprompt has this on by default; it eats `typescript@beta` and
    # `metaquity@MacBook` alike, so it is opt-in via enable_patterns.
    Rule("SHELL_HOST", "LOW",
         re.compile(r"\b[A-Za-z0-9_.-]+@(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{2,}\b"),
         default_on=False),
)


@dataclass(frozen=True)
class Detection:
    name: str
    severity: str


@dataclass
class Result:
    text: str
    detections: list[Detection] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(d.name for d in self.detections))

    def worst(self) -> str | None:
        order = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        found = {d.severity for d in self.detections}
        return next((s for s in order if s in found), None)


def _hash(secret: str) -> str:
    """Stable placeholder: a reader can tell the same secret appeared twice
    without learning it."""
    return f"[SHA256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]}]"


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def active_rules(cfg: RedactionConfig) -> list[Rule]:
    on = []
    for rule in RULES:
        enabled = rule.default_on or rule.name in cfg.enable_patterns
        if enabled and rule.name not in cfg.disable_patterns:
            on.append(rule)
    return on


def _replace(text: str, pattern: re.Pattern, mode: str, secret_group: int | None,
             placeholder: str, on_hit: Callable[[], None]) -> str:
    def sub(m: re.Match) -> str:
        on_hit()
        group = secret_group if secret_group and m.group(secret_group) else 0
        secret = m.group(group)
        token = _hash(secret) if mode == "hash" else placeholder
        if group == 0:
            return token
        whole, offset = m.group(0), m.start()
        start, end = m.span(group)
        return whole[: start - offset] + token + whole[end - offset:]

    return pattern.sub(sub, text)


def redact(text: str, cfg: RedactionConfig | None = None) -> Result:
    cfg = cfg or RedactionConfig()
    mode = cfg.mode if cfg.mode in ("replace", "hash") else "replace"
    detections: list[Detection] = []
    result = text

    for rule in active_rules(cfg):
        result = _replace(
            result, rule.pattern, mode, rule.secret_group, rule.placeholder,
            lambda r=rule: detections.append(Detection(r.name, r.severity)),
        )

    for raw in cfg.custom_patterns:
        try:
            pattern = re.compile(raw["pattern"])
        except (KeyError, re.error):
            continue  # a bad custom pattern must not stop the built-ins
        replacement = str(raw.get("replacement", "[REDACTED_CUSTOM]"))
        result = _replace(
            result, pattern, mode, None, replacement,
            lambda: detections.append(Detection("CUSTOM", "MEDIUM")),
        )

    result, entropy_hits = _redact_high_entropy(result, mode)
    detections += entropy_hits
    return Result(result, detections)


def _redact_high_entropy(text: str, mode: str) -> tuple[str, list[Detection]]:
    """Catch secrets no pattern anticipated. Hex digests top out at 4 bits
    per character, so the 4.5 threshold leaves commit SHAs alone."""
    hits = []
    spans = []
    for m in _ENTROPY_TOKEN.finditer(text):
        token = m.group(0)
        if "REDACTED" in token or "SHA256" in token:
            continue
        if shannon_entropy(token) > ENTROPY_THRESHOLD:
            spans.append((m.start(), m.end(), token))

    for start, end, token in reversed(spans):  # reverse keeps offsets valid
        replacement = _hash(token) if mode == "hash" else "[REDACTED_HIGH_ENTROPY]"
        text = text[:start] + replacement + text[end:]
        hits.append(Detection("HIGH_ENTROPY", "MEDIUM"))
    return text, hits


_SEVERITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def summarize(detections: list[Detection]) -> dict[str, str]:
    """{name: worst severity seen} — what gets stored on a receipt."""
    found: dict[str, str] = {}
    for d in detections:
        if (d.name not in found
                or _SEVERITY_ORDER.index(d.severity) > _SEVERITY_ORDER.index(found[d.name])):
            found[d.name] = d.severity
    return found


def scan(text: str, cfg: RedactionConfig | None = None) -> list[Detection]:
    """What redaction would find, without changing anything. Used at capture
    so `doctor` can report secrets sitting in the record."""
    return redact(text, cfg).detections
