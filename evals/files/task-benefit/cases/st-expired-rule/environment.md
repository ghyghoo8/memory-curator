# Synthetic task environment: st-expired-rule

This is a self-contained synthetic input, not a live project or historical run.

Fixed today: 2026-09-08 (no wall-clock lookup). Current default routing includes only status=active notes whose review_after is null or is greater than or equal to today. It does not change note metadata. Notes: a.md active/null; b.md active/2026-09-07; c.md inactive/2026-10-01; d.md active/2026-09-08.
