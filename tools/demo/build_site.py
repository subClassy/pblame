"""Build the site from the template and the real demo repo.

    python tools/demo/build_site.py --repo https://github.com/<you>/pblame
    python tools/demo/build_site.py --repo ... --preview out/preview.html

The blame data comes from `pblame blame --json` run against the demo repo, and
prompt text goes through the same redaction a push applies — the page shows
what a teammate would see, not the author's verbatim record.
"""
import argparse
import base64
import collections
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pblame import redact  # noqa: E402
from pblame.config import RedactionConfig  # noqa: E402

SITE = ROOT / "site"
TEMPLATE = SITE / "src" / "template.html"
MEDIA = SITE / "media"
PBLAME = ROOT / ".venv" / "Scripts" / "pblame.exe"
DEMO_REPO = Path("C:/demo/envdiff")
FILE = "envdiff.py"


def blame_data() -> dict:
    out = subprocess.run([str(PBLAME), "blame", FILE, "--json"], cwd=DEMO_REPO,
                         capture_output=True, check=True)
    raw = json.loads(out.stdout.decode("utf-8"))

    order: list[str] = []
    by_id: dict[str, dict] = {}
    commits: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    lines = []
    for line in raw["lines"]:
        p = line["prompt"]
        index = -1
        if p:
            if p["id"] not in by_id:
                order.append(p["id"])
                by_id[p["id"]] = p
            index = order.index(p["id"])
            commits[p["id"]][line["commit"][:7]] += 1
        lines.append({"n": line["line"], "t": line["text"], "p": index})

    prompts = []
    for pid in order:
        p = by_id[pid]
        when = datetime.fromisoformat(p["timestamp"])
        prompts.append({
            "text": redact.redact(p["text"], RedactionConfig()).text,
            # Counted on the verbatim text: redaction swaps a value for a
            # placeholder, which is not the author's choice of words.
            "words": len(p["text"].split()),
            "model": p["model"],
            "commit": commits[pid].most_common(1)[0][0],
            "when": f"{when:%d %b %Y, %H:%M} UTC",
            "count": sum(1 for line in lines if line["p"] == order.index(pid)),
        })
    return {"file": FILE, "lines": lines, "prompts": prompts}


def render(template: str, data: dict, media_prefix: str, repo: str) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (template.replace("__DATA__", payload)
                    .replace("__MEDIA__", media_prefix)
                    .replace("__REPO__", repo))


def as_document(fragment: str) -> str:
    """GitHub Pages serves the file as-is, so it needs a real document."""
    head, sep, body = fragment.partition("</style>")
    assert sep, "template must contain exactly one </style>"
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            f"{head}{sep}\n</head>\n<body>\n{body}\n</body>\n</html>\n")


def inline_media(html: str) -> str:
    """For a preview that has to stand alone: every media file as a data URI."""
    for f in sorted(MEDIA.iterdir()):
        mime = {".mp4": "video/mp4", ".jpg": "image/jpeg"}.get(f.suffix)
        if mime:
            uri = f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()
            html = html.replace(f"media/{f.name}", uri)
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="public repo URL, used in links and the install line")
    ap.add_argument("--preview", help="also write a standalone preview fragment here")
    args = ap.parse_args()

    data = blame_data()
    # Checked before anything is written: this page is published.
    leaked = [s for s in ("hunter2correct", "AKIAIOSFODNN7EXAMPLE") if s in json.dumps(data)]
    if leaked:
        print(f"REFUSING: verbatim secret in page data: {leaked}", file=sys.stderr)
        return 1
    template = TEMPLATE.read_text(encoding="utf-8")

    page = as_document(render(template, data, "media/", args.repo))
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"site/index.html   {len(page):>9,} bytes   {len(data['lines'])} lines, {len(data['prompts'])} prompts")

    if args.preview:
        preview = inline_media(render(template, data, "media/", args.repo))
        Path(args.preview).write_text(preview, encoding="utf-8")
        print(f"{args.preview}   {len(preview):>9,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
