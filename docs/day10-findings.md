# Day 10 findings — building the site

Found while researching git-ai, recording the demo with real Claude Code, and building
the page. None was fixed in this pass; the site does not depend on any of them, and the
README and site describe 20 honestly. Numbering continues from
[day9-fix-verification.md](day9-fix-verification.md).

| # | Severity | Finding |
|---|---|---|
| 20 | **silent failure** | Repos with `core.hooksPath` (husky) are never attributed, and `doctor` says recording is live |
| 21 | reporting | `search --limit 2` says "2 of 9 recorded prompts" when 4 matched |
| 22 | reporting | `doctor` headline says "Not recording reliably" when the only failure is a sharing-safety check |
| 23 | gap | `search --path` does not follow renames; `blame` does |
| 24 | reporting | a pure rename is listed as "(removed)" |

## 20. `core.hooksPath` turns pblame off, silently

Confirmed by test in a scratch repo. Husky sets `core.hooksPath=.husky`; git then ignores
`.git/hooks`, so `post-commit` never runs and every receipt stays in staging forever.
`doctor` checks that the hook *file* exists in `.git/hooks`, finds it, and reports
*"post-commit hook installed — Recording is live"*.

**Fix, in order:** `doctor` must read `core.hooksPath` and fail loudly; then attach lazily
(every hook event and every pblame command checks whether HEAD moved since staging) so
`post-commit` is an optimisation rather than a dependency. Do **not** install into
`.husky/`: it is committed, and our hook embeds an absolute path to the local binary. Full
reasoning in [git-ai-teardown.md](git-ai-teardown.md#1-stop-depending-on-post-commit-firing--finding-20-confirmed).

## 21. The search footer counts what it showed, not what matched

```
pblame search make            ->  4 of 9 recorded prompts
pblame search make --limit 2  ->  2 of 9 recorded prompts
```

Same family as day 8's 12–15. It should read *"2 of 4 matches, 9 recorded"* or similar.

## 22. `doctor` blames recording for a sharing concern

With sharing on and a critical-severity secret in any prompt:

```
✗ secrets in prompts     1 prompt contain AWS_KEY, PASSWORD (worst CRITICAL)
  Not recording reliably - 1 check failing
```

Recording is fine. The check exists to make someone look before publishing — and the push
redacts these anyway. Two separate problems: the headline should describe what failed,
not assume it is recording; and whether this should be a failure at all once redaction
is known to cover it is worth a decision. Also: "1 prompt contain" → "contains".

## 23. `search --path` does not follow renames

In the demo repo `envfile.py` was renamed to `dotenv_loader.py` by a later prompt:

```
pblame search --path dotenv_loader.py   ->  only the rename prompt
pblame search --path envfile.py         ->  the prompt that wrote the contents
pblame blame dotenv_loader.py           ->  correctly shows that prompt
```

Receipts record the path at the time, which is right for `blame` (it joins on commit-time
paths). `search` filters on the same stored path, so it answers "which prompts touched a
file *called* this" rather than "which prompts wrote this file". Following renames needs
`git log --follow` names for the queried path, joined to the receipts' paths.

## 24. A pure rename shows as "(removed)"

```
Rename envfile.py to dotenv_loader.py and update the import in envdiff.py.
dotenv_loader.py (removed) · envdiff.py 7
```

`dotenv_loader.py` was created. A rename that changes no lines records the path with empty
ranges, and the renderer reads empty ranges as a deletion. It needs to know which one it
is — the snapshot diff already has the rename (`-M`); the receipt does not keep it.

## Things that were not bugs

- **The trust dialog.** Claude Code now defaults its folder-trust prompt to *"No, exit"*.
  A tape pressing Enter blind declined it. Handled by trusting the demo folder once,
  separately; recorded in [tools/demo/README.md](../tools/demo/README.md).
- **"model: unknown".** A Claude Code session launched from inside another one inherits
  `CLAUDE_CODE_CHILD_SESSION` and switches transcript saving off, so the Stop hook could
  not read the model. Every tape and script now strips `CLAUDE*` variables first. Not a
  pblame bug — but pblame recording "unknown" silently is the same shape as finding 20,
  and `doctor` could notice a run of unknown models.
