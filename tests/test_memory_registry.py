#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "memory_registry", ROOT / "scripts" / "memory_registry.py"
)
assert SPEC and SPEC.loader
memory_registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = memory_registry
SPEC.loader.exec_module(memory_registry)


class MemoryRegistryTests(unittest.TestCase):
    def test_groups_active_by_layer_and_inactive_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "MEMORY.md").write_text(
                "- [Human active](active.md) - old\n- [Human old](old.md) - old\n",
                encoding="utf-8",
            )
            for filename, layer, status in (
                ("active.md", "L3", "active"),
                ("old.md", "L1", "superseded"),
            ):
                (memory_dir / filename).write_text(
                    f"""---
name: {filename[:-3]}
description: {filename} summary
metadata:
  type: project
  layer: {layer}
  domain: test
  status: {status}
  freshness: timeless
  stability: stable
  risk: normal
---
Body.
""",
                    encoding="utf-8",
                )

            rendered = memory_registry.render_registry(memory_dir)

            self.assertIn("## Active L3", rendered)
            self.assertIn("[Human active](active.md)", rendered)
            self.assertIn("## Superseded", rendered)
            self.assertIn("[Human old](old.md)", rendered)
            self.assertLess(rendered.index("## Active L3"), rendered.index("## Superseded"))

    def test_apply_preserves_registry_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            registry = memory_dir / "MEMORY.md"
            registry.write_text("- [Old](a.md) - old\n", encoding="utf-8")
            os.chmod(registry, 0o644)
            (memory_dir / "a.md").write_text(
                """---
name: a
description: New
metadata:
  type: project
  layer: L2
  domain: test
  status: active
  freshness: timeless
  stability: stable
  risk: normal
---
Body.
""",
                encoding="utf-8",
            )

            memory_registry.write_registry(memory_dir, apply=True)

            self.assertEqual(stat.S_IMODE(registry.stat().st_mode), 0o644)


if __name__ == "__main__":
    unittest.main()
