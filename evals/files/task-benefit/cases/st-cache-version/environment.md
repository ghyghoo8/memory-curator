# Synthetic task environment: st-cache-version

This is a self-contained synthetic input, not a live project or historical run.

Current authoritative contract for fictional release R1: JSON source schema is 4. SQLite manifest schema is 2 and source_index_schema must equal 4. Reject unsupported or absent versions before source validation or any adapter call. Explicit user-invoked rebuild is the recovery; query/check never writes caches or notes.

Examples: A={"schema_version":1}; B={"schema_version":2,"source_index_schema":3}; C={"schema_version":2,"source_index_schema":4}. All source content hashes happen to match.
