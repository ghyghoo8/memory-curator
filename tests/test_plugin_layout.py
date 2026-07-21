import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "memory-curator"
SKILL_ROOT = PLUGIN_ROOT / "skills" / "memory-curator"


class PluginLayoutTest(unittest.TestCase):
    def test_marketplace_points_to_the_bundled_plugin(self) -> None:
        marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

        self.assertEqual(marketplace["name"], "memory-curator")
        self.assertEqual(marketplace["interface"]["displayName"], "Memory Curator")
        self.assertEqual(len(marketplace["plugins"]), 1)

        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "memory-curator")
        self.assertEqual(
            entry["source"],
            {"source": "local", "path": "./plugins/memory-curator"},
        )
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )
        self.assertEqual(entry["category"], "Productivity")
        self.assertTrue(PLUGIN_ROOT.is_dir())

    def test_manifest_exposes_the_memory_curator_skill(self) -> None:
        manifest_path = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], PLUGIN_ROOT.name)
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(manifest["interface"]["displayName"], "Memory Curator")
        self.assertTrue((SKILL_ROOT / "SKILL.md").is_file())

        skill_frontmatter = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("\nname: memory-curator\n", skill_frontmatter)

    def test_legacy_installer_links_the_canonical_plugin_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()

            subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--project"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )

            installed = project / ".codex" / "skills" / "memory-curator"
            self.assertTrue(installed.is_symlink())
            self.assertEqual(installed.resolve(), SKILL_ROOT.resolve())


if __name__ == "__main__":
    unittest.main()
