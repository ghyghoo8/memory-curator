# Synthetic task environment: ex-current-root

This is a self-contained synthetic input, not a live project or historical run.

A search index built in directory A is copied together with all notes into directory B. The database row is {"file": "policy.md", "path": "/old/A/policy.md"}. The helper gets current_root: Path and file: str; index validation has already succeeded for B. It must not consult A. Path resolution may use the current temporary filesystem in a later test, but this response is code only.
