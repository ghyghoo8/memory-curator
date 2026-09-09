# Synthetic task environment: cc-health-exit

This is a self-contained synthetic input, not a live project or historical run.

There are two independent commands: detect-memory-health.sh is an optional notification probe; check-index.sh is an explicit requested integrity check. The optional detector uses jq. The strict checker uses its documented runtime. Evaluate: detector cannot find jq; detector finds overdue active note; strict checker finds stale index; strict checker validates a healthy index. No actual command should be run in this response.
