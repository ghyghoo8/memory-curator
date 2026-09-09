# Synthetic task environment: cc-quoted-comma

This is a self-contained synthetic input, not a live project or historical run.

Examples:
A: evidence_refs: [AGENTS.md, docs/a.md]
B: evidence_refs: ["docs/a,b.md", "docs/c.md"]
C:
evidence_refs:
  - "docs/a,b.md"
  - docs/c.md
Unsupported sample: evidence_refs: [{path: docs/a.md}]
This exercise concerns an intentionally finite YAML subset, with scalar strings and lists. Do not install a YAML package or build a general YAML engine.
