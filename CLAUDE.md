# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`memory-curator` is a **Codex plugin** (not an application) with a bundled skill and legacy
Claude Code compatibility. It packages a reusable workflow for curating and pruning a file-based agent
memory library — Codex project `.codex/memory/` + `MEMORY.md`, legacy Claude Code memory,
or any "one fact per markdown note + one index file" store. There is no build step; the deliverable is the prose and scripts
inside the markdown files.

## Layout & how the pieces relate

- `.agents/plugins/marketplace.json` — the repo marketplace catalog used by Codex plugin CLI.
- `plugins/memory-curator/.codex-plugin/plugin.json` — the required plugin manifest.
- `plugins/memory-curator/skills/memory-curator/SKILL.md` — the canonical skill entrypoint.
  Its YAML `frontmatter` (`name`, `description`) is what
  Claude Code keeps resident in context and uses to decide when to auto-trigger the skill.
  The body is the always-loaded main workflow: a 6-step pipeline **locate → inventory →
  6-dimension health check → keep/delete/update/merge matrix → safe execution → consistency
  gate**.
- `plugins/memory-curator/skills/memory-curator/references/judgment-matrix.md` — the
  progressive-disclosure layer, loaded on demand. Holds
  the detailed delete/keep/update/merge criteria, contradiction-detection method, and the
  reusable bash scripts. `SKILL.md` deliberately stays lean and points here for fine judgment.
- `plugins/memory-curator/skills/memory-curator/scripts/` — deterministic helpers for
  token-frugal memory infrastructure:
  `inventory-memory.sh` prints a compact live inventory, `build-index.sh` creates
  `.curator-index.json`, `check-index.sh` strictly enforces note/MEMORY.md/JSON content
  consistency, `route-memory.sh` selects the top relevant notes for Chinese or English queries,
  and `mark-curated.sh` records the baseline only after the strict gate passes.
- `plugins/memory-curator/skills/memory-curator/hooks/` — deterministic health detector plus
  legacy Claude Code hook adapters. Codex uses
  `detect-memory-health.sh` directly when an external reminder is desired. `on-stop.sh` and
  `on-pre-push.sh` remain compatibility adapters only; they emit a non-blocking `systemMessage`
  and never curate. Actual delete/update still goes through SKILL.md Step 5 (user approval).
- Root `SKILL.md`, `scripts/`, `references/`, `hooks/`, `docs/`, and `poc/` are compatibility
  symlinks to the canonical bundled skill; do not add runtime files only at the repo root.
- `install.sh` — legacy-compatible installer that symlinks the canonical bundled skill into
  `${CODEX_HOME:-~/.codex}/skills/` (global) or
  `./.codex/skills/` (with `--project`); `--with-claude-hooks` additionally merges legacy Claude
  hook entries into `settings.json` via jq.
- `README.md` — user-facing rationale and install/usage docs (bilingual zh/en).

Editing principle: edit the canonical files under
`plugins/memory-curator/skills/memory-curator/`; keep `SKILL.md` short (frontmatter is a context
cost paid every session) and push depth, tables, and scripts into `references/`.

## Installing for local testing

```bash
codex plugin marketplace add "$PWD"
codex plugin add memory-curator@memory-curator
```

Use `./install.sh` only for legacy skill-only testing. After install, the skill triggers on prompts
like "清理记忆 / 盘点记忆库 / tidy up memory", or explicitly by mentioning
`memory-curator`. Restart or open a new session to pick it up.

## Non-negotiable invariants the skill enforces (preserve these when editing)

- **Deletion is irreversible** → always read a note's body before proposing delete (confirm no
  unique experience the rules files/code don't already capture), and present a list to the user
  before executing.
- **File and index are deleted/updated as a pair** — never leave `MEMORY.md` out of sync.
- **Terminal consistency gate must pass**: note file count == `MEMORY.md` entry count ==
  `.curator-index.json` entry count, source hashes match, no dead links, no orphans.
- **Token budget comes first**: use `.curator-index.json` and `route-memory.sh` to choose a small
  top-N set before reading full note bodies. Do not load the whole memory library for ordinary
  tasks.
- After a successful curation, SKILL.md Step 6 stamps `<memory_dir>/.curator-state`
  (`last_curation_epoch` / `last_curation_sha`) — this is the baseline the hooks' "days/commits
  since last curation" signals read. The hooks write `last_notify_epoch` to that same file for
  cooldown; keep the keys non-conflicting when editing either side.
- Detector and legacy hooks must fail safe: a missing `jq` or unresolved memory dir → exit 0
  silently, never block the user's Stop/push.
- Bash scripts target macOS/BSD (`stat -f`, `date -r`); keep that compatibility if extending them.
