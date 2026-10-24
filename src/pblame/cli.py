import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import (adapters, blame, config, doctor, git_hooks, index, notes, redact,
               repair, searchview, share, staging, ui)
from .ui import plural
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
    ui.err.bad(line)
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
        ui.err.bad(f"{args.repo} is not a git repository ({e})")
        return 1
    settings = adapters.get("claude").install(repo)
    hooks = git_hooks.install_hooks(repo)
    ui.out.ok(f"Recording set up in {repo.name}")
    ui.out.plain()
    ui.out.field("Claude Code hooks", str(settings.relative_to(repo)))
    ui.out.field("git hooks", ", ".join(h.name for h in hooks))
    override = git_hooks.hooks_path_override(repo)
    if override:
        ui.out.plain()
        ui.out.note(f"core.hooksPath is {override} (husky?), so git will not run these hooks.")
        ui.out.note("Commits are attributed at your next prompt or pblame command instead.")
    ui.out.plain()
    ui.out.note("Open a new Claude Code session - hooks load when a session starts.")
    # A fresh clone has no hooks (git never clones them) and its first pull is
    # a no-op, so joining a team that already shares needs one explicit step.
    try:
        if git(repo, "remote").split() and config.load(repo).share.enabled:
            ui.out.next_step("pblame pull", "fetch prompts your team already shared")
    except (GitError, config.ConfigError):
        pass
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError as e:
        ui.err.bad(f"{args.repo} is not a git repository ({e})")
        return 1

    removed = adapters.get("claude").uninstall(repo) + git_hooks.uninstall_hooks(repo)
    ui.out.ok(f"Recording stopped in {repo.name}")
    if removed:
        ui.out.field("hooks removed", ", ".join(x.name for x in removed))

    if not args.purge:
        ui.out.plain()
        ui.out.note("Recorded prompts were kept.")
        ui.out.next_step("pblame uninstall --purge", "delete them too")
        return 0

    state_dir = repo / ".git" / "pblame"
    if state_dir.exists():
        shutil.rmtree(state_dir)
        ui.out.field("deleted", str(state_dir.relative_to(repo)))

    # Every pblame ref, not just the one this command was written for: the
    # redacted mirror used to survive a purge still holding every prompt.
    for ref in notes.all_refs(repo):
        try:
            git(repo, "update-ref", "-d", ref)
            ui.out.field("deleted", ref)
        except GitError:
            ui.err.warn(f"could not delete {ref}")
    ui.out.note("Every recorded prompt is gone.")
    return 0


def cmd_rewrite(args: argparse.Namespace) -> int:
    """Run by the post-rewrite hook: stdin carries "<old> <new>" per line."""
    try:
        repo = repo_root(Path.cwd())
        moved = 0
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                moved += notes.remap_all(repo, parts[0], parts[1])
        if moved:
            ui.out.hook(f"carried {moved} prompt{plural(moved)} onto the rewritten commit")
    except Exception as e:
        ui.err.bad(f"rewrite failed: {e}")
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    # Runs from the post-commit hook: never fail the caller.
    try:
        attached = notes.attach_staged(repo_root(Path.cwd()))
    except Exception as e:
        ui.err.bad(f"attach failed: {e}")
        return 0
    if attached:
        ui.out.hook(f"attached {len(attached)} prompt{plural(len(attached))} to this commit")
    return 0


def _use_color(args: argparse.Namespace) -> bool:
    """git's `--color=always` semantics, spelled `--color`.

    Forcing matters whenever stdout is not a terminal but something that can
    still render colour: `| less -R`, or capturing the output for a document.
    An explicit flag beats NO_COLOR, because the user just asked.
    """
    if getattr(args, "no_color", False):
        return False
    if getattr(args, "color", False):
        return True
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _color_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--color", action="store_true",
                       help="colour even when the output is not a terminal")
    group.add_argument("--no-color", action="store_true")


def _catch_up(repo: Path) -> None:
    """Attach anything committed while the git hooks were not running, so a
    command reading the record sees all of it. Never fatal to the command."""
    try:
        notes.reconcile_now(repo)
    except Exception as e:
        staging.log_failure(repo, "attach", e)


