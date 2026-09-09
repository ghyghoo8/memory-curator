# Synthetic task environment: ue-same-stat

This is a self-contained synthetic input, not a live project or historical run.

Proposed code:
```python
if saved_size == path.stat().st_size and saved_mtime == path.stat().st_mtime_ns:
    return saved_hash
return sha256(path.read_bytes()).hexdigest()
```
The present command promises to reject any changed source content before serving a cached result. It is a one-shot local CLI, not a resident service. No measured need for a new watcher or cache system exists.
