# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`memory-curator` is a **Claude Code skill** (not an application). It packages a reusable
workflow for curating and pruning a file-based agent memory library — Claude Code's
`memory/` directory + `MEMORY.md` index, or any "one fact per markdown note + one index
file" store. There is no build, lint, or test step; the deliverable is the prose and scripts
inside the markdown files.

## Layout & how the pieces relate

- `SKILL.md` — the skill entrypoint. Its YAML `frontmatter` (`name`, `description`) is what
  Claude Code keeps resident in context and uses to decide when to auto-trigger the skill.
  The body is the always-loaded main workflow: a 6-step pipeline **locate → inventory →
  6-dimension health check → keep/delete/update/merge matrix → safe execution → consistency
  gate**.
- `references/judgment-matrix.md` — the progressive-disclosure layer, loaded on demand. Holds
  the detailed delete/keep/update/merge criteria, contradiction-detection method, and the
  reusable bash scripts. `SKILL.md` deliberately stays lean and points here for fine judgment.
- `hooks/` — optional auto-reminder layer (installed with `--with-hooks`). A hook can only run
  deterministic shell, but curation needs LLM judgment, so the hooks are **detector + trigger,
  never curator**: `detect-memory-health.sh` computes cheap health signals and exits 10 when any
  threshold trips; `on-stop.sh` (Stop event, 24h cooldown) and `on-pre-push.sh` (PreToolUse/Bash,
  fires only on `git push`) emit a non-blocking `systemMessage` suggesting `/memory-curator`.
  `curator-lib.sh` is the shared lib (memory-dir resolution + `.curator-state` read/write). Actual
  delete/update still goes through SKILL.md Step 5 (user approval) — hooks never auto-delete.
- `install.sh` — symlinks the repo into `~/.claude/skills/` (global) or `./.claude/skills/`
  (with `--project`); `--with-hooks` additionally merges hook entries into `settings.json` via jq
  (idempotent — dedupes by command path, preserves existing keys).
- `README.md` — user-facing rationale and install/usage docs (bilingual zh/en).

Editing principle: keep `SKILL.md` short (frontmatter is a context cost paid every session);
push depth, tables, and scripts into `references/`. Keep the two files' scripts in sync.

## Installing for local testing

```bash
./install.sh            # symlink to ~/.claude/skills/ (global)
./install.sh --project  # symlink to ./.claude/skills/ (current project)
```

After install, the skill auto-triggers on prompts like "清理记忆 / 盘点记忆库 / tidy up
memory", or explicitly via `/memory-curator`. Restart or open a new session to pick it up.

## Non-negotiable invariants the skill enforces (preserve these when editing)

- **Deletion is irreversible** → always read a note's body before proposing delete (confirm no
  unique experience the rules files/code don't already capture), and present a list to the user
  before executing.
- **File and index are deleted/updated as a pair** — never leave `MEMORY.md` out of sync.
- **Terminal consistency gate must pass**: `file count == index count`, no dead links, no
  orphans. The check scripts live in both `SKILL.md` Step 6 and `references/judgment-matrix.md` §4.
- After a successful curation, SKILL.md Step 6 stamps `<memory_dir>/.curator-state`
  (`last_curation_epoch` / `last_curation_sha`) — this is the baseline the hooks' "days/commits
  since last curation" signals read. The hooks write `last_notify_epoch` to that same file for
  cooldown; keep the keys non-conflicting when editing either side.
- Hooks must fail safe: a missing `jq` or unresolved memory dir → exit 0 silently, never block the
  user's Stop/push.
- Bash scripts target macOS/BSD (`stat -f`, `date -r`); keep that compatibility if extending them.
