---
name: sandbox-policy
description: User prefers following approval flow for sandbox and network failures.
metadata:
  type: feedback
  status: active
  stability: stable
  freshness: timeless
  risk: high-if-wrong
  scope: [codex, shell, permissions]
  entities: [sandbox, approval, network]
---

When a command fails because of sandbox or network restrictions, follow the approval flow instead of inventing a workaround.

**Why:** This prevents hidden permission drift.
**How to apply:** Retry important blocked commands with the proper escalation request.
