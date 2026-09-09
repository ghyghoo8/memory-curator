# Result provenance contract
Construct output paths from the caller's current library root and validated relative filename. Reject absolute filenames, directory traversal and symlinks resolving outside the current root. The database's stored absolute path is historical metadata and never an authority after copying.

# Old example output
A historical example displayed /old/A/policy.md because A was the current root in that run.
