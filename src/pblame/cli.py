import argparse
import json
import sys
from pathlib import Path

from . import adapters, git_hooks, notes
from .snapshot import GitError, repo_root


def cmd_hook(args: argparse.Namespace) -> int:
    try:
        adapters.get(args.agent).handle(json.loads(sys.stdin.read()))
    except Exception as e:
        # A broken hook must never break the agent's turn: report, exit 0.
        print(f"pblame: hook error: {e}", file=sys.stderr)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError as e:
        print(f"pblame: {args.repo} is not a git repository ({e})", file=sys.stderr)
        return 1
    settings = adapters.get("claude").install(repo)
    hook = git_hooks.install_post_commit(repo)
    print(f"pblame: installed Claude Code hooks in {settings}")
    print(f"pblame: installed post-commit hook in {hook}")
    print("pblame: recording starts with the next Claude Code session in this repo")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pblame")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="install recording hooks in a repo")
    init.add_argument("repo", nargs="?", default=".", help="repo to record (default: cwd)")
    init.set_defaults(func=cmd_init)

    hook = sub.add_parser("hook", help="handle an agent hook event (JSON on stdin)")
    hook.add_argument("agent", choices=adapters.names())
    hook.set_defaults(func=cmd_hook)

    attach = sub.add_parser("attach", help="attach staged receipts to HEAD (run by post-commit)")
    attach.set_defaults(func=cmd_attach)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
