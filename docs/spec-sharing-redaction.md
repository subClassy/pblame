# Spec — sharing and redaction (Phase 1)

Branch `feat/sharing-redaction`. Goal: a second person can see the record, and nobody
leaks a secret doing it.

Reuses blameprompt (MIT) wherever it has already solved something; every reuse and every
deliberate divergence is named below. Credit goes in [NOTICE](../NOTICE).

---

## 0. Prerequisite — note payload becomes JSONL

**Problem.** `refs/notes/pblame` is a git ref like any other. Two developers push, and the
second push is rejected or force-clobbers the first. Git solves this with
`git notes merge --strategy=union` (or `cat_sort_uniq`), but **those strategies are
line-based, and our note is one pretty-printed JSON object** — a line-wise union of two
JSON documents is not valid JSON.

blameprompt does not solve this. Its fetch refspec is `+refs/notes/blameprompt:...` — a
force fetch. Two developers means one silently overwrites the other.

**Decision.** Change the note payload to **one compact JSON receipt per line** (JSONL):

```
{"prompt":{"id":"a1b2",...},"pre_tree":"...","files":[...]}
{"prompt":{"id":"c3d4",...},"pre_tree":"...","files":[...]}
```

Then `union` and `cat_sort_uniq` are correct merges for free, and a conflicted note is
still readable. `notes.read` accepts both formats so existing recorded history keeps
working; `notes.write` only emits JSONL. Do this **first** — it is cheap now and
expensive once anyone has data worth keeping.

Version marker moves from a payload field to the note's first line:
`{"pblame":1}`, ignored by readers that do not care.

---

## 1. Redaction

### Reuse from blameprompt

Port `src/core/redact.rs` into `pblame/redact.py`, specifically:

- **The pattern table** — API keys (`sk-`, `key-`), AWS (`AKIA…`), `password|secret = "…"`,
  `Bearer …`, `token|auth = …`, home paths (`/Users/x`, `/home/x`). This is the genuinely
  reusable asset.
- **Shannon entropy detection** — flag tokens matching `[A-Za-z0-9+/=_-]{20,}` whose
  entropy exceeds 4.5. Catches secrets no pattern anticipated.
- **Two modes** — `replace` (`[REDACTED_API_KEY]`) and `hash`
  (`[SHA256:abc123def456...]`). Hash mode is worth keeping: it lets a reader see that the
  same secret appeared in two prompts without learning it.
- **Config shape** — `custom_patterns`, `disable_patterns`, `mode`.

### Diverge from blameprompt

**Redact at the boundary, not at capture.** Every one of their ~30 call sites redacts
inside the hook, before staging. That means the author's own record is mangled too, and
irreversibly.

Their host pattern shows why that hurts:

```
'upgrade lodash@4.17.21 please'  ->  'upgrade [REDACTED_HOST] please'
'use node@20'                   ->  'use [REDACTED_HOST]'
```

Ordinary dependency prompts, destroyed permanently, in a tool whose headline feature
scores prompt quality. We will:

1. **Capture stores the prompt verbatim.** It is already inside `.git`, exactly as private
   as the code next to it.
2. **Capture *scans* and records detections** — type and severity, not the secret — and
   `doctor` surfaces them. Detect and tell; never silently mangle. Same principle as the
   hook log: silence is the worst outcome.
3. **Redaction runs when a receipt crosses the machine boundary**, i.e. in `pblame push`.
   The dangerous moment is publication, so that is where the filter sits. False positives
   then cost fidelity in the shared copy only.

**Fix the host pattern** rather than porting it as-is: require a dot-separated TLD-ish tail
and exclude a leading version-like segment, or drop it to `LOW` and off by default.
`/Users/x` and `/home/x` stay.

**The hole this leaves.** A manual `git push origin refs/notes/pblame` bypasses our
redaction entirely. Mitigations, all three:
- `pblame push` is the sanctioned route and the README says so.
- The `pre-push` hook refuses to push the notes ref if sharing is not enabled, and routes
  it through redaction when it is.
- `doctor` reports unredacted high-severity detections sitting in shareable history.

### Config

`.pblame.json` in the repo root, falling back to `~/.pblame.json`:

```json
{
  "share": { "enabled": false, "remote": "origin" },
  "redaction": {
    "mode": "replace",
    "disable_patterns": ["HOME_PATH"],
    "custom_patterns": [
      { "pattern": "CUST-\\d{6,}", "replacement": "[REDACTED_CUSTOMER_ID]" }
    ]
  }
}
```

