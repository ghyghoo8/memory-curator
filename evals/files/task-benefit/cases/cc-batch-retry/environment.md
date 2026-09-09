# Synthetic task environment: cc-batch-retry

This is a self-contained synthetic input, not a live project or historical run.

One requested embedding batch contains IDs [A,B,C]. The primary endpoint may produce one of: network timeout, HTTP 503, HTTP 400, or a successful full response with mismatched model revision. The user has explicitly enabled the configured backup endpoint for this batch. Return pseudocode and a table only; do not contact any endpoint.