def cmd_blame(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path.cwd())
        rel = Path(args.file).resolve().relative_to(repo).as_posix()
    except GitError as e:
        ui.err.bad(str(e))
        return 1
    except ValueError:
        ui.err.bad(f"{args.file} is outside the repository")
        return 1

    _catch_up(repo)
    try:
        lines = blame.attribute(repo, rel)
    except GitError as e:
        ui.err.bad(f"Cannot blame {rel} ({e})")
        return 1

    try:
        lines = blame.select(lines, args.lines)
    except ValueError as e:
        ui.err.bad(str(e))
        return 1
    shown = f"{rel}:{args.lines}" if args.lines else rel

    if args.json:
        print(json.dumps(blame.to_json(lines, rel), indent=2))
    else:
        print(blame.render(lines, shown, color=_use_color(args),
                           glyphs=blame.glyphs_for(sys.stdout)))
    return 0


def cmd_redact(args: argparse.Namespace) -> int:
    """Run the engine over text so patterns can be tuned without recording
    anything. Redacted text goes to stdout, the summary to stderr, so the
    output stays pipeable."""
    cfg = None
    try:
        cfg = config.load(repo_root(Path.cwd())).redaction
    except config.ConfigError as e:
        ui.err.bad(str(e))
        return 1
    except GitError:
        pass  # a plain text filter; no repo required

    if args.file in (None, "-"):
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    else:
        try:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            ui.err.bad(f"Cannot read {args.file}: {e}")
            return 1

    result = redact.redact(text, cfg)
    print(result.text, end="" if text.endswith("\n") else "\n")
    if result.detections:
        found = ", ".join(f"{n} x{c}" if c > 1 else n
                          for n, c in sorted(result.counts.items()))
        ui.err.warn(f"{len(result.detections)} found ({result.worst()}): {found}")
    else:
        ui.err.ok("Nothing detected")
    return 0


def _repo_and_config(path: str = "."):
    repo = repo_root(Path(path).resolve())
    return repo, config.load(repo)


