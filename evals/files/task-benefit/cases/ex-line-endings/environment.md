# Synthetic task environment: ex-line-endings

This is a self-contained synthetic input, not a live project or historical run.

The function edits the single top-level title field inside frontmatter bounded by lines containing only ---. Input example as Python bytes: b'---\r\ntitle: Old\r\nowner: user\r\n---\r\nBody stays.\r\n'. Requested title: New. Titles for this exercise contain only ASCII letters and spaces. No disk writes are needed.
