import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import adapters, blame, config, doctor, git_hooks, notes, redact
from .snapshot import GitError, git, repo_root


def cmd_hook(args: argparse.Namespace) -> int:
    payload: dict = {}
    try:
        # Hook payloads are UTF-8; Windows would otherwise decode them as cp1252
        # and mangle every non-ASCII character in the prompt.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        adapters.get(args.agent).handle(payload)
    except Exception as e:
        # A broken hook must never break the agent's turn: log, exit 0.
        _log_hook_error(payload, e)
    return 0


def _log_hook_error(payload: dict, error: Exception) -> None:
    """Leave a trace in the repo's hook log. Silent failure is the worst
    outcome here: recording can stop for a whole session unnoticed."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} hook: {type(error).__name__}: {error}"
    print(f"pblame: {line}", file=sys.stderr)
    try:
        log = repo_root(Path(payload.get("cwd") or ".")) / ".git" / "pblame" / "hook.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            print(line, file=f)
    except Exception:
        pass  # the error path must never raise


def cmd_init(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError as e:
        print(f"pblame: {args.repo} is not a git repository ({e})", file=sys.stderr)
        return 1
    settings = adapters.get("claude").install(repo)
    hooks = git_hooks.install_hooks(repo)
    print(f"pblame: installed Claude Code hooks in {settings}")
    for hook in hooks:
        print(f"pblame: installed {hook.name} hook in {hook}")
    print("pblame: recording starts with the next Claude Code session in this repo")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError as e:
        print(f"pblame: {args.repo} is not a git repository ({e})", file=sys.stderr)
        return 1

    for path in adapters.get("claude").uninstall(repo) + git_hooks.uninstall_hooks(repo):
        print(f"pblame: removed hooks from {path}")
    print("pblame: recording stopped for this repo")

    if not args.purge:
        print("pblame: recorded history kept (refs/notes/pblame and .git/pblame/);"
              " add --purge to delete it")
        return 0

    state_dir = repo / ".git" / "pblame"
    if state_dir.exists():
        shutil.rmtree(state_dir)
        print(f"pblame: deleted {state_dir}")
    try:
        git(repo, "update-ref", "-d", notes.NOTES_REF)
        print(f"pblame: deleted {notes.NOTES_REF} - every recorded prompt is gone")
    except GitError:
        pass  # no notes were ever written
    return 0


def cmd_rewrite(args: argparse.Namespace) -> int:
    """Run by the post-rewrite hook: stdin carries "<old> <new>" per line."""
    try:
        repo = repo_root(Path.cwd())
        moved = 0
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                moved += notes.remap(repo, parts[0], parts[1])
        if moved:
            print(f"[pblame] carried {moved} prompt receipt(s) onto rewritten commits")
    except Exception as e:
        print(f"pblame: rewrite error: {e}", file=sys.stderr)
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    # Runs from the post-commit hook: never fail the caller.
    try:
        attached = notes.attach_staged(repo_root(Path.cwd()))
    except Exception as e:
        print(f"pblame: attach error: {e}", file=sys.stderr)
        return 0
    if attached:
        print(f"[pblame] attached {len(attached)} prompt receipt(s) to this commit")
    return 0


def cmd_blame(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path.cwd())
        rel = Path(args.file).resolve().relative_to(repo).as_posix()
    except GitError as e:
        print(f"pblame: {e}", file=sys.stderr)
        return 1
    except ValueError:
        print(f"pblame: {args.file} is outside the repository", file=sys.stderr)
        return 1

    try:
        lines = blame.attribute(repo, rel)
    except GitError as e:
        print(f"pblame: cannot blame {rel} ({e})", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(blame.to_json(lines, rel), indent=2))
    else:
        color = sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ
        print(blame.render(lines, rel, color=color, glyphs=blame.glyphs_for(sys.stdout)))
    return 0


def cmd_redact(args: argparse.Namespace) -> int:
    """Run the engine over text so patterns can be tuned without recording
    anything. Redacted text goes to stdout, the summary to stderr, so the
    output stays pipeable."""
    cfg = None
    try:
        cfg = config.load(repo_root(Path.cwd())).redaction
    except config.ConfigError as e:
        print(f"pblame: {e}", file=sys.stderr)
        return 1
    except GitError:
        pass  # a plain text filter; no repo required

    if args.file in (None, "-"):
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    else:
        try:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"pblame: cannot read {args.file}: {e}", file=sys.stderr)
            return 1

    result = redact.redact(text, cfg)
    print(result.text, end="" if text.endswith("\n") else "\n")
    if result.detections:
        found = ", ".join(f"{n}x{c}" if c > 1 else n
                          for n, c in sorted(result.counts.items()))
        print(f"pblame: {len(result.detections)} detection(s): {found}"
              f" (worst {result.worst()})", file=sys.stderr)
    else:
        print("pblame: nothing detected", file=sys.stderr)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError:
        print(f"pblame: {args.repo} is not a git repository", file=sys.stderr)
        return 1
    checks = doctor.run(repo)
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print(doctor.render(checks, color=color))
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path.cwd())
    except GitError as e:
        print(f"pblame: {e}", file=sys.stderr)
        return 1
    receipts = notes.read(repo, args.commit)
    if not receipts:
        print(f"pblame: no prompt receipts recorded for {args.commit}")
        return 0
    for r in receipts:
        print(f"{r.prompt.model} - {r.prompt.timestamp:%Y-%m-%d %H:%M} - {r.prompt.session_id}")
        print(f"  {r.prompt.text.strip()}")
        for fc in r.files:
            spans = ", ".join(f"{s}-{e}" if s != e else str(s) for s, e in fc.ranges)
            print(f"    {fc.path}  {spans or '(no surviving lines)'}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    # Blamed source lines can hold characters the console cannot encode (a
    # cp1252 Windows console cannot print an emoji). Degrade, never crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(prog="pblame")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="install recording hooks in a repo")
    init.add_argument("repo", nargs="?", default=".", help="repo to record (default: cwd)")
    init.set_defaults(func=cmd_init)

    un = sub.add_parser("uninstall", help="remove recording hooks from a repo")
    un.add_argument("repo", nargs="?", default=".")
    un.add_argument("--purge", action="store_true",
                    help="also delete recorded history (notes ref and .git/pblame/)")
    un.set_defaults(func=cmd_uninstall)

    hook = sub.add_parser("hook", help="handle an agent hook event (JSON on stdin)")
    hook.add_argument("agent", choices=adapters.names())
    hook.set_defaults(func=cmd_hook)

    attach = sub.add_parser("attach", help="attach staged receipts to HEAD (run by post-commit)")
    attach.set_defaults(func=cmd_attach)

    rewrite = sub.add_parser("rewrite", help="carry notes onto rewritten commits (run by post-rewrite)")
    rewrite.set_defaults(func=cmd_rewrite)

    bl = sub.add_parser("blame", help="show a file annotated with the prompt behind each line")
    bl.add_argument("file")
    bl.add_argument("--json", action="store_true", help="machine-readable output")
    bl.add_argument("--no-color", action="store_true")
    bl.set_defaults(func=cmd_blame)

    show = sub.add_parser("show", help="show all prompt receipts recorded for a commit")
    show.add_argument("commit", nargs="?", default="HEAD")
    show.set_defaults(func=cmd_show)

    red = sub.add_parser("redact", help="show what redaction would do to some text")
    red.add_argument("file", nargs="?", default="-", help="file to read, or - for stdin")
    red.set_defaults(func=cmd_redact)

    doc = sub.add_parser("doctor", help="check that this repo is actually being recorded")
    doc.add_argument("repo", nargs="?", default=".")
    doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