def cmd_share(args: argparse.Namespace) -> int:
    """Opt this developer in or out. Writes the personal, gitignored file, so
    one person turning sharing on never turns it on for the whole team."""
    try:
        repo = repo_root(Path.cwd())
    except GitError as e:
        ui.err.bad(str(e))
        return 1

    path = repo / config.LOCAL_FILENAME
    if args.off:
        raw = json.loads(path.read_text(encoding=config.USER_TEXT)) if path.exists() else {}
        raw.setdefault("share", {})["enabled"] = False
        path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        ui.out.ok("Sharing off - prompts stay on this machine")
        ui.out.field("written to", path.name)
        return 0

    config.enable_sharing(repo, args.remote)
    git_hooks.ensure_ignored(repo, config.LOCAL_FILENAME)
    ui.out.ok(f"Sharing on, remote {config.load(repo).share.remote}")
    ui.out.field("written to", f"{path.name} (gitignored)")
    ui.out.plain()
    ui.out.next_step("pblame push --dry-run", "see exactly what would be sent")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    try:
        repo, cfg = _repo_and_config()
        if args.remote:
            cfg.share.remote = args.remote
    except (GitError, config.ConfigError) as e:
        ui.err.bad(str(e))
        return 1

    if args.if_enabled and not cfg.share.enabled:
        return 0  # run from a hook; sharing is off, so there is nothing to say

    _catch_up(repo)

    if args.dry_run:
        planned = share.plan(repo, cfg)
        ui.out.plain(f"Would send to {cfg.share.remote} {notes.NOTES_REF}")
        ui.out.plain()
        ui.out.plain(share.describe(planned, redacted_only=args.secrets_only))
        ui.out.plain()
        if cfg.share.enabled:
            ui.out.next_step("pblame push", "send it")
        else:
            ui.out.note("Sharing is off. Nothing was sent.")
            ui.out.next_step("pblame share", "turn it on")
        return 0

    try:
        planned = share.push(repo, cfg)
    except share.ShareDisabled as e:
        ui.err.bad(str(e))
        return 1
    except GitError as e:
        ui.err.bad(f"Push failed: {e}")
        return 1

    if not planned:
        # It used to report "Already shared, 0 prompts on origin".
        if not args.if_enabled:  # a hook should not announce a no-op
            ui.out.ok("Nothing recorded yet, so nothing to share")
        return 0

    total = share.shared_total(repo)
    # `changed`, not every receipt in a changed note: one edited redaction
    # rule touching two prompts was reported as four.
    new = sum(len(item.changed) for item in planned)
    secrets = sum(len(item.changed_detections) for item in planned)

    if not new:
        summary = f"Already shared, {total} prompt{plural(total)} on {cfg.share.remote}"
    else:
        summary = (f"Shared {new} new prompt{plural(new)} to {cfg.share.remote}"
                   f" ({total} total)")
    redacted = f"{secrets} secret{plural(secrets)} redacted" if secrets else ""
    if args.if_enabled:  # running inside git push; stay on one line
        ui.out.hook(summary[0].lower() + summary[1:]
                    + (f", {redacted}" if redacted else ""))
        return 0
    ui.out.ok(summary)
    if redacted:
        ui.out.field("redacted", redacted)
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    try:
        repo, cfg = _repo_and_config()
        if args.remote:
            cfg.share.remote = args.remote
        if args.if_enabled and not cfg.share.enabled:
            return 0
        pulled = share.pull(repo, cfg)
    except (GitError, config.ConfigError) as e:
        ui.err.bad(f"Pull failed: {e}")
        return 1

    # Lead with what arrived. Reporting only the coverage read as "17 prompts
    # came in" when one had.
    n = pulled.new_prompts
    summary = (f"Pulled {n} new prompt{plural(n)} from {cfg.share.remote}"
               if n else "Up to date")
    covered = f"{pulled.commits} commit{plural(pulled.commits)}"
    if args.if_enabled:  # running inside git pull
        ui.out.hook(f"{summary[0].lower()}{summary[1:]}, shared history covers {covered}")
    else:
        ui.out.ok(summary)
        ui.out.field("shared history", covered)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path.cwd())
    except GitError as e:
        ui.err.bad(str(e))
        return 1
    _catch_up(repo)

    try:
        query = index.Query(
            text=" ".join(args.text) or None,
            regex=args.regex,
            path=args.path,
            since=index.parse_when(args.since) if args.since else None,
            until=index.parse_when(args.until) if args.until else None,
            model=args.model,
            author=args.author,
            mine=args.mine,
        )
    except ValueError as e:
        ui.err.bad(f"Cannot read a date from that ({e})")
        return 1

    entries = index.load(repo)
    hits, matcher = index.search(entries, query)
    if args.limit and len(hits) > args.limit:
        hits = hits[: args.limit]

    if args.json:
        print(json.dumps(index.to_json(hits), indent=2))
        return 0

    print(searchview.render(hits, matcher, total=len(entries),
                            color=_use_color(args)))
    return 0 if hits else 1