JSON, not blameprompt's TOML: `tomllib` is Python 3.11+ and our floor is 3.10. Not worth
raising the floor or taking a dependency for config we already have a parser for.

---

## 2. Consent

Sharing prompts is a decision a developer must make knowingly. Rules:

- **Off by default.** `share.enabled` is false until someone sets it. `init` does not ask;
  a prompt during install gets clicked through.
- **Never an implicit first push.** `pblame push` with sharing disabled explains what
  would be sent and exits non-zero without sending.
- **Preview before the first send.** `pblame push --dry-run` prints the exact redacted
  text of every receipt that would leave, plus a per-detection summary. The gate question
  for this whole phase is whether someone reads that output and is comfortable.
- **Per-repo, not global.** A config in the repo root, so enabling it for one project says
  nothing about another.

---

## 3. Push and pull

### Reuse from blameprompt's hook shell (`src/git/hooks.rs`)

Their `pre-push` has hard-won details worth taking verbatim:

- A recursion guard (`BLAMEPROMPT_NOTES_PUSH=1`) so pushing notes does not re-trigger the
  hook.
- `--no-verify` on the inner push, same reason.
- Resolving the *real* git binary to avoid going back through a wrapper shim.
- Backgrounding with every fd redirected, so the outer push is not held open by the inner
  one, plus a short sleep so the two pushes do not race for one SSH socket.
- A `post-checkout` fetch so a fresh clone picks notes up.

### Diverge

- **Fetch must merge, not clobber.** `git fetch origin refs/notes/pblame:refs/notes/pblame-remote`
  into a temporary ref, then `git notes merge --strategy=union refs/notes/pblame-remote`.
  Never the `+` force refspec.
- **Push must handle rejection.** On non-fast-forward: fetch, merge, retry once. Never
  force.

### Commands

| | |
|---|---|
| `pblame push [--dry-run] [--remote R]` | redact, then push the notes ref |
| `pblame pull [--remote R]` | fetch into a temp ref and merge with `union` |
| `pblame redact <file\|->` | run the engine over text and print what it finds — lets someone tune patterns without recording anything (their `redact_test.rs`) |

`doctor` gains: is sharing enabled, is the notes ref ahead of or behind the remote, and
are there unredacted high-severity detections in shareable history.

---

## 4. Order of work

1. JSONL note format + `notes.read` accepting both (tests: old note still reads, union
   merge of two notes produces both receipts).
2. `redact.py` — ported patterns, entropy, both modes, config. Tests including the
   `lodash@4.17.21` false positive as a regression.
3. Detection at capture: store detections on the receipt, surface in `doctor`.
4. Config loading, `share.enabled`, `pblame redact`.
5. `pblame push --dry-run`, then real push; `pblame pull` with merge.
6. `pre-push` + `post-checkout` hooks, ported mechanics.
7. Two-clone integration test: A records and pushes, B clones, pulls, and sees A's
   prompts; both push and neither loses data.

## Non-goals

- A server or hosted index. Notes-on-a-remote is the whole mechanism for now.
- Per-person access control. Whoever can read the repo can read the notes.
- Encrypting notes at rest.
- Redacting the *code* in a diff — only prompt text is filtered.
- Retroactively redacting already-recorded local history (`uninstall --purge` is the
  blunt tool that exists).

## Open questions

1. **Should redaction be reversible for the author?** Keeping a local map from placeholder
   back to the original would let the author read their own history in full while the
   shared copy stays clean. It also creates a secrets file on disk. Current lean: no map,
   local verbatim + shared redacted is enough.
2. **What happens when redaction changes a prompt's meaning?** `"use the key sk-abc..."`
   becomes `"use the key [REDACTED_API_KEY]"`, which is fine, but a prompt that is *mostly*
   secret becomes noise. Drop the receipt from the shared copy above some redaction ratio,
   or ship the noise and let the reader see that a prompt was mostly secret?
3. **Do we want prompts on the remote at all, or only a hash plus metadata?** A more
   conservative product ships "this line came from a prompt by X at T, 47 characters,
   2 secrets redacted" and keeps the text local. Weaker for review, much easier to adopt.
   Worth asking the first team that says no to the full version.
