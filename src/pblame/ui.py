"""Terminal output.

Restrained colour and a small symbol set, degrading to ASCII when the console
cannot encode it — a Windows console defaults to cp1252 and once crashed this
tool outright on a box-drawing character, so nothing here assumes Unicode.

Deliberately no emoji: this output belongs in a record people may keep for
audit, and it has to survive a legacy console. Colour and symbols carry the
hierarchy instead.

Runtime output states what happened. Why it works that way belongs in the
README, not in a status line.
"""

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"

def plural(n: int) -> str:
    """Suffix for a count: one prompt, two prompts."""
    return "" if n == 1 else "s"


_UNICODE = {"ok": "✓", "warn": "!", "bad": "✗", "arrow": "→",
            "dot": "•", "sep": "·"}
_ASCII = {"ok": "+", "warn": "!", "bad": "x", "arrow": "->",
          "dot": "-", "sep": "|"}


def _enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING, so older consoles colour too
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle in (-11, -12):  # stdout, stderr
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(kernel32.GetStdHandle(handle), ctypes.byref(mode)):
                kernel32.SetConsoleMode(kernel32.GetStdHandle(handle), mode.value | 0x4)
    except Exception:
        pass  # cosmetic only


def _symbols(stream) -> dict[str, str]:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "".join(_UNICODE.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _ASCII
    return _UNICODE


_ansi_ready = False


class Out:
    """Writes to one stream, colouring only when it is a terminal.

    The stream is looked up per call rather than captured once: anything that
    replaces sys.stdout afterwards — a test harness, a wrapper — would
    otherwise leave this writing to a closed file.
    """

    def __init__(self, name: str):
        self._name = name  # "stdout" or "stderr"

    @property
    def stream(self):
        return getattr(sys, self._name)

    @property
    def color(self) -> bool:
        global _ansi_ready
        try:
            tty = self.stream.isatty()
        except Exception:
            return False  # closed or exotic stream
        if not tty or "NO_COLOR" in os.environ:
            return False
        if not _ansi_ready:
            _enable_windows_ansi()
            _ansi_ready = True
        return True

    @property
    def sym(self) -> dict[str, str]:
        return _symbols(self.stream)

    def _paint(self, text: str, *codes: str) -> str:
        return f"{''.join(codes)}{text}{RESET}" if self.color else text

    def _line(self, text: str = "") -> None:
        print(text, file=self.stream)

    def ok(self, message: str) -> None:
        self._line(f"{self._paint(self.sym['ok'], GREEN, BOLD)} {message}")

    def warn(self, message: str) -> None:
        self._line(f"{self._paint(self.sym['warn'], YELLOW, BOLD)} {message}")

    def bad(self, message: str) -> None:
        self._line(f"{self._paint(self.sym['bad'], RED, BOLD)} {message}")

    def plain(self, message: str = "") -> None:
        self._line(message)

    def field(self, label: str, value: str, width: int = 20) -> None:
        self._line(f"  {self._paint(label.ljust(width), DIM)} {value}")

    def note(self, message: str) -> None:
        self._line(f"  {self._paint(message, DIM)}")

    def next_step(self, command: str, why: str = "") -> None:
        tail = f"   {self._paint(why, DIM)}" if why else ""
        self._line(f"  {self._paint(self.sym['arrow'], CYAN)} "
                   f"{self._paint(command, CYAN)}{tail}")

    def hook(self, message: str) -> None:
        """Output from inside a git hook, mixed into git's own. Stays on one
        line and names itself, because the reader did not ask for it."""
        self._line(f"{self._paint('pblame', DIM)} {message}")


out = Out("stdout")
err = Out("stderr")