def cmd_repair(args: argparse.Namespace) -> int:
    """Re-clean prompts recorded before clean_prompt existed, and refresh the
    secret scan. Previews unless --write, because it rewrites history."""
    try:
        repo, cfg = _repo_and_config()
    except (GitError, config.ConfigError) as e:
        ui.err.bad(str(e))
        return 1

    plans = repair.plan(repo, cfg)
    if not plans:
        ui.out.ok("Nothing to repair")
        return 0

    if not args.write:
        ui.out.plain("Would change:")
        ui.out.plain()
        ui.out.plain(repair.describe(plans))
        ui.out.plain()
        ui.out.next_step("pblame repair --write", "apply these")
        return 0

    changed = repair.apply(repo, plans)
    ui.out.ok(f"Repaired {changed} prompt{plural(changed)}"
              f" across {len(plans)} note{plural(len(plans))}")
    ui.out.note(f"The previous state is still in {notes.NOTES_REF}@{{1}}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path(args.repo).resolve())
    except GitError:
        ui.err.bad(f"{args.repo} is not a git repository")
        return 1
    checks = doctor.run(repo)
    print(doctor.render(checks, color=_use_color(args)))
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        repo = repo_root(Path.cwd())
    except GitError as e:
        ui.err.bad(str(e))
        return 1
    _catch_up(repo)
    # Merged, so a teammate's shared prompts show up and not just our own.
    receipts = notes.read_merged(repo, args.commit)
    if not receipts:
        ui.out.note(f"No prompts recorded for {args.commit}")
        return 0
    for r in receipts:
        print(f"{r.prompt.model} - {r.prompt.timestamp:%Y-%m-%d %H:%M} - {r.prompt.session_id}")
        print(f"  {r.prompt.text.strip()}")
        for fc in r.files:
            spans = ", ".join(f"{s}-{e}" if s != e else str(s) for s, e in fc.ranges)
            print(f"    {fc.path}  {spans or fc.label()}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    # Blamed source lines can hold characters the console cannot encode (a
    # cp1252 Windows console cannot print an emoji). Degrade, never crash.
    #
    # Redirected output is a different problem: there the locale codepage is
    # nobody's intent. An em dash was leaving as cp1252 0x97 and arriving as
    # mojibake, so a pipe or a file gets UTF-8 — a console keeps whatever it
    # can actually display.
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
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
    bl.add_argument("-L", "--lines", metavar="N,M",
                    help="only these lines, as git blame spells it: 5,8 or 5")
    bl.add_argument("--json", action="store_true", help="machine-readable output")
    _color_flags(bl)
    bl.set_defaults(func=cmd_blame)

    show = sub.add_parser("show", help="show all prompt receipts recorded for a commit")
    show.add_argument("commit", nargs="?", default="HEAD")
    show.set_defaults(func=cmd_show)

    sh = sub.add_parser("share", help="opt in (or out) of sharing prompts with your team")
    sh.add_argument("--off", action="store_true", help="stop sharing")
    sh.add_argument("--remote")
    sh.set_defaults(func=cmd_share)

    push = sub.add_parser("push", help="share the record: redact, then push the notes ref")
    push.add_argument("--dry-run", action="store_true",
                      help="print exactly what would be sent, and send nothing")
    push.add_argument("--secrets-only", action="store_true",
                      help="with --dry-run, show only prompts that had something redacted")
    push.add_argument("--remote")
    push.add_argument("--if-enabled", action="store_true",
                      help="do nothing unless sharing is on (used by the pre-push hook)")
    push.set_defaults(func=cmd_push)

    pull = sub.add_parser("pull", help="fetch and merge what teammates shared")
    pull.add_argument("--remote")
    pull.add_argument("--if-enabled", action="store_true",
                      help="do nothing unless sharing is on (used by the post-merge hook)")
    pull.set_defaults(func=cmd_pull)

    red = sub.add_parser("redact", help="show what redaction would do to some text")
    red.add_argument("file", nargs="?", default="-", help="file to read, or - for stdin")
    red.set_defaults(func=cmd_redact)

    find = sub.add_parser("search", help="search recorded prompts")
    find.add_argument("text", nargs="*", help="words to look for in the prompt text")
    find.add_argument("--regex", action="store_true", help="treat the text as a regex")
    find.add_argument("--path", help="only prompts that touched this file or glob")
    find.add_argument("--since", help="ISO date, or an age like 7d / 2w / 3m")
    find.add_argument("--until", help="ISO date, or an age like 7d / 2w / 3m")
    find.add_argument("--model", help="only prompts answered by this model")
    find.add_argument("--author", help="only prompts from this commit author")
    find.add_argument("--mine", action="store_true",
                      help="exclude prompts that only came from teammates")
    find.add_argument("--limit", type=int, default=20, help="0 for no limit")
    find.add_argument("--json", action="store_true")
    _color_flags(find)
    find.set_defaults(func=cmd_search)

    rep = sub.add_parser("repair",
                         help="re-clean recorded prompts and refresh the secret scan")
    rep.add_argument("--write", action="store_true",
                     help="apply the changes instead of previewing them")
    rep.set_defaults(func=cmd_repair)

    doc = sub.add_parser("doctor", help="check that this repo is actually being recorded")
    doc.add_argument("repo", nargs="?", default=".")
    _color_flags(doc)
    doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
