"""pblame blame: join `git blame` against the prompt receipts in git notes.

git blame maps each line of the working file back to the commit that last
touched it, and to that line's number *in that commit* — which is the
coordinate system the receipts recorded. So the join needs no line tracking
of its own: blame follows lines across later commits for free.
"""

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from . import notes
from .models import Receipt
from .snapshot import git

UNCOMMITTED = "0" * 40
_HEADER = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)")

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
# Distinguishable hues, cycled per prompt in the order prompts appear.
PALETTE = ["\033[36m", "\033[32m", "\033[35m", "\033[33m", "\033[34m", "\033[31m"]

UNICODE_GLYPHS = {"bar": "▎", "rule": "│"}
ASCII_GLYPHS = {"bar": "|", "rule": "|"}


def glyphs_for(stream) -> dict[str, str]:
    """Box-drawing glyphs, or ASCII when the stream cannot encode them —
    a Windows console defaults to cp1252 and would otherwise crash."""
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "".join(UNICODE_GLYPHS.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return ASCII_GLYPHS
    return UNICODE_GLYPHS


@dataclass
class Line:
    number: int  # line number in the working file
    text: str
    sha: str
    receipt: Receipt | None


def _blame(repo: Path, rel_path: str) -> list[tuple[str, int, str, str]]:
    """(sha, line number in that commit, path in that commit, content).

    Both the line number and the path are taken as of the blamed commit,
    because that is the coordinate system the receipts recorded. Matching on
    the file's current name would lose every receipt written before a rename.
    """
    out = git(repo, "blame", "--line-porcelain", "--", rel_path, strip=False)
    lines: list[tuple[str, int, str, str]] = []
    sha, orig, name = "", 0, rel_path
    for line in out.split("\n"):
        header = _HEADER.match(line)
        if header:
            sha, orig = header.group(1), int(header.group(2))
        elif line.startswith("filename "):
            name = line[len("filename "):]
        elif line.startswith("\t"):
            lines.append((sha, orig, name, line[1:]))
    return lines


def _owner(receipts: list[Receipt], path: str, line_no: int) -> Receipt | None:
    """The receipt owning this line. Later receipts win: when a prompt edits a
    line an earlier prompt wrote, the last writer owns it."""
    found = None
    for r in receipts:
        for fc in r.files:
            if fc.path == path and any(s <= line_no <= e for s, e in fc.ranges):
                found = r
    return found


def attribute(repo: Path, rel_path: str) -> list[Line]:
    by_sha: dict[str, list[Receipt]] = {}
    result = []
    for number, (sha, orig, name, text) in enumerate(_blame(repo, rel_path), start=1):
        if sha not in by_sha:
            by_sha[sha] = [] if sha == UNCOMMITTED else notes.read_merged(repo, sha)
        result.append(Line(number, text, sha, _owner(by_sha[sha], name, orig)))
    return result


def _groups(lines: list[Line]) -> list[tuple[Receipt | None, list[Line]]]:
    """Consecutive lines sharing an owner, so each prompt is stated once."""
    groups: list[tuple[Receipt | None, list[Line]]] = []
    for line in lines:
        key = line.receipt.prompt.id if line.receipt else None
        if groups and (groups[-1][0].prompt.id if groups[-1][0] else None) == key:
            groups[-1][1].append(line)
        else:
            groups.append((line.receipt, [line]))
    return groups


def render(lines: list[Line], rel_path: str, color: bool = True,
           glyphs: dict[str, str] | None = None) -> str:
    g = glyphs or UNICODE_GLYPHS

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    colors: dict[str, str] = {}
    for line in lines:
        if line.receipt and line.receipt.prompt.id not in colors:
            colors[line.receipt.prompt.id] = PALETTE[len(colors) % len(PALETTE)]

    attributed = sum(1 for line in lines if line.receipt)
    width = len(str(len(lines))) if lines else 1
    out = [
        paint(rel_path, BOLD)
        + paint(
            f"  {attributed}/{len(lines)} lines from {len(colors)} prompt(s)", DIM
        ),
        "",
    ]

    for receipt, group in _groups(lines):
        if receipt is None:
            out.append(paint(f"  {g['bar']} (not attributed to a prompt)", DIM))
        else:
            color_code = colors[receipt.prompt.id]
            prompt = receipt.prompt
            for chunk in textwrap.wrap(prompt.text.strip(), 72) or [""]:
                out.append("  " + paint(f"{g['bar']} {chunk}", color_code))
            meta = f"{prompt.model} - {group[0].sha[:7]} - {prompt.timestamp:%Y-%m-%d %H:%M}"
            out.append("  " + paint(f"{g['bar']} {meta}", DIM))

        bar = colors[receipt.prompt.id] if receipt else DIM
        for line in group:
            gutter = paint(g["bar"], bar) + paint(f"{line.number:>{width}} {g['rule']} ", DIM)
            out.append("  " + gutter + line.text)
        out.append("")

    return "\n".join(out)


def to_json(lines: list[Line], rel_path: str) -> dict:
    return {
        "file": rel_path,
        "lines": [
            {
                "line": line.number,
                "text": line.text,
                "commit": line.sha,
                "prompt": line.receipt.prompt.to_dict() if line.receipt else None,
            }
            for line in lines
        ],
    }
