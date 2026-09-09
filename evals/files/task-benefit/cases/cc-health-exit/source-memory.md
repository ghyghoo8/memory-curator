# Non-blocking detector
Missing jq or unresolved memory directory must make the optional detector exit 0 silently. Real notification-worthy findings exit 10. Legacy Stop/push adapters always avoid blocking the user's command.

# Strict integrity check
An explicit check must fail nonzero on stale/missing/inconsistent indexes. It must not auto-rebuild to manufacture success.
