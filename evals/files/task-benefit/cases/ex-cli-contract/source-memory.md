# memory-list consumer contract
The shell consumer parses stdout as exactly one JSON object: {"files": [relative filenames]}. Diagnostics go to stderr. Valid --limit is an integer in [1, 20]; invalid or unknown arguments exit 2 and leave stdout empty. Success exits 0.

# Old unrelated progress output
A separate human-only importer prints "Starting import" to stdout before work; that importer is not memory-list.
