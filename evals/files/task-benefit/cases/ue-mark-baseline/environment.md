# Synthetic task environment: ue-mark-baseline

This is a self-contained synthetic input, not a live project or historical run.

Current .curator-state bytes are `last_notify_epoch=123\nlast_curation_epoch=100\n`. The note/index/hash strict check succeeds. The governance check fails because an active note is overdue. The current implementation writes a fresh last_curation_epoch immediately after strict succeeds. The optional detector uses the last-curation stamp as its baseline. No actual memory files may be modified in this task.
