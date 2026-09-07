"""Agent adapters: each module turns one agent's hook events into staging
updates via handle(payload). New agent = new module registered here."""

from . import claude_code

_ADAPTERS = {"claude": claude_code}


def names() -> list[str]:
    return sorted(_ADAPTERS)


def get(name: str):
    return _ADAPTERS[name]
