# Allowed backup condition
When the configured backup is explicitly enabled, a network error, timeout or 5xx retries the whole original batch once on that backup. Never combine vectors from different attempts.

# Do not fallback
HTTP 4xx and provider/model/revision mismatch are hard errors. Never send those requests to the backup. Never log credentials.
