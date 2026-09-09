# Synthetic task environment: ue-registry-summary

This is a self-contained synthetic input, not a live project or historical run.

Note rollout.md has no frontmatter description. Existing registry line: `- [Carefully chosen label](rollout.md) — Roll back only after the reader has drained its old cursor.` The note body starts with a generic heading and does not repeat the drain detail. The writer renders `- [{label}]({file}) — {summary}`. Current fallback returns the entire original registry line as summary.
