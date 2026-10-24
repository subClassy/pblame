"""Rendering for `pblame search`.

The prompt text is the thing being searched, so it gets the space and the
highlight; everything else is context and stays dim.
"""

import re
import textwrap

from . import ui
from .index import Entry

WIDTH = 76


def _highlight(text: str, matcher: re.Pattern | None, color: bool) -> str:
    if not matcher or not color:
        return text
    return matcher.sub(lambda m: f"{ui.YELLOW}{ui.BOLD}{m.group(0)}{ui.RESET}", text)


def _files(entry: Entry) -> str:
    parts = []
    for f in entry.receipt.files:
        spans = ",".join(f"{s}-{e}" if s != e else str(s) for s, e in f.ranges)
        parts.append(f"{f.path} {spans}" if spans else f"{f.path} {f.label()}")
    # Via the symbol set, so a cp1252 console gets an ASCII separator rather
    # than a replacement character.
    return f" {ui.out.sym['sep']} ".join(parts)


def render(hits: list[Entry], matcher: re.Pattern | None = None,
           total: int = 0, color: bool = True, matched: int | None = None) -> str:
    def paint(text: str, *codes: str) -> str:
        return f"{''.join(codes)}{text}{ui.RESET}" if color else text

    if not hits:
        return paint(f"  No prompts matched (searched {total}).", ui.DIM)

    out = [""]
    for e in hits:
        meta = f"{e.sha[:7]}  {e.prompt.timestamp:%Y-%m-%d %H:%M}  {e.prompt.model}"
        if e.author:
            meta += f"  {e.author}"
        if e.shared:
            meta += "  (shared)"
        out.append("  " + paint(meta, ui.DIM))

        # Wrap first, highlight second: the colour codes would otherwise be
        # counted as visible width and wreck the wrapping.
        for line in textwrap.wrap(e.prompt.text.strip(), WIDTH) or ["(empty)"]:
            out.append("    " + _highlight(line, matcher, color))

        files = _files(e)
        if files:
            out.append("    " + paint(textwrap.shorten(files, WIDTH + 4,
                                                       placeholder=" ..."), ui.DIM))
        out.append("")

    matched = len(hits) if matched is None else matched
    # Counted from what matched, not what --limit let through: a trimmed
    # list read "2 of 9 recorded prompts" when 4 had matched.
    if matched > len(hits):
        shown = (f"{len(hits)} of {matched} matches, "
                 f"{total} recorded prompt{ui.plural(total)}")
    else:
        shown = f"{matched} of {total} recorded prompt{ui.plural(total)}"
    out.append("  " + paint(shown, ui.DIM))
    return "\n".join(out)
