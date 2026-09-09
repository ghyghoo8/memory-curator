# Query immutability contract
The report command must never create a missing database, WAL, SHM or a truncated-name file. Use a properly URI-encoded absolute file path with mode=ro&immutable=1. Query failure must leave the directory file set and existing database bytes unchanged.

# Importer contract
The separate importer intentionally creates new databases; its open mode is not appropriate for queries.
