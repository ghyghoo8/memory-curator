# Synthetic task environment: ex-readonly-query

This is a self-contained synthetic input, not a live project or historical run.

Current helper:
```python
from pathlib import Path
import sqlite3
def open_report(path: Path):
    return sqlite3.connect(str(path))
```
The database has already been built and closed. A representative pathname ends in `中文 report #1?100%.sqlite`. The consumer only executes SELECT statements. There are no writers or WAL files for the fixed fixture.
