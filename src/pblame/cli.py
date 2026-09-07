import argparse
import json
import sys

from . import adapters


def cmd_hook(args: argparse.Namespace) -> int:
    try:
        adapters.get(args.agent).handle(json.loads(sys.stdin.read()))
    except Exception as e:
        # A broken hook must never break the agent's turn: report, exit 0.
        print(f"pblame: hook error: {e}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pblame")
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook", help="handle an agent hook event (JSON on stdin)")
    hook.add_argument("agent", choices=adapters.names())
    hook.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
